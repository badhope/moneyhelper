"""`python -m moneyhelper.cli` 入口。

为什么需要：项目 pyproject 里声明了 `moneyhelper = "moneyhelper.cli:main"`，
pip 安装后可直接用；但开发态（未 pip install -e）只能靠 `python -m`，
而包缺 `__main__.py` 时 `-m moneyhelper.cli` 会报
"No module named moneyhelper.cli.__main__"。补这个文件让两种用法都成立。
"""

from . import main

if __name__ == "__main__":
    raise SystemExit(main())
