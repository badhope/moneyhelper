"""Moneyhelper · 个人理财多智能体后端。"""

import os
import warnings as _warnings

from dotenv import load_dotenv

# —— 必须在任何子模块 import litellm 之前生效的环境变量 ——
# LITELLM_LOG：litellm 自带 handler 默认 DEBUG，每次模型调用会打大量
#   "Error getting model info / cost" 行（带 traceback，看着像报错）。
# LITELLM_LOCAL_MODEL_COST_MAP：跳过启动时联网抓成本表（失败会打 SSL 警告）。
load_dotenv()
os.environ.setdefault("LITELLM_LOG", "ERROR")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# —— 第三方库「待上游迁移」的弃用提示（均非本项目代码；依赖升级/迁移后应移除豁免）——
# 说明：这些提示在控制台出现会被误读为报错，且修正权在上游包
# （迁移目标分别需要 langchain v1 主包 / 新版 mem0 发布）。
_warnings.filterwarnings("ignore", message=r"The default value of `allowed_objects` will change")
_warnings.filterwarnings("ignore", message=r".*has been moved to `langchain\.agents`")
_warnings.filterwarnings("ignore", message=r"Support for class-based `config` is deprecated")

from .version import __version__ as __version__  # noqa: E402  单一真源（app/version.py）
