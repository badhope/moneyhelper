"""安全 Markdown 渲染与成品导出：分享页、回答画布共用一套，避免两处各写一遍。

只放纯函数：转义、极简 Markdown、HTML 文档、无第三方依赖的 DOCX。
不读数据库、不发请求，便于单测和复用。
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape


def safe_url(url: str) -> str:
    """只放行 http/https，并转义属性里的引号；伪协议一律丢弃。"""
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme in {"http", "https"}:
            return html.escape(str(url), quote=True)
    except Exception:  # noqa: BLE001
        pass
    return ""


def inline(text: str) -> str:
    """先转义再只放行粗体/行内代码；分享页不执行任何用户 HTML。"""
    out = html.escape(str(text or ""))
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return out


def body_text(text: str) -> str:
    return inline(text).replace("\n", "<br>")


def body_html(text: str) -> str:
    """极简 Markdown：标题、粗体、行内代码、列表、代码块，无外链。"""
    lines = str(text or "").replace("\r", "").split("\n")
    out: list[str] = []
    list_tag = ""
    in_code = False
    code_buf: list[str] = []

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            close_list()
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if not stripped:
            close_list()
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1)) + 1
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet or numbered:
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{inline((bullet or numbered).group(1))}</li>")
            continue
        close_list()
        out.append(f"<p>{inline(stripped)}</p>")
    close_list()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "".join(out)


def html_document(title: str, body: str) -> str:
    """独立 HTML 成品：可直接打开、打印或再存 PDF。"""
    safe_title = html.escape(str(title or "未命名文档"))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style>
:root{{color-scheme:light dark;--bg:#f8f6f1;--card:#fff;--ink:#1d2824;--muted:#65716b;--line:#dde4df;--brand:#0f5c4a}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111917;--card:#18221f;--ink:#e8f0ec;--muted:#9aada5;--line:#2b3934;--brand:#72d6be}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}}
main{{max-width:860px;margin:0 auto;padding:40px 24px 72px;background:var(--card);border:1px solid var(--line);border-radius:18px;margin-top:32px}}
h1{{font-size:24px;margin:0 0 18px}} .meta{{color:var(--muted);font-size:12px;margin-bottom:22px}}
p{{margin:0 0 12px}} ul,ol{{margin:0 0 12px 22px}} h2,h3,h4{{margin:22px 0 10px}}
code{{background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 4px;font-size:13px}}
pre{{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px;overflow-x:auto}}
pre code{{border:0;padding:0}} footer{{margin-top:32px;color:var(--muted);font-size:12px}}
</style></head><body><main>
<h1>{safe_title}</h1>
<div class="meta">由 Moneyhelper 画布导出</div>
{body_html(body)}
<footer>本文件为静态快照，不含账户、账本或模型配置。</footer>
</main></body></html>"""


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _docx_text(text: str) -> str:
    # 去 Markdown 强调符号，保留可读文本；所有 XML 特殊字符必须转义。
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or ""))
    plain = plain.replace("`", "")
    return xml_escape(plain)


def _docx_paragraph(text: str, style: str = "Normal") -> str:
    keep = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return (
        "<w:p><w:pPr>"
        f'<w:pStyle w:val="{style}"/>'
        "</w:pPr>"
        f"<w:r><w:t{keep}>{_docx_text(text)}</w:t></w:r></w:p>"
    )


def _docx_body(title: str, text: str) -> str:
    parts: list[str] = [_docx_paragraph(title, "Title")]
    in_code = False
    code_buf: list[str] = []
    for line in str(text or "").replace("\r", "").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                parts.append(_docx_paragraph("\n".join(code_buf), "Code"))
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if not stripped:
            parts.append(_docx_paragraph("", "Normal"))
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            level = min(len(heading.group(1)), 3)
            parts.append(_docx_paragraph(heading.group(2), f"Heading{level}"))
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet:
            parts.append(_docx_paragraph("• " + bullet.group(1), "ListParagraph"))
            continue
        if numbered:
            parts.append(_docx_paragraph(stripped, "ListParagraph"))
            continue
        parts.append(_docx_paragraph(stripped, "Normal"))
    if in_code and code_buf:
        parts.append(_docx_paragraph("\n".join(code_buf), "Code"))
    return "".join(parts)


def docx_bytes(title: str, text: str) -> bytes:
    """生成最小但可被 Word/WPS/LibreOffice 打开的 DOCX，不依赖第三方库。"""
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}"><w:body>'
        + _docx_body(title, text)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        "</w:body></w:document>"
    )
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W_NS}">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="22"/></w:rPr><w:pPr><w:spacing w:after="140" w:line="360" w:lineRule="auto"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:pPr><w:spacing w:after="260"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="30"/></w:rPr><w:pPr><w:spacing w:before="260" w:after="120"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr><w:pPr><w:spacing w:before="220" w:after="100"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr><w:pPr><w:spacing w:before="180" w:after="80"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="420"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="19"/></w:rPr><w:pPr><w:spacing w:after="60" w:line="240" w:lineRule="auto"/></w:pPr></w:style>
</w:styles>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
    return buf.getvalue()
