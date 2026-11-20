"""浏览器代登录书签脚本：只回传当前页可见文本与一次性配对码。"""

from __future__ import annotations

from urllib.parse import quote

from ..logging_utils import get_logger

log = get_logger(__name__)

def build_bookmarklet(base_url: str, code: str, connector_id: str, lang: str = "zh") -> str:
    """生成一段 javascript: 书签脚本。

    作用：在用户已登录的目标平台页面上，抓取当前页面的可见文本/表格，
    以配对码回传本机服务。**不读取 cookie、不读取密码、不跨域偷数据**——
    它只能看到用户当前正在看的这一页，等价于用户自己复制粘贴。

    安全边界：脚本里只有回传地址与一次性配对码，没有用户凭据。
    """
    endpoint = f"{base_url.rstrip('/')}/api/connect/ingest?code={quote(code)}&connector_id={quote(connector_id)}"
    label = "回传本页" if lang != "en" else "Send this page"
    body = (
        "javascript:(function(){"
        "var t=document.body?document.body.innerText:'';"
        f"var u='{endpoint}';"
        "fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({title:document.title,url:location.href,text:t.slice(0,200000)})})"
        ".then(function(r){return r.json()})"
        ".then(function(j){alert(" + repr(label) + "+': '+(j&&j.ok?('OK '+(j.imported||0)+' rows'):('FAIL '+((j&&j.error)||''))))})"
        ".catch(function(e){alert('FAIL '+e)});"
        "})();"
    )
    return body
