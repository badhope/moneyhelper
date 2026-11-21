"""MCP 包装层返回值注解审计：注解与实际返回类型必须一致。

FastMCP 会按函数注解校验返回值。包装函数写 `-> str`、底层却返回 dict 时，
客户端调用直接得到 "Output validation error"（backup_now 就这么坏过，且只有
真调一次才看得见）。这里用 AST 静态比对：包装层直接 `return await
xtools.tool_x(...)` 的，注解必须和 tool_x 的注解一致。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def _ann(node: ast.AST | None) -> str:
    if node is None:
        return ""
    return ast.unparse(node).replace(" ", "")


def _tool_annotations() -> dict[str, str]:
    """扫 tools*.py，收集 tool_x 的返回注解。"""
    out: dict[str, str] = {}
    for path in APP.glob("tools*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("tool_"):
                out[node.name] = _ann(node.returns)
    return out


def _wrapper_returns() -> list[tuple[str, str, str]]:
    """扫 mcp_*.py：收集 (包装函数名, 包装注解, 被调 tool_x)。"""
    got: list[tuple[str, str, str]] = []
    for path in APP.glob("mcp_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Return) or stmt.value is None:
                    continue
                value = stmt.value
                if not isinstance(value, ast.Await) or not isinstance(value.value, ast.Call):
                    continue
                call = value.value
                if not isinstance(call.func, ast.Attribute):
                    continue
                if not isinstance(call.func.value, ast.Name) or call.func.value.id != "xtools":
                    continue
                target = call.func.attr
                if target.startswith("tool_"):
                    got.append((node.name, _ann(node.returns), target))
    return got


def test_mcp_wrapper_return_annotations_match_impls() -> None:
    impls = _tool_annotations()
    mismatches = []
    for wrapper, wrapper_ann, target in _wrapper_returns():
        impl_ann = impls.get(target)
        if impl_ann is None:
            continue
        # 只比较"是不是容器/标量"这一层，具体泛型参数允许不同
        wl = wrapper_ann.split("[")[0]
        il = impl_ann.split("[")[0]
        if wl != il:
            mismatches.append(f"{wrapper} -> {wrapper_ann}，但 {target} 返回 {impl_ann}")
    assert not mismatches, "MCP 包装注解不一致：\n" + "\n".join(mismatches)
