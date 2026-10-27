"""发版脚本的版本推导测试（M4.3）。

发版自动化最容易出错的地方是"版本号推错了"，而那正是最不该手工检查的部分。
这里验证三件事：
1. 提交类型到升位规则的映射（major/minor/patch）
2. 版本号单一真源真的只有一处，其余文件由它派生
3. 发版脚本的 dry-run 不改任何文件
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERSION_PY = REPO / "backend" / "app" / "version.py"


def _bump(commits: list[str]) -> str:
    """复刻 release.sh 的推导逻辑（bash 里不好单测，用 Python 表达同一规则）。"""
    joined = "\n".join(commits)
    if re.search(r"^[a-z]+(\([^)]*\))?!:|BREAKING CHANGE", joined, re.M):
        return "major"
    if re.search(r"^feat(\([^)]*\))?:", joined, re.M):
        return "minor"
    return "patch"


def _apply(cur: str, bump: str) -> str:
    major, minor, patch = (int(x) for x in cur.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ---------------------------------------------------------------------------
# 版本推导规则
# ---------------------------------------------------------------------------


def test_feat_bumps_minor() -> None:
    assert _apply("2.1.0", _bump(["feat(M3.1): 工单模型"])) == "2.2.0"


def test_fix_bumps_patch() -> None:
    assert _apply("2.1.3", _bump(["fix(db): 事务串行化"])) == "2.1.4"


def test_breaking_bumps_major() -> None:
    assert _apply("2.1.0", _bump(["feat(core)!: 移除旧接口"])) == "3.0.0"
    assert _apply("2.1.0", _bump(["chore: 重构\n\nBREAKING CHANGE: 不再支持 py39"])) == "3.0.0"


def test_breaking_wins_over_feat() -> None:
    """同时有 feat 与 BREAKING CHANGE 时取 major（破坏性优先）。"""
    commits = ["feat: 新功能", "refactor(core)!: 删掉旧 API"]
    assert _bump(commits) == "major"


def test_docs_chore_are_patch() -> None:
    assert _bump(["docs: 补文档", "chore: 清缓存", "ci: 加 job"]) == "patch"


def test_major_resets_minor_and_patch() -> None:
    assert _apply("2.7.9", "major") == "3.0.0"


def test_minor_resets_patch() -> None:
    assert _apply("2.7.9", "minor") == "2.8.0"


# ---------------------------------------------------------------------------
# 版本号单一真源
# ---------------------------------------------------------------------------


def test_version_py_is_single_source() -> None:
    """version.py 必须有可被脚本解析的 `__version__ = "x.y.z"`，且是 SemVer。"""
    text = VERSION_PY.read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    assert m, "version.py 缺少 __version__ 定义"
    assert re.fullmatch(r"\d+\.\d+\.\d+", m.group(1)), f"版本号不是 SemVer: {m.group(1)}"


def test_pyproject_version_matches_source() -> None:
    """pyproject 的版本必须与真源一致（发版脚本负责同步，漂移说明脚本漏了）。"""
    src = re.search(
        r'^__version__ = "([^"]+)"', VERSION_PY.read_text(encoding="utf-8"), re.M
    ).group(1)
    py = re.search(
        r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M
    ).group(1)
    assert py == src, f"pyproject={py} 与 version.py={src} 不一致"


def test_package_json_version_matches_source() -> None:
    src = re.search(
        r'^__version__ = "([^"]+)"', VERSION_PY.read_text(encoding="utf-8"), re.M
    ).group(1)
    pkg = (REPO / "frontend" / "package.json").read_text(encoding="utf-8")
    # 只取顶层 version（避免误匹配依赖的 "^1.4.0"）
    m = re.search(r'^\s{2}"version": "([^"]+)"', pkg, re.M)
    assert m, "package.json 缺少顶层 version"
    assert m.group(1) == src, f"package.json={m.group(1)} 与 version.py={src} 不一致"


def test_app_version_reads_from_source() -> None:
    """后端运行时版本必须来自真源，不能有第二个写死的字符串。"""
    from app.version import __version__ as runtime

    src = re.search(
        r'^__version__ = "([^"]+)"', VERSION_PY.read_text(encoding="utf-8"), re.M
    ).group(1)
    assert runtime == src


def test_no_hardcoded_version_in_main() -> None:
    """main.py 不能写死版本号（必须引用 __version__）。"""
    text = (REPO / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'version="1.0.0"' not in text
    assert "version=__version__" in text


# ---------------------------------------------------------------------------
# 发版脚本
# ---------------------------------------------------------------------------


def test_release_script_is_executable() -> None:
    script = REPO / "scripts" / "release.sh"
    assert script.is_file()
    if os.name == "nt":
        # Windows 没有 POSIX 权限位：git 记录的 100755 由 core.filemode 反映，
        # 用 git ls-files -s 校验（不依赖文件系统的 mode 位）。
        out = subprocess.run(
            ["git", "ls-files", "-s", "scripts/release.sh"],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.startswith("100755"), f"git 记录的权限不是可执行：{out.stdout!r}"
    else:
        assert script.stat().st_mode & 0o111, "release.sh 必须可执行"


def test_release_script_has_no_push() -> None:
    """脚本不应自动 push：推送是人工决定，避免误推未审阅内容。"""
    text = (REPO / "scripts" / "release.sh").read_text(encoding="utf-8")
    # 允许在注释/echo 里提到 git push，但不允许真正执行（行首非注释且非 echo）
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("echo") or s.startswith('"'):
            continue
        assert not re.match(r"git push", s), f"release.sh 不应自动 push：{s}"


def test_release_yml_valid_and_guards_version() -> None:
    """release workflow 必须校验 tag 与 version.py 一致。"""
    text = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "version.py" in text
    assert "不一致" in text or "mismatch" in text
    assert "softprops/action-gh-release" in text


def _bash() -> str:
    """返回可用的 bash 解释器。

    Windows 的 PATH 里可能有 C:\\Windows\\System32\\bash.exe（WSL 转发器），
    它不指向真实 bash，运行会失败。这里逐个探测候选并验证能执行命令。
    """
    candidates = [
        os.environ.get("MONEYHELPER_BASH", ""),
        r"C:\Program Files\Git\usr\bin\bash.exe" if os.name == "nt" else "",
        r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else "",
        "/usr/bin/bash",
        "bash",
    ]
    for cand in candidates:
        if not cand:
            continue
        if os.path.isabs(cand) and not os.path.exists(cand):
            continue
        try:
            probe = subprocess.run(
                [cand, "-c", "echo ok"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and "ok" in (probe.stdout or ""):
            return cand
    __import__("pytest").skip("当前环境没有可用的 bash（Windows 需安装 Git for Windows）")


def test_release_dry_run_does_not_modify_files() -> None:
    """--dry-run 必须零副作用（用户靠它预演）。

    在临时 git 仓库里跑脚本，避免污染真实工作区：脚本要求工作区干净，
    且会改 version/CHANGELOG。
    """
    import shutil
    import tempfile

    bash = _bash()
    script = REPO / "scripts" / "release.sh"
    tmp = Path(tempfile.mkdtemp(prefix="rel-"))
    try:
        # 最小仓库骨架：脚本只需要 version.py / git 历史 / 几个待改文件
        (tmp / "backend" / "app").mkdir(parents=True)
        (tmp / "backend" / "app" / "version.py").write_text('__version__ = "1.2.3"\n')
        (tmp / "frontend").mkdir()
        (tmp / "frontend" / "package.json").write_text('{\n  "version": "1.2.3"\n}\n')
        (tmp / "pyproject.toml").write_text('version = "1.2.3"\n')
        (tmp / "CHANGELOG.md").write_text("# Changelog\n\n## [1.2.3] - 2026-01-01\n")
        (tmp / "scripts").mkdir()
        shutil.copy2(script, tmp / "scripts" / "release.sh")

        env = {
            # 继承真实 PATH：Windows 的 git 不在 /usr/bin，写死会让脚本找不到 git。
            "PATH": os.environ.get("PATH", ""),
            # 保留真实 HOME：Windows 上 git 依赖用户目录下的辅助进程/配置，
            # 指向临时空目录会触发 "RPC failed"（实测）。
            "HOME": os.environ.get("HOME") or os.environ.get("USERPROFILE", str(tmp)),
            "USERPROFILE": os.environ.get("USERPROFILE", str(tmp)),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            # 隔离全局/系统 git 配置，避免本机 core.autocrlf、默认身份影响断言
            "GIT_CONFIG_GLOBAL": str(tmp / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }

        def run(*a: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                a, cwd=tmp, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=env,
            )
        run("git", "init", "-q", "-b", "main")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "feat: initial")

        before = {
            p: (tmp / p).read_text()
            for p in ("backend/app/version.py", "pyproject.toml", "frontend/package.json", "CHANGELOG.md")
        }
        out = subprocess.run(
            [bash, "scripts/release.sh", "--dry-run"],
            cwd=tmp, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        assert out.returncode == 0, (out.stdout or "")[-800:] + (out.stderr or "")[-800:]
        # 预演应提示下一版本为 1.3.0（feat → minor）
        assert "1.3.0" in out.stdout
        # 所有文件内容未变
        for p, content in before.items():
            assert (tmp / p).read_text() == content, f"{p} 被 dry-run 修改了"
        # 没有新 tag
        tags = run("git", "tag").stdout.strip()
        assert tags == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
