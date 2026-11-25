"""外部投递通道（4.22.0）：真实 SMTP 发信与签名 HTTPS 网关。

边界：
- SMTP 只证明邮件服务器受理，不证明对方已读；状态用 `accepted`，不用 `delivered`。
- 签名网关只证明对端返回 2xx 并给出回执；税局/银行是否真正入账，以持牌通道
  的官方回执为准，本系统不伪造申报成功或支付成功。
- 没有密钥、没有启用、没有服务商地址时一律 fail-closed，不静默降级成本地成功。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlparse

import httpx

from . import db
from .external_packets import consolidation_packet, payment_packet, tax_packet
from .timeutil import now_iso

MAX_ATTACHMENT_BYTES = 6 * 1024 * 1024
_MAX_BODY = 2048
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9_.:\-\[\]]{1,253}$")

CHANNEL_SPECS: dict[str, dict[str, Any]] = {
    "smtp": {
        "id": "smtp",
        "transport": "smtp",
        "kinds": ["tax", "payment", "consolidation"],
        "secret_fields": ["password"],
        "config_fields": [
            "host",
            "port",
            "security",
            "username",
            "from_addr",
            "to_addrs",
            "subject_prefix",
        ],
        "label": "邮箱投递",
    },
    "tax_gateway": {
        "id": "tax_gateway",
        "transport": "https",
        "kinds": ["tax"],
        "secret_fields": ["signing_secret"],
        "config_fields": ["endpoint", "provider_name", "timeout_sec"],
        "label": "税费申报网关",
    },
    "bank_gateway": {
        "id": "bank_gateway",
        "transport": "https",
        "kinds": ["payment"],
        "secret_fields": ["signing_secret"],
        "config_fields": ["endpoint", "provider_name", "timeout_sec"],
        "label": "付款指令网关",
    },
    "audit_gateway": {
        "id": "audit_gateway",
        "transport": "https",
        "kinds": ["consolidation"],
        "secret_fields": ["signing_secret"],
        "config_fields": ["endpoint", "provider_name", "timeout_sec"],
        "label": "审计交接网关",
    },
}


def _local_allowed() -> bool:
    return os.getenv("MH_ALLOW_LOCAL_CHANNELS", "").strip() in ("1", "true", "yes")


def _is_local_host(host: str) -> bool:
    value = host.strip("[]").lower()
    if value in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_loopback


def _host_private(host: str) -> bool:
    value = host.strip("[]").lower()
    if value == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _valid_email(value: str) -> str:
    addr = str(value or "").strip()
    if "\r" in addr or "\n" in addr:
        raise ValueError("邮箱地址不能包含换行")
    name, parsed = parseaddr(addr)
    if not parsed or not _EMAIL_RE.match(parsed):
        raise ValueError(f"邮箱地址无效：{addr[:60]}")
    if len(parsed) > 254:
        raise ValueError("邮箱地址过长")
    return f"{name} <{parsed}>" if name else parsed


def _emails(value: Any) -> list[str]:
    raw: list[Any]
    if isinstance(value, str):
        raw = [item for item in re.split(r"[,;，；\n]", value)]
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = []
    items = [_valid_email(str(item)) for item in raw if str(item).strip()]
    if len(items) > 5:
        raise ValueError("收件人最多 5 个")
    return items


def _int(value: Any, default: int, low: int, high: int, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < low or parsed > high:
        raise ValueError(f"{field} 必须在 {low}–{high} 之间")
    return parsed


def _host(value: Any) -> str:
    host = str(value or "").strip()
    if not host or not _HOST_RE.match(host) or "://" in host or "/" in host:
        raise ValueError("主机名无效")
    if host.startswith("-") or host.endswith("-"):
        raise ValueError("主机名无效")
    return host


def _endpoint(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) > 500 or "\r" in raw or "\n" in raw:
        raise ValueError("网关地址无效")
    parsed = urlparse(raw)
    if parsed.username or parsed.password:
        raise ValueError("网关地址不能内嵌账号密码")
    if parsed.scheme == "https":
        if not parsed.hostname:
            raise ValueError("网关地址缺少主机")
    elif parsed.scheme == "http":
        if not (_local_allowed() and _is_local_host(parsed.hostname or "")):
            raise ValueError(
                "外部网关必须使用 HTTPS；本机测试需显式开启 MH_ALLOW_LOCAL_CHANNELS"
            )
    else:
        raise ValueError("网关地址只支持 HTTPS")
    if _host_private(parsed.hostname or "") and not (
        _local_allowed() and _is_local_host(parsed.hostname or "")
    ):
        raise ValueError("网关地址不能指向内网/保留地址")
    return raw


def normalize_config(channel_id: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """只接受白名单字段，拒绝把任意 JSON 塞进通道配置。"""
    spec = CHANNEL_SPECS.get(channel_id)
    if spec is None:
        raise ValueError(f"不支持的通道：{channel_id}")
    raw = dict(config or {})
    if channel_id == "smtp":
        host = _host(raw.get("host"))
        port = _int(raw.get("port"), 587, 1, 65535, "端口")
        security = str(raw.get("security") or "starttls").strip().lower()
        if security not in ("starttls", "ssl", "none"):
            raise ValueError("加密方式必须是 starttls / ssl / none")
        if security == "none" and not (_local_allowed() and _is_local_host(host)):
            raise ValueError("明文 SMTP 只允许本机测试；外部邮箱必须启用 TLS")
        username = str(raw.get("username") or "").strip()
        if "\r" in username or "\n" in username or len(username) > 120:
            raise ValueError("用户名无效")
        from_addr = _valid_email(str(raw.get("from_addr") or username))
        to_addrs = _emails(raw.get("to_addrs"))
        if not to_addrs:
            raise ValueError("至少一个收件人")
        prefix = str(raw.get("subject_prefix") or "[Moneyhelper]").strip()
        if "\r" in prefix or "\n" in prefix or len(prefix) > 40:
            raise ValueError("邮件主题前缀无效")
        return {
            "host": host,
            "port": port,
            "security": security,
            "username": username,
            "from_addr": from_addr,
            "to_addrs": to_addrs,
            "subject_prefix": prefix,
        }

    endpoint = _endpoint(raw.get("endpoint"))
    provider = str(raw.get("provider_name") or "").strip()
    if len(provider) > 60 or "\r" in provider or "\n" in provider:
        raise ValueError("服务商名称无效")
    timeout = _int(raw.get("timeout_sec"), 15, 5, 30, "超时")
    return {"endpoint": endpoint, "provider_name": provider, "timeout_sec": timeout}


def normalize_secret(
    channel_id: str, secret: dict[str, Any] | None
) -> dict[str, Any] | None:
    if secret is None:
        return None
    if channel_id == "smtp":
        password = str((secret or {}).get("password") or "")
        if "\r" in password or "\n" in password or len(password) > 256:
            raise ValueError("邮箱密码无效")
        return {"password": password} if password else None
    signing = str((secret or {}).get("signing_secret") or "")
    if len(signing) < 16 or len(signing) > 128:
        raise ValueError("签名密钥长度需在 16–128 字符")
    if "\r" in signing or "\n" in signing:
        raise ValueError("签名密钥不能包含换行")
    return {"signing_secret": signing}


def readiness(channel: dict[str, Any]) -> tuple[bool, list[str]]:
    cid = str(channel.get("channel_id") or "")
    spec = CHANNEL_SPECS.get(cid)
    if spec is None:
        return False, ["unknown"]
    missing: list[str] = []
    if not channel.get("enabled"):
        missing.append("disabled")
    cfg = channel.get("config") or {}
    if cid == "smtp":
        for key in ("host", "port", "from_addr", "to_addrs"):
            if not cfg.get(key):
                missing.append(str(key))
        if cfg.get("security") == "none" and not _local_allowed():
            missing.append("smtp_tls")
        if cfg.get("username") and not channel.get("configured"):
            missing.append("password")
    else:
        if not cfg.get("endpoint"):
            missing.append("endpoint")
        if not channel.get("configured"):
            missing.append("signing_secret")
    return (not missing), missing


def channel_list() -> list[dict[str, Any]]:
    """同步返回目录；路由负责补数据库状态。"""
    return [dict(spec) for spec in CHANNEL_SPECS.values()]


async def list_channels() -> dict[str, Any]:
    rows = {row["channel_id"]: row for row in await db.external_list_channels()}
    items: list[dict[str, Any]] = []
    for spec in CHANNEL_SPECS.values():
        stored = rows.get(spec["id"], {})
        item = {
            **spec,
            "channel_id": spec["id"],
            "config": stored.get("config") or {},
            "enabled": bool(stored.get("enabled")),
            "configured": bool(stored.get("configured")),
            "last_test_at": stored.get("last_test_at") or "",
            "last_test_ok": stored.get("last_test_ok"),
            "last_test_detail": stored.get("last_test_detail") or "",
            "updated_at": stored.get("updated_at") or "",
        }
        ready, missing = readiness(item)
        item["ready"] = ready
        item["missing"] = missing
        items.append(item)
    stats = await db.external_delivery_stats()
    return {
        "channels": items,
        "deliveries": await db.external_list_deliveries(30),
        "stats": stats,
        "boundary": "通道只证明对端受理；税局申报成功、银行支付成功仍以持牌通道官方回执为准。",
    }


async def save_channel(
    channel_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    cid = str(channel_id or "").strip().lower()
    config = normalize_config(
        cid, body.get("config") if isinstance(body.get("config"), dict) else {}
    )
    secret = normalize_secret(
        cid, body.get("secret") if isinstance(body.get("secret"), dict) else None
    )
    if cid == "smtp" and config.get("username") and secret is None:
        existing = await db.external_get_secret(cid)
        if not existing or not existing.get("password"):
            raise ValueError("填了 SMTP 用户名就必须提供密码")
    if cid != "smtp" and secret is None:
        existing = await db.external_get_secret(cid)
        if not existing or not existing.get("signing_secret"):
            raise ValueError("网关通道必须提供签名密钥")
    saved = await db.external_save_channel(
        cid,
        label=str(body.get("label") or CHANNEL_SPECS[cid]["label"])[:60],
        config=config,
        secret=secret,
        enabled=bool(body.get("enabled")),
    )
    ready, missing = readiness({**saved, **CHANNEL_SPECS[cid]})
    return {
        "channel": {**saved, **CHANNEL_SPECS[cid], "ready": ready, "missing": missing}
    }


async def delete_channel(channel_id: str) -> dict[str, Any]:
    deleted = await db.external_delete_channel(channel_id)
    return {"deleted": deleted, "channel_id": channel_id}


async def _smtp_send(
    config: dict[str, Any],
    secret: dict[str, Any] | None,
    *,
    subject: str,
    text: str,
    attachments: list[tuple[str, str, str]],
    to_addrs: list[str] | None = None,
) -> dict[str, Any]:
    recipients = list(to_addrs or config["to_addrs"])
    msg = EmailMessage()
    msg["From"] = config["from_addr"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject[:180]
    msg.set_content(text)
    total = 0
    for filename, content, mime in attachments:
        data = content.encode("utf-8")
        total += len(data)
        if total > MAX_ATTACHMENT_BYTES:
            raise ValueError("附件超过 6 MB，拒绝发送")
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    host, port, security = config["host"], int(config["port"]), config["security"]
    username = config.get("username") or ""
    password = (secret or {}).get("password") or ""
    context = ssl.create_default_context()

    def _run() -> dict[str, Any]:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=15, context=context
            )
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        try:
            server.ehlo()
            if security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if username:
                server.login(username, password)
            refused = server.send_message(
                msg, from_addr=config["from_addr"], to_addrs=recipients
            )
            message_id = str(msg.get("Message-ID") or "")
            return {
                "transport": "smtp",
                "host": f"{host}:{port}",
                "accepted": recipients,
                "refused": {str(k): str(v)[:120] for k, v in (refused or {}).items()},
                "message_id": message_id,
                "attachment_bytes": total,
            }
        finally:
            try:
                server.quit()
            except Exception:
                pass

    return await asyncio.to_thread(_run)


async def _http_send(
    config: dict[str, Any],
    secret: dict[str, Any],
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    channel_id: str,
) -> dict[str, Any]:
    endpoint = config["endpoint"]
    timeout = int(config.get("timeout_sec") or 15)
    body = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    signing = str(secret.get("signing_secret") or "")
    signature = hmac.new(
        signing.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Moneyhelper-External-Gateway/4.22.0",
        "X-MH-Channel": channel_id,
        "X-MH-Timestamp": timestamp,
        "X-MH-Signature": f"sha256={signature}",
        "Idempotency-Key": idempotency_key,
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(endpoint, content=body, headers=headers)
    text = response.text[:_MAX_BODY]
    receipt: dict[str, Any] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            for key in ("receipt_id", "id", "request_id", "code", "message", "status"):
                if key in parsed:
                    receipt[key] = str(parsed[key])[:180]
    except ValueError:
        pass
    return {
        "transport": "https",
        "host": urlparse(endpoint).hostname or "",
        "status_code": response.status_code,
        "receipt_id": str(
            receipt.get("receipt_id")
            or receipt.get("id")
            or receipt.get("request_id")
            or ""
        ),
        "remote": receipt,
        "body_excerpt": text,
    }


async def test_channel(
    channel_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    cid = str(channel_id or "").strip().lower()
    stored = await db.external_get_channel(cid)
    if not stored:
        raise ValueError("通道未配置")
    config = stored.get("config") or {}
    if cid != "smtp":
        config = normalize_config(cid, config)
    secret = await db.external_get_secret(cid)
    override = (
        body.get("config")
        if isinstance(body, dict) and isinstance(body.get("config"), dict)
        else None
    )
    if override:
        config = normalize_config(cid, override)
    try:
        if cid == "smtp":
            result = await _smtp_send(
                normalize_config(cid, config),
                secret,
                subject=f"{config.get('subject_prefix', '[Moneyhelper]')} 邮箱通道测试",
                text=(
                    "这是一封通道测试邮件，由 Moneyhelper 本机发起。\n"
                    "收到即说明 SMTP 服务器已受理；不代表任何申报或付款动作。\n"
                    f"时间：{now_iso()}\n"
                ),
                attachments=[],
            )
        else:
            result = await _http_send(
                normalize_config(cid, config),
                secret or {},
                {"event": "probe", "channel_id": cid, "generated_at": now_iso()},
                idempotency_key=f"probe-{cid}-{int(time.time())}",
                channel_id=cid,
            )
        ok = True
        detail = "对端已受理测试请求" if cid != "smtp" else "SMTP 服务器已受理测试邮件"
        if cid != "smtp" and int(result.get("status_code") or 0) >= 300:
            ok = False
            detail = f"网关返回 HTTP {result.get('status_code')}"
        elif cid == "smtp" and result.get("refused"):
            ok = False
            detail = "部分收件人被 SMTP 服务器拒绝"
        await db.external_mark_test(cid, ok, detail)
        return {"ok": ok, "detail": detail, "receipt": result}
    except Exception as exc:  # noqa: BLE001 — 网络异常要落测试状态并回给用户
        detail = f"测试失败：{str(exc)[:180]}"
        await db.external_mark_test(cid, False, detail)
        return {"ok": False, "detail": detail, "receipt": {}}


def _packet_files(kind: str, packet: dict[str, Any]) -> list[tuple[str, str, str]]:
    packet_id = str(packet.get("packet_id") or "packet")
    files = [
        (
            f"{packet_id}.json",
            json.dumps(packet, ensure_ascii=False, indent=2),
            "application/json",
        ),
        (f"{packet_id}.sha256.txt", str(packet.get("source_hash") or ""), "text/plain"),
    ]
    if kind == "payment" and isinstance(packet.get("instructions"), list):
        header = [
            "seq",
            "expected_date",
            "account_code",
            "counterparty",
            "amount",
            "certainty",
            "note",
        ]
        rows = [header]
        for item in packet["instructions"]:
            rows.append(
                [
                    str(item.get("seq", "")),
                    str(item.get("expected_date", "")),
                    str(item.get("account_code", "")),
                    str(item.get("counterparty", "")),
                    str(item.get("amount", "")),
                    str(item.get("certainty", "")),
                    str(item.get("note", "")),
                ]
            )
        csv_text = "\n".join(",".join(_csv_cell(cell) for cell in row) for row in rows)
        files.append((f"{packet_id}.csv", "\ufeff" + csv_text, "text/csv"))
    return files


def _csv_cell(value: str) -> str:
    return (
        f'"{value.replace(chr(34), chr(34) * 2)}"'
        if any(ch in value for ch in '",\n')
        else value
    )


async def _build_packet(
    kind: str, tenant_id: int, user_id: int, period: str, group_id: str
) -> dict[str, Any]:
    if kind == "tax":
        return await tax_packet(tenant_id, period)
    if kind == "payment":
        return await payment_packet(tenant_id, period)
    if kind == "consolidation":
        if not str(group_id or "").strip():
            raise ValueError("合并包需要 group_id")
        return await consolidation_packet(user_id, group_id, period)
    raise ValueError("kind 必须是 tax / payment / consolidation")


async def deliver(
    channel_id: str,
    kind: str,
    tenant_id: int,
    user_id: int,
    *,
    period: str = "",
    group_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    cid = str(channel_id or "").strip().lower()
    spec = CHANNEL_SPECS.get(cid)
    if spec is None:
        raise ValueError("未知通道")
    if kind not in spec["kinds"]:
        raise ValueError("该通道不接受这类资料包")
    stored = await db.external_get_channel(cid)
    if not stored:
        raise ValueError("通道未配置")
    ready, missing = readiness({**stored, **spec})
    if not ready:
        raise ValueError("通道未就绪：" + "、".join(missing))
    config = normalize_config(cid, stored.get("config") or {})
    secret = await db.external_get_secret(cid)
    if cid == "smtp" and config.get("username") and not secret:
        raise ValueError("SMTP 用户名已配置但缺少密码")
    if cid != "smtp" and not secret:
        raise ValueError("网关缺少签名密钥")

    packet = await _build_packet(kind, tenant_id, user_id, period, group_id)
    status = str(packet.get("status") or "")
    if status == "missing":
        raise ValueError("资料包没有数据，不能向外投递")
    # “无税局直连 / 无持牌支付通道 / 非审计口径”本身就是这份包要交给外部的原因，
    # 不能让它们反过来阻断投递；其余 blocked 仍是数据质量问题，必须拦住。
    channel_limits = {
        "tax": {"filing_channel"},
        "payment": {"execution_channel"},
        "consolidation": {"audit_basis"},
    }.get(kind, set())
    blockers = [
        c
        for c in packet.get("checks") or []
        if c.get("status") == "blocked" and str(c.get("id") or "") not in channel_limits
    ]
    if blockers:
        raise ValueError(
            "资料包存在数据阻断项：" + "、".join(str(c.get("id")) for c in blockers[:3])
        )
    packet_id = str(packet["packet_id"])
    source_hash = str(packet.get("source_hash") or "")
    if not source_hash:
        raise ValueError("资料包缺少来源摘要，拒绝投递")
    idem = hashlib.sha256(
        f"{user_id}:{cid}:{kind}:{packet_id}:{source_hash}".encode()
    ).hexdigest()[:40]

    existing = await db.external_get_delivery_by_key(cid, idem)
    if existing and existing["status"] == "accepted":
        return {"duplicate": True, "delivery": existing}
    if existing and existing["status"] == "pending":
        return {"duplicate": True, "delivery": existing, "in_progress": True}

    recipient = (
        ", ".join(config.get("to_addrs") or [])[:400]
        if cid == "smtp"
        else f"{config.get('provider_name') or spec['label']} {urlparse(config['endpoint']).hostname or ''}"
    )
    files = _packet_files(kind, packet) if cid == "smtp" else []
    summary = {
        "packet_status": status,
        "checks": len(packet.get("checks") or []),
        "source_hash": source_hash,
        "note": str(note or "")[:120],
        "attachments": len(files) if cid == "smtp" else 1,
    }
    delivery = await db.external_create_delivery(
        cid,
        kind,
        packet_id,
        source_hash,
        idem,
        recipient=recipient,
        request_summary=summary,
    )
    try:
        if cid == "smtp":
            subject = f"{config['subject_prefix']} {spec['label']} {packet_id}"
            result = await _smtp_send(
                config,
                secret,
                subject=subject,
                text=(
                    f"{spec['label']}已生成，附底稿与摘要。\n"
                    f"期间：{packet.get('period') or period}\n"
                    f"摘要：{source_hash}\n"
                    f"备注：{str(note or '')[:120]}\n"
                    "本邮件只代表资料交接，不代表税局申报、银行付款或审计意见已完成。\n"
                ),
                attachments=files,
            )
            if result.get("refused"):
                raise RuntimeError(
                    "部分收件人被 SMTP 服务器拒绝："
                    + json.dumps(result["refused"], ensure_ascii=False)[:180]
                )
            receipt = result
        else:
            result = await _http_send(
                config,
                secret,
                {
                    "version": "moneyhelper-external-v1",
                    "channel": cid,
                    "kind": kind,
                    "packet_id": packet_id,
                    "source_hash": source_hash,
                    "period": packet.get("period") or period,
                    "note": str(note or "")[:120],
                    "packet": packet,
                },
                idempotency_key=idem,
                channel_id=cid,
            )
            if int(result.get("status_code") or 0) >= 300:
                raise RuntimeError(
                    f"网关返回 HTTP {result.get('status_code')}：{result.get('body_excerpt', '')[:120]}"
                )
            receipt = result
        finished = await db.external_finish_delivery(
            delivery["id"], status="accepted", receipt=receipt
        )
        # 投递成功即进入交接台账，避免“发出去了但台账没有”的断点。
        from .external_handoffs import archive_handoff

        await archive_handoff(
            tenant_id,
            user_id,
            kind,
            period,
            group_id=group_id,
            note=f"外部投递 {cid}",
        )
        await db.add_audit_log(
            "HANDOFF_SEND",
            "POST",
            f"/api/external/channels/{cid}/deliver",
            200,
            actor=f"user:{int(user_id)}",
            detail=json.dumps(
                {
                    "channel_id": cid,
                    "kind": kind,
                    "packet_id": packet_id,
                    "source_hash": source_hash,
                    "delivery_id": delivery["id"],
                    "recipient": recipient[:200],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        return {"duplicate": False, "delivery": finished}
    except Exception as exc:  # noqa: BLE001 — 失败要留痕，但不能伪装成功
        finished = await db.external_finish_delivery(
            delivery["id"], status="failed", receipt={}, error=str(exc)
        )
        await db.add_audit_log(
            "HANDOFF_SEND_FAIL",
            "POST",
            f"/api/external/channels/{cid}/deliver",
            502,
            actor=f"user:{int(user_id)}",
            detail=json.dumps(
                {
                    "channel_id": cid,
                    "kind": kind,
                    "packet_id": packet_id,
                    "source_hash": source_hash,
                    "delivery_id": delivery["id"],
                    "error": str(exc)[:240],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        raise ValueError(f"投递失败：{str(exc)[:180]}") from None


__all__ = [
    "CHANNEL_SPECS",
    "channel_list",
    "delete_channel",
    "deliver",
    "list_channels",
    "normalize_config",
    "readiness",
    "save_channel",
    "test_channel",
]
