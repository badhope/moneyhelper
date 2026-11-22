"""PDF 文本层抽取：让附件正文可搜索、可入知识库。

只处理有文本层的电子 PDF。扫描件不在这里假装识别成功：没有可抽取文本时返回
空正文和一句可读说明，由前端提示「可能是扫描件」。OCR 属于图片识别链路，
不在附件上传时隐式触发，避免 8MB 扫描件把上传请求拖成几十秒。
"""

from __future__ import annotations

import io

# 与文本附件一致：正文只留前 6000 字供预览、搜索和 BM25 切块。
CONTENT_MAX_CHARS = 6000
# 电子 PDF 前 40 页足够覆盖个人保单、合同和产品说明；再往后成本高、收益低。
MAX_PAGES = 40


def extract_pdf_text(raw: bytes, max_chars: int = CONTENT_MAX_CHARS) -> tuple[str, str]:
    """返回 (正文, 说明)。说明用于上传后的提示；成功时为空字符串。"""
    if not raw:
        return "", "文件为空"
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return "", "未安装 pypdf，PDF 正文未抽取；安装后重新上传即可"

    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 — 损坏 PDF 不阻断上传，只丢正文
        return "", f"PDF 正文未抽取：{type(exc).__name__}"

    if getattr(reader, "is_encrypted", False):
        try:
            unlocked = reader.decrypt("")
        except Exception:  # noqa: BLE001 — 加密方式不支持，按未抽取处理
            unlocked = 0
        if not unlocked:
            return "", "PDF 已加密，未抽取正文；解密后重新上传即可"

    parts: list[str] = []
    chars = 0
    failed_pages = 0
    try:
        pages = reader.pages
    except Exception as exc:  # noqa: BLE001
        return "", f"PDF 页面读取失败：{type(exc).__name__}"

    for index, page in enumerate(pages):
        if index >= MAX_PAGES:
            break
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — 单页字体/编码异常不拖垮整份文件
            failed_pages += 1
            continue
        text = str(text).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            continue
        parts.append(text)
        chars += len(text)
        if chars >= max_chars:
            break

    body = "\n\n".join(parts).strip()
    if len(body) > max_chars:
        body = body[:max_chars].rstrip()
    if body:
        return body, ""
    if failed_pages:
        return "", "PDF 页面解析失败，未抽取到正文"
    return "", "PDF 没有可提取正文，可能是扫描件；可改用图片识别"
