"""确定性内核层：不依赖 HTTP、不依赖 UI，可被 CLI / MCP / 部门模式直接复用。

这一层的判据很简单：**换成 CLI 或 MCP 调用，这段逻辑还成立吗？**
成立就属于 core。凡是需要 Request / FastAPI 依赖 / HTTP 状态码的，属于 server。

当前实现映射（实现仍集中在 app/ 下，此处只做门面 re-export）：

    db            ← app.db              组合库与运行历史（连接池 / schema / 各域存储）
    analysis      ← app.analysis        收支 / 现金流 / 风险的确定性计算
    quotes        ← app.quotes          行情（东财 / 新浪 / 快照三级降级）
    nlparse       ← app.nlparse         中文一句话解析（金额 / 日期 / 分类）
    evaluate      ← app.evaluate        体检与评分
    backup        ← app.backup          加密导出 / 恢复
    vault         ← app.vault           敏感字段加密
    csvimport     ← app.csvimport       CSV 分类与解析
    provenance    ← app.provenance      审计链（数字可复核的基础）
    service       ← app.service         问答编排（路由 → 取数 → 叙述）

注意：service 目前包含 SSE 事件拼装，属于「带壳痕迹」的内核。等 M2 做
AG-UI 映射层时把事件产出与传输解耦，届时 service 才会是纯内核。
"""

from __future__ import annotations

# 门面只暴露模块对象，不展开符号：调用方写 core.db.add_transaction(...)，
# 这样内部函数增删不需要同步维护一份巨大的 __all__。
from app import (  # noqa: F401
    analysis,
    backup,
    csvimport,
    db,  # noqa: F401
    evaluate,
    nlparse,
    provenance,
    quotes,  # noqa: F401
    service,  # noqa: F401
    vault,  # noqa: F401
)

__all__ = [
    "analysis",
    "backup",
    "csvimport",
    "db",
    "evaluate",
    "nlparse",
    "provenance",
    "quotes",
    "service",
    "vault",
]
