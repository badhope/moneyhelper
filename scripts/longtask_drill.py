"""用真实模型跑五个长任务，产出可核查的产物与报告。

用法：
    LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=... \
      .venv/Scripts/python.exe scripts/longtask_drill.py [base_url]

前置：后端已启动（默认 127.0.0.1:18812）且已配置模型。
输出：out/longtask/<kind>/ 下的阶段产物 + out/longtask/report.md
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18812").rstrip("/")
OUT = Path(__file__).resolve().parent.parent / "out" / "longtask"

TASKS = [
    {
        "kind": "novel",
        "title": "长夜灯塔",
        "brief": "写一部科幻悬疑小说：近未来海平面上升，一座孤岛灯塔看守人发现灯塔其实在向深海发送信号。要求有完整人物弧光与三次反转。",
    },
    {
        "kind": "webapp",
        "title": "个人记账 Web 应用",
        "brief": "做一个单页记账应用：新增收支、按分类汇总、月度趋势图、本地存储、移动端可用。技术栈不限，要求可直接运行。",
    },
    {
        "kind": "docx",
        "title": "季度经营分析报告",
        "brief": "为一家 50 人的 SaaS 公司写季度经营分析报告，覆盖收入、成本、客户留存、现金流与下季度计划。缺少真实数据的地方必须标注为待填。",
    },
    {
        "kind": "paper",
        "title": "生成式 AI 对知识工作的影响",
        "brief": "写一篇 3000 字以上的综述型论文，讨论生成式 AI 对知识工作者生产率与技能结构的影响。要求有明确研究问题、文献综述结构、方法说明与局限讨论；不得编造具体文献或数据。",
    },
    {
        "kind": "program",
        "title": "CSV 清洗命令行工具",
        "brief": "用 Python 写一个 CLI：读取 CSV，处理缺失值、去重、类型推断，输出清洗报告与清洗后的文件。要求有参数校验、错误处理与测试。",
    },
]


def _post(path: str, payload: dict, timeout: int = 3600) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str, timeout: int = 120) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if not os.getenv("LLM_API_KEY"):
        print("SKIP: 未设置 LLM_API_KEY")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["# 长任务实测报告", "", f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", f"- 后端：{BASE}", ""]
    failures = 0

    for spec in TASKS:
        print(f"\n=== {spec['kind']} : {spec['title']} ===", flush=True)
        created = _post("/api/longtasks", spec)
        if not created.get("ok"):
            print("创建失败:", created)
            failures += 1
            continue
        task_id = created["task"]["id"]
        started = time.time()
        result = _post(f"/api/longtasks/{task_id}/run", {})
        elapsed = round(time.time() - started, 1)
        if not result.get("ok"):
            print("执行失败:", result)
            failures += 1
            continue
        task = result["task"]
        folder = OUT / spec["kind"]
        folder.mkdir(parents=True, exist_ok=True)
        total_chars = 0
        stage_lines = []
        for stage in task["stages"]:
            art = _get(f"/api/longtasks/{task_id}/stages/{stage['index']}")
            content = art.get("content") or ""
            if content:
                (folder / f"{stage['index']:02d}-{stage['name']}.md").write_text(
                    content, encoding="utf-8"
                )
                total_chars += len(content)
            stage_lines.append(
                f"| {stage['index']} | {stage['name']} | {stage['status']} | {stage['chars']} | {stage['error'][:60]} |"
            )
        (folder / "task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        status_ok = task["status"] == "done"
        if not status_ok:
            failures += 1
        print(f"status={task['status']} chars={total_chars} elapsed={elapsed}s", flush=True)
        lines += [
            f"## {spec['kind']} · {spec['title']}",
            "",
            f"- 任务 ID：`{task_id}`",
            f"- 状态：**{task['status']}**",
            f"- 总字数：{total_chars}",
            f"- 耗时：{elapsed}s",
            f"- 产物目录：`out/longtask/{spec['kind']}/`",
            "",
            "| # | 阶段 | 状态 | 字数 | 错误 |",
            "|---|---|---|---|---|",
            *stage_lines,
            "",
        ]

    lines.append(f"**失败任务数：{failures}**")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告：{OUT / 'report.md'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
