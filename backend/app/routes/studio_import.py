"""Studio 路由 · 导入域：上传文件/压缩包与按 URL 抓取。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from ..studio import importer, installer, store
from ._responses import fail as _err
from .studio_common import _require_admin

router = APIRouter()


@router.post("/api/studio/import")
async def studio_import(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    kind: str = Form(""),
) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    default_kind = kind.strip() or None
    if default_kind and default_kind not in store.ASSET_KINDS:
        return _err(f"未知资产类型：{default_kind}")
    uploads = [f for f in ([file] if file else []) + (files or []) if f is not None]
    if not uploads:
        return _err("请选择要导入的文件")
    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for upload in uploads:
        name = upload.filename or "upload"
        data = await upload.read()
        try:
            entries = importer.parse_file(data, name, default_kind)
        except importer.ImportErrorDetail as exc:
            errors.append({"file": name, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 — 解析异常逐文件回报
            errors.append({"file": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for entry in entries:
            if "__zip_errors__" in entry:
                errors.extend(entry["__zip_errors__"])
                continue
            try:
                existing_ids = {a["id"] for a in await store.list_assets(entry["kind"])}
                replaced = entry["id"] in existing_ids
                asset = await store.upsert_asset(entry["kind"], entry["id"], entry["asset"])
                saved.append(
                    {
                        "kind": entry["kind"],
                        "id": entry["id"],
                        "name": asset.get("name", ""),
                        "file": name,
                        # 覆盖同名资产时要让用户知道（否则「导入 3 个只剩 1 个」无从察觉）
                        "replaced": replaced,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({"file": entry.get("source") or name, "error": str(exc)})
    return {"ok": bool(saved) or not errors, "saved": saved, "errors": errors}


@router.post("/api/studio/import/url")
async def studio_import_url(payload: dict) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    url = str((payload or {}).get("url") or "").strip()
    kind = str((payload or {}).get("kind") or "").strip() or None
    if not url:
        return _err("url 必填")
    if not await store.cli_admin_allowed() and not (await store.get_config()).get("permissions", {}).get(
        "allow_remote_install", True
    ):
        return _err("远程安装已被权限设置关闭", 403)
    # SSRF 防护：这是管理员接口，但管理员也不该被诱导去读取内网/云 metadata
    from ..netguard import SSRFBlocked, assert_public_http_url

    try:
        url = assert_public_http_url(url)
    except SSRFBlocked as exc:
        return _err(str(exc))
    try:
        result = await installer.install_remote(url, kind)
    except ValueError as exc:
        return _err(str(exc))
    except Exception as exc:  # noqa: BLE001 — 网络异常如实回报
        return _err(f"下载失败：{type(exc).__name__}: {exc}", 502)
    return result


# ---------------------------------------------------------------------------
# AI 一键生成
# ---------------------------------------------------------------------------
