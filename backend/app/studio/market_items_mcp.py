"""Studio 目录条目：MCP 服务器：抓取、文件、记忆、时序、时间、Git 与科研检索。

条目是纯数据（dict 字面量），按站内顺序切段拆出，拼接顺序与原文件一致。
"""

from __future__ import annotations

from typing import Any

from .market_sources import (
    _MCP_AWESOME,
    _MCP_OFFICIAL,
)

ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "mcp-fetch",
        "aliases": ["抓取", "网页", "fetch", "爬虫"],
        "name": "Fetch MCP（网页抓取）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_OFFICIAL,
        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/fetch",
        "stars": 91597,
        "description": "官方参考实现：抓取网页并转 Markdown，适合让 Agent 读取公开资料。",
        "server": {"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]},
    },

    {
        "id": "mcp-filesystem",
        "aliases": ["文件", "文件系统", "filesystem", "目录"],
        "name": "Filesystem MCP（只读文件）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_OFFICIAL,
        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        "stars": 91597,
        "description": "官方参考实现：受限目录内的文件读写；本应用默认只开放只读工具。",
        "server": {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"],
        },
    },

    {
        "id": "mcp-memory",
        "aliases": ["记忆", "memory", "知识图谱"],
        "name": "Memory MCP（知识图谱记忆）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_OFFICIAL,
        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/memory",
        "stars": 91597,
        "description": "官方参考实现：以实体-关系图保存跨会话事实。",
        "server": {"name": "memory", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]},
    },

    {
        "id": "mcp-sequentialthinking",
        "aliases": ["推理", "思考", "sequential", "分步"],
        "name": "Sequential Thinking MCP",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_OFFICIAL,
        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
        "stars": 91597,
        "description": "官方参考实现：把复杂问题拆成可回溯的推理步骤。",
        "server": {
            "name": "sequentialthinking",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        },
    },

    {
        "id": "mcp-time",
        "aliases": ["时间", "时区", "time", "时钟"],
        "name": "Time MCP（时区时间）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_OFFICIAL,
        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/time",
        "stars": 91597,
        "description": "官方参考实现：时区换算与当前时间。",
        "server": {"name": "time", "command": "uvx", "args": ["mcp-server-time"]},
    },

    {
        "id": "mcp-git",
        "aliases": ["git", "版本库", "提交"],
        "name": "Git MCP（版本库操作）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_OFFICIAL,
        "url": "https://github.com/modelcontextprotocol/servers/tree/main/src/git",
        "stars": 91597,
        "description": "官方参考实现：查看 diff、提交历史与分支。",
        "server": {"name": "git", "command": "uvx", "args": ["mcp-server-git", "--repository", "."]},
    },

    {
        "id": "mcp-deepwiki",
        "aliases": ["deepwiki", "仓库文档", "代码文档"],
        "name": "DeepWiki MCP（仓库文档）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_AWESOME,
        "url": "https://mcp.deepwiki.com/mcp",
        "stars": 96920,
        "description": "远程 MCP：查询任意 GitHub 仓库的文档与结构（官方托管）。",
        "server": {"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp"},
    },

    {
        "id": "mcp-gitmcp",
        "aliases": ["gitmcp", "仓库检索"],
        "name": "GitMCP（仓库检索）",
        "kind": "mcp",
        "category": "MCP",
        "source": _MCP_AWESOME,
        "url": "https://gitmcp.io/docs",
        "stars": 96920,
        "description": "远程 MCP：把任意 GitHub 仓库变成可检索的知识源。",
        "server": {"name": "gitmcp", "url": "https://gitmcp.io/docs"},
    },

    {
        "id": "mcp-arxiv",
        "name": "arXiv MCP（论文全文检索）",
        "kind": "mcp",
        "category": "科研 MCP",
        "source": "https://github.com/blazickjp/arxiv-mcp-server",
        "url": "https://github.com/blazickjp/arxiv-mcp-server",
        "stars": 3236,
        "description": "检索 arXiv、读取 LaTeX 章节与 BibTeX，适合文献综述与论文追踪。",
        "aliases": ["arxiv", "论文检索", "预印本"],
        "server": {"name": "arxiv", "command": "uvx", "args": ["arxiv-mcp-server"]},
    },

    {
        "id": "mcp-zotero",
        "name": "Zotero MCP（文献库）",
        "kind": "mcp",
        "category": "科研 MCP",
        "source": "https://github.com/54yyyu/zotero-mcp",
        "url": "https://github.com/54yyyu/zotero-mcp",
        "stars": 5605,
        "description": "连接本地 Zotero 文献库：检索条目、读笔记与附件、导出引用。",
        "aliases": ["zotero", "文献库", "参考文献"],
        "server": {"name": "zotero", "command": "uvx", "args": ["zotero-mcp-server"], "env": {"ZOTERO_LOCAL": "true"}},
    },

    {
        "id": "mcp-paper-search",
        "name": "Paper Search MCP（多源检索）",
        "kind": "mcp",
        "category": "科研 MCP",
        "source": "https://github.com/openags/paper-search-mcp",
        "url": "https://github.com/openags/paper-search-mcp",
        "stars": 2936,
        "description": "跨 arXiv/PubMed/Semantic Scholar 等来源检索与下载论文。",
        "aliases": ["paper search", "论文搜索", "文献检索"],
        "server": {"name": "paper-search", "command": "uvx", "args": ["paper-search-mcp"]},
    },
)
