"""能力评测路由（M6.3）：题库 / 判分 / 排行榜。

定位：把"这个模型能不能管钱"从主观印象变成可复现的分数。
- 题库与判据都是确定性的，任何人可以用同一套题复跑。
- 未配置模型时明确返回未评分，不生成假成绩。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import model_eval
from ..eval_bank import get_questions, question_count

router = APIRouter()

# 进程内排行榜（本轮评测结果）。不做持久化：排行榜是"这次跑出来的"，
# 重启后重新评测即可，避免把一次性结果当成长期事实写进库。
_results: list[dict[str, Any]] = []


@router.get("/api/eval/questions")
async def eval_questions(category: str = Query(default="")) -> dict[str, Any]:
    """题库（含判据），供前端展示与他人复现。"""
    items = get_questions(category)
    return {
        "count": len(items),
        "total": question_count(),
        "categories": sorted({q["category"] for q in get_questions()}),
        "questions": items,
    }


@router.post("/api/eval/run")
async def eval_run(payload: dict | None = None) -> dict[str, Any]:
    """用当前配置模型跑一遍题库。payload: {model?, category?, max_questions?}"""
    payload = payload or {}
    model = str(payload.get("model") or "")
    category = str(payload.get("category") or "")
    try:
        max_q = int(payload.get("max_questions") or 0)
    except (TypeError, ValueError):
        max_q = 0
    result = await model_eval.evaluate_model(model, category, max_questions=max_q)
    if result.get("scored"):
        _results.append(
            {
                "model": result.get("model"),
                "score_pct": result.get("score_pct"),
                "passed": result.get("passed"),
                "question_count": result.get("question_count"),
                "graded_at": result.get("graded_at"),
            }
        )
        # 只保留最近 50 次，避免进程内无限增长
        del _results[:-50]
    return result


@router.post("/api/eval/score")
async def eval_score(payload: dict) -> dict[str, Any]:
    """对已有回答判分（离线评测 / 对比不同模型输出用）。payload: {answers, category?}"""
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise HTTPException(400, "answers 必须是 {题目ID: 回答} 的对象")
    category = str(payload.get("category") or "")
    return model_eval.score_answers({str(k): str(v) for k, v in answers.items()}, category)


@router.get("/api/eval/leaderboard")
async def eval_leaderboard() -> dict[str, Any]:
    """排行榜：本次进程内跑过的模型成绩，按分数降序。没有数据时返回空，不塞假条目。"""
    rows = model_eval.leaderboard(_results)
    return {"count": len(rows), "leaderboard": rows}
