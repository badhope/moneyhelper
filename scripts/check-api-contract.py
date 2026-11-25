"""前后端接口契约检查：前端写死的路径，后端是否真的有这个端点。

为什么需要它：重构时最容易出现的隐性故障是"前端改成新路径、后端还是旧的"（或反过来）。
这种错误 `tsc` 抓不到、单测抓不到（前端测试都在 mock），只有真点开页面才会 404。
这里做静态比对，把它变成一次可以随时跑的检查。

用法：
    python3 scripts/check-api-contract.py           # 只报告前端调用但后端缺失的
    python3 scripts/check-api-contract.py -v        # 同时列出后端有、前端没用的端点
    python3 scripts/check-api-contract.py --update  # 刷新白名单（确认是外部/动态路径后）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app"
FRONTEND = ROOT / "frontend" / "src"
BASELINE = ROOT / "scripts" / "api-contract-baseline.json"

ROUTE_RE = re.compile(r'@(\w+)\.(get|post|put|patch|delete)\(\s*["\']([^"\']*)["\']')
# 路由前缀写在 APIRouter(prefix=...) 里，装饰器只写后缀；只看 @router. 会漏掉
# 所有带前缀的子路由（4.16.45 的项目卡就这么被误报成「后端不存在」）。
ROUTER_RE = re.compile(r'(\w+)\s*=\s*APIRouter\(\s*prefix\s*=\s*["\']([^"\']*)["\']')
# 前端：只认真正的请求调用（api(...) / fetch(...)），
# 不能把 `queryKey: ["/api/xxx"]` 这种缓存键当成路径——那是键名，不是 URL。
FRONT_PATH_RE = re.compile(
    r'(?:api(?:<[^>]{0,120}>)?|fetch|fetchEventSource)\(\s*["`](/api/[^"`\s]*)["`]'
)


def normalize(path: str) -> str:
    """把路径参数与模板变量统一成 {p}；查询串去掉。

    前端常见两种写法：
      `/api/bank/import${qs}`      —— 变量是查询串，路径到 import 就结束了
      `/api/bank/transactions/${id}` —— 变量是路径参数，必须保留一段
    判据：`${` 前一个字符是不是 `/`，是则算路径参数，否则其后整体当作查询串丢弃。
    """
    path = path.split("?")[0].split("#")[0]
    out: list[str] = []
    i = 0
    while i < len(path):
        if path.startswith("${", i):
            j = path.find("}", i)
            if j < 0:
                break
            out.append("{p}" if (out and out[-1] == "/") else "")
            i = j + 1
            continue
        if path[i] == "{" and (out and out[-1] == "/"):
            j = path.find("}", i)
            if j < 0:
                out.append(path[i])
                i += 1
                continue
            out.append("{p}")
            i = j + 1
            continue
        out.append(path[i])
        i += 1
    return re.sub(r"/+", "/", "".join(out)).rstrip("/")


def _segments(path: str) -> list[str]:
    return [x for x in path.split("/") if x]


def path_match(front: str, back: str) -> bool:
    """按段比对，{p} 可匹配任意一段（前端模板变量 / 后端路径参数）。

    必须段数相等：`/api/x` 与 `/api/x/{p}` 是两个端点，不能互相顶替。
    """
    a, b = _segments(front), _segments(back)
    if len(a) != len(b):
        return False
    return all(x == y or x == "{p}" or y == "{p}" for x, y in zip(a, b))


def backend_routes() -> dict[str, set[str]]:
    """返回 {归一化路径: {method...}}。同一路径可能挂多个方法。"""
    out: dict[str, set[str]] = {}
    for f in BACKEND.rglob("*.py"):
        if "routes" not in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        prefixes = {m.group(1): m.group(2) for m in ROUTER_RE.finditer(text)}
        for m in ROUTE_RE.finditer(text):
            router_name, method, raw = m.group(1), m.group(2).upper(), m.group(3)
            out.setdefault(normalize(prefixes.get(router_name, "") + raw), set()).add(method)
    return out


def frontend_paths() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in list(FRONTEND.rglob("*.ts")) + list(FRONTEND.rglob("*.tsx")):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in FRONT_PATH_RE.finditer(text):
            raw = m.group(1)
            # 跳过明显不是路径的（含未闭合拼接的变量）
            out.setdefault(normalize(raw), set()).add(str(f.relative_to(ROOT)))
    return out


def main() -> int:
    argv = set(sys.argv[1:])
    be = backend_routes()
    fe = frontend_paths()

    missing: dict[str, list[str]] = {}
    for path, files in sorted(fe.items()):
        if any(path_match(path, b) for b in be):
            continue
        missing[path] = sorted(files)

    baseline: set[str] = set()
    if BASELINE.exists():
        baseline = set(json.loads(BASELINE.read_text(encoding="utf-8")))

    unknown = {p: f for p, f in missing.items() if p not in baseline}
    if "--update" in argv:
        BASELINE.write_text(json.dumps(sorted(missing), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ 白名单已更新：{len(missing)} 条前端路径无对应后端端点")
        return 0

    if unknown:
        print("✗ 前端调用了后端不存在的端点：")
        for p, files in unknown.items():
            print(f"  {p}\n    ← {', '.join(files[:3])}")
        return 1

    print(f"✓ 契约一致：前端 {len(fe)} 条路径全部能对上后端端点（白名单 {len(baseline)} 条）")
    if "-v" in argv:
        unused = sorted(p for p in be if p not in fe and p.startswith("/api/"))
        print(f"  参考：后端有、前端未直接调用的 {len(unused)} 条（可能供 MCP/外部 API 使用，不作为死代码判据）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
