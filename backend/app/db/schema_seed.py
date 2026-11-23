"""示例账本种子数据：一套典型中产家庭的持仓/流水/订阅/负债/设置。

生产首启不种示例；只有设置页「导入示例数据」与测试夹具会用到这些常量。
"""

from __future__ import annotations

SEED_POSITIONS = [
    {
        "symbol": "600519",
        "name": "贵州茅台",
        "kind": "股票",
        "industry": "白酒",
        "shares": 100,
        "cost": 1680.00,
        "last": 1521.00,
    },
    {
        "symbol": "510300",
        "name": "沪深300ETF",
        "kind": "ETF",
        "industry": "宽基指数",
        "shares": 8000,
        "cost": 3.85,
        "last": 4.06,
    },
    {
        "symbol": "110011",
        "name": "易方达中小盘混合",
        "kind": "基金",
        "industry": "主动权益",
        "shares": 12000,
        "cost": 4.10,
        "last": 3.58,
    },
    {
        "symbol": "CASH",
        "name": "活期现金",
        "kind": "现金",
        "industry": "现金",
        "shares": 1,
        "cost": 55000.00,
        "last": 55000.00,
    },
]

# day_in_month: 尽量落在本月已过去的日期（今日之前），保证"本月"口径成立
SEED_TRANSACTIONS = [
    (2, "工资入账", "收入", 24800.0),
    (3, "房租", "居住", -5200.0),
    (5, "外卖餐饮", "餐饮", -1860.0),
    (7, "视频会员（年付）", "订阅", -258.0),
    (9, "通勤地铁", "交通", -320.0),
    (11, "健身私教", "订阅", -1999.0),
    (13, "添置家电", "购物", -4300.0),
    (15, "基金定投", "投资", -3000.0),
    (17, "云盘会员", "订阅", -168.0),
    (19, "聚餐", "餐饮", -960.0),
    (20, "信用卡还款", "还款", -3200.0),
]

SEED_SUBSCRIPTIONS = [
    {"name": "云盘会员", "monthly": 14.0, "note": "可合并到家庭共享", "due_day": "1"},
    {
        "name": "健身私教",
        "monthly": 1999.0,
        "note": "占订阅支出绝大部分",
        "due_day": "5",
    },
    {"name": "流媒体", "monthly": 21.5, "note": "与年付会员功能重叠", "due_day": "28"},
]

SEED_DEBTS = [
    {
        "name": "房贷",
        "monthly": 6800.0,
        "balance": 1280000.0,
        "rate": 0.0345,
        "due_day": "15",
    },
    {
        "name": "信用卡分期",
        "monthly": 900.0,
        "balance": 7200.0,
        "rate": 0.13,
        "due_day": "10",
    },
]

SEED_SETTINGS = {
    "monthly_income": "24800",
    "emergency_target_months": "6",
    # 应急金覆盖所需的"必要月支出"口径：居住 + 餐饮 + 交通 三类
    "essential_categories": "居住,餐饮,交通",
    # 行情源：auto（东财优先，失败降级快照）| snapshot | eastmoney
    "quote_source_mode": "auto",
    # 定时晨报时间（HH:MM）
    "report_time": "08:00",
    # ---- 功能开关（设置中心可自定义）----
    "voice_input": "off",  # 问答语音输入（浏览器支持时）
    "voice_output": "off",  # 回答语音播报（浏览器 SpeechSynthesis）
    # 适老化：正文缩放（normal/large/xlarge）与高对比度（on/off）
    "text_scale": "normal",
    "high_contrast": "off",
    "show_export": "on",  # 回答导出/复制按钮
    "expand_process": "off",  # 分析过程默认展开
    "show_suggestions": "off",  # 问答页建议入口（R4 起输入区常驻快捷指令 chips，空态建议默认关）
    "auto_refresh": "off",  # 仪表盘定时自动刷新
    "auto_refresh_seconds": "300",  # 自动刷新间隔（秒）
    "compact_numbers": "on",  # 大金额缩写（万/亿）
    "color_scheme": "cn",  # 涨跌颜色：cn 红涨绿跌（A股惯例）| us 绿涨红跌（海外惯例）
    "default_tab": "chat",  # 默认首页：overview|holdings|market|ledger|chat（对话中枢为主，可在设置改回）
    "savings_goal": "20",  # 储蓄率目标（%）
    # ---- AI 回答（OpenAI 兼容端点，可配任意国产/海外模型；失败自动降级模板）----
    "ai_enabled": "on",  # 是否启用 AI 回答（AI 优先；三要素未配或调用失败时回退内置分析）
    "ai_base_url": "",  # 国产示例：DeepSeek https://api.deepseek.com/v1 · 豆包 https://ark.cn-beijing.volces.com/api/v3 · 通义 https://dashscope.aliyuncs.com/compatible-mode/v1
    "ai_api_key": "",  # 仅存本机数据库
    "ai_model": "",  # 对应端点模型：deepseek-chat / doubao 接入点 ID / qwen-plus
    # 任务模型路由：留空=全部用主模型；设置后只在本端点内换模型名，
    # 简单问答走轻量模型，深研/长文走深度模型，避免一刀切。
    "model_route_economy": "",
    "model_route_deep": "",
    # ---- 模型点亮：设置页可勾选启用哪些模型，逗号分隔的模型名（默认点亮前两个）----
    "enabled_models": "deepseek-chat,qwen-plus",
    # ---- Agent 行为（可配置化：工具轮次 / 规划展示 / 失败反思重试）----
    "agent_tool_turns": "5",  # 单轮问答里模型可调用工具的轮次上限（1-30，防死循环）
    "agent_context_tokens": "12000",  # 工具循环的上下文 token 软预算；超出后压缩旧轮次与超长工具结果
    "agent_plan": "on",  # 是否展示执行计划（supervisor 计划卡 / 推理轨迹）
    "agent_reflect": "on",  # 工具失败时是否提示模型反思修正后重试
    "custom_system_prompt": "",  # 自定义系统提示词（留空用 agents/supervisor/instructions.md）
    "knowledge_enabled": "on",  # 知识库检索开关
    # ---- 远程控制（手机扫码接入）----
    "remote_enabled": "on",  # 是否允许生成远程链接（不生成就没有任何远程入口）
    "remote_public_url": "",  # 对外地址，如 https://money.example.com；留空用当前访问地址
    "remote_session_hours": "12",  # 单次远程会话有效期（1-168 小时）
    "data_note": "seed",
}

# 版本化默认设置：新增键时对已有库补齐默认值
DEFAULT_SETTINGS = {k: v for k, v in SEED_SETTINGS.items()}
