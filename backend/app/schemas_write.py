"""写入与通用：记账/持仓/记忆/设置/晨报/备份/当前时间/联网搜索。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .tool_schemas import _In


class RecordTransactionIn(_In):
    text: str = Field(..., description="用户原话")

class SaveUserMemoryIn(_In):
    content: str = Field(..., description="要记住的内容（一句话，含具体事实）")

class RecordPositionIn(_In):
    symbol: str = Field(..., description="6 位代码")
    name: str = Field("", description="名称（可省略，自动获取）")
    kind: str = Field("", description="股票/基金/ETF")
    shares: float = Field(..., description="份额/股数")
    cost: float = Field(..., description="成本价（买入价）")
    last: float = Field(0, description="现价（可省略，自动获取）")
    buy_date: str = Field("", description="买入日期 YYYY-MM-DD，可省略默认今天")
    industry: str = Field("", description="行业分类（可省略，默认其他）")

class SellPositionIn(_In):
    symbol: str = Field(..., description="6 位代码")
    shares: float = Field(0, description="卖出份额/股数（省略=清仓全部）")

class SetSettingIn(_In):
    key: str = Field(..., description="设置键名，见工具描述")
    value: str = Field(..., description="设置值，见工具描述")

class GetUserMemoryIn(_In):
    query: str = Field("", description="检索关键词（可选）：返回与该话题相关的记忆")
    kind: str = Field(
        "", description="按类型过滤（可选）：fact / preference / goal_related"
    )

class TriggerMorningReportIn(_In):
    """立即生成今日晨报。"""

    lang: str = Field("", description="输出语言 zh/en，可省略（默认 zh）")

class BackupNowIn(_In):
    """生成本地加密备份包。"""

    lang: str = Field("", description="输出语言 zh/en，可省略（默认 zh）")

class GetNowIn(_In):
    """查当前日期与时间。"""

class WebSearchIn(_In):
    q: str = Field(..., description="搜索关键词")


MODELS: dict[str, type[BaseModel]] = {
    "record_transaction": RecordTransactionIn,
    "save_user_memory": SaveUserMemoryIn,
    "record_position": RecordPositionIn,
    "sell_position": SellPositionIn,
    "set_setting": SetSettingIn,
    "get_user_memory": GetUserMemoryIn,
    "trigger_morning_report": TriggerMorningReportIn,
    "backup_now": BackupNowIn,
    "get_now": GetNowIn,
    "web_search": WebSearchIn,
}
