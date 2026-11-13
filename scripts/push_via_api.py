"""用 GitHub Git Data API 推送（HTTPS 传输被中间设备 reset 时的兜底通道）。

背景：本机到 github.com:443 的 git-upload-pack 大包会被重置，但 api.github.com
的普通 HTTPS 请求可用。Git Data API 允许分步创建 blob/tree/commit/ref，
每个请求体都小，不触发中间设备的包大小限制。

用法（不要在任何输出里打印 token）：
    python push_via_api.py --repo badhope/moneyhelper --branch main --token-env GH_BADHOPE_TOKEN
    python push_via_api.py ... --tag v3.0.0

行为：
- 从 git ls-tree 读取**当前 HEAD** 的文件清单（含删除的文件，不需要逐个上传全历史）
- 只创建 changed blobs（用 HEAD 与远端 commit 的文件列表对比；为稳妥起见全部上传）
- 建 tree（base_tree 省略 = 全量快照）→ commit → 快进 ref
- 幂等：远端已是同一 tree 时跳过
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import time

import httpx

API = "https://api.github.com"
BATCH_LIMIT = 40  # 每次批量创建 blob 的并发数，过大会触发 secondary rate limit


def sh(*args: str, cwd: str | None = None) -> str:
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout


def list_files(repo: str) -> list[tuple[str, str, str]]:
    """返回 [(mode, sha, path)]，取自本地 HEAD 的 tree（不含子模块）。"""
    raw = sh("git", "ls-tree", "-r", "-z", "HEAD", cwd=repo)
    out = []
    for entry in raw.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            out.append((parts[0], parts[2], path))
    return out


def blob_bytes(repo: str, sha: str) -> bytes:
    """用 git cat-file 取 blob 内容（二进制安全）。"""
    proc = subprocess.run(
        ["git", "cat-file", "blob", sha], cwd=repo, capture_output=True, check=True
    )
    return proc.stdout


class GH:
    def __init__(self, token: str, owner: str, name: str):
        self.owner = owner
        self.name = name
        self.c = httpx.Client(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def req(self, method: str, path: str, **kw):
        """path 是不含 /repos/{owner}/{name} 的 API 子路径（如 /git/blobs）。"""
        url = f"{API}/repos/{self.owner}/{self.name}{path}"
        for attempt in range(5):
            r = self.c.request(method, url, **kw)
            if r.status_code in (403, 429) and attempt < 4:
                # 二次限流：退避重试
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
            return r.json() if r.content else {}
        raise RuntimeError(f"{method} {path} retries exhausted")

    def create_blob(self, content: bytes) -> str:
        payload = {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"}
        return self.req("POST", "/git/blobs", json=payload)["sha"]

    def get_tree(self, sha: str) -> dict[str, str]:
        """远端 tree 的 path -> blob sha 映射（recursive，单仓库 690 文件一次拿全）。"""
        data = self.req("GET", f"/git/trees/{sha}?recursive=1")
        return {
            e["path"]: e["sha"]
            for e in data.get("tree", [])
            if e.get("type") == "blob"
        }

    def create_tree(self, entries: list[dict], base_tree: str | None = None) -> str:
        payload: dict = {"tree": entries}
        if base_tree:
            payload["base_tree"] = base_tree
        return self.req("POST", "/git/trees", json=payload)["sha"]

    def create_commit(self, message: str, tree: str, parents: list[str]) -> str:
        return self.req(
            "POST", "/git/commits", json={"message": message, "tree": tree, "parents": parents}
        )["sha"]

    def get_ref(self, owner: str, name: str, branch: str) -> dict | None:
        try:
            return self.req("GET", f"/git/ref/heads/{branch}")
        except RuntimeError as exc:
            if "404" in str(exc):
                return None
            raise

    def update_ref(self, owner: str, name: str, branch: str, sha: str, force: bool = False):
        return self.req(
            "PATCH",
            f"/git/refs/heads/{branch}",
            json={"sha": sha, "force": force},
        )

    def create_ref(self, owner: str, name: str, ref: str, sha: str):
        return self.req("POST", "/git/refs", json={"ref": ref, "sha": sha})

    def create_tag(self, owner: str, name: str, tag: str, sha: str, message: str):
        obj = self.req(
            "POST",
            "/git/tags",
            json={"tag": tag, "message": message, "object": sha, "type": "commit"},
        )
        try:
            self.create_ref(owner, name, f"refs/tags/{tag}", obj["sha"])
        except RuntimeError as exc:
            if "422" in str(exc) or "already exists" in str(exc).lower():
                self.req("PATCH", f"/git/refs/tags/{tag}", json={"sha": obj["sha"], "force": True})
            else:
                raise


def head_tree_sha(cwd: str = ".") -> str:
    """本地 HEAD 的 tree sha（内容级验收用）。"""
    return sh("git", "rev-parse", "HEAD^{tree}", cwd=cwd).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--path", default=".", help="本地 git 仓库路径")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--tag", default="")
    ap.add_argument("--token-env", default="GH_BADHOPE_TOKEN")
    ap.add_argument("--message-file", default="")
    ap.add_argument(
        "--incremental",
        action="store_true",
        help="对比远端 tree，只上传有变化的 blob（推荐；需要远端已存在分支）",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"missing ${args.token_env}", file=sys.stderr)
        return 2

    owner, name = args.repo.split("/", 1)
    head_sha = sh("git", "rev-parse", "HEAD", cwd=args.path).strip()
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as fh:
            msg = fh.read()
    else:
        msg = sh("git", "log", "-1", "--pretty=%B", cwd=args.path)
    files = list_files(args.path)
    print(f"local HEAD {head_sha[:8]}, {len(files)} files")

    gh = GH(token, owner, name)
    ref = gh.get_ref(owner, name, args.branch)
    parents = [ref["object"]["sha"]] if ref else []
    print(f"remote {args.branch} = {parents[0][:8] if parents else '(new)'}")

    if args.dry_run:
        print("dry-run: would upload", len(files), "blobs")
        return 0

    # 0) 增量模式：对比远端 tree，只上传内容有变化的 blob。
    #    690 文件全量 × 3 镜像 ≈ 2000+ 次 API 调用，容易撞 secondary rate limit；
    #    远端 tree 与本地某个历史树一致时，差异通常只有几十个文件。
    remote_tree_sha = ""
    remote_files: dict[str, str] = {}
    if args.incremental and ref:
        head_commit = gh.req("GET", f"/commits/{ref['object']['sha']}")
        remote_tree_sha = head_commit["commit"]["tree"]["sha"]
        remote_files = gh.get_tree(remote_tree_sha)
        local_map = {p: s for _m, s, p in files}
        removed = [p for p in remote_files if p not in local_map]
        unchanged = sum(1 for p, s in remote_files.items() if local_map.get(p) == s)
        print(
            f"incremental: remote tree {remote_tree_sha[:8]}, "
            f"{unchanged} unchanged, {len(files) - unchanged} to upload, {len(removed)} removed"
        )

    # 1) blobs（逐个，串行分批）
    entries = []
    upload_count = 0
    for _i, (mode, sha, path) in enumerate(files, 1):
        if args.incremental and remote_files.get(path) == sha:
            continue  # 内容没变，blob 已在远端
        blob_sha = gh.create_blob(blob_bytes(args.path, sha))
        entry = {"path": path, "mode": "100755" if mode == "100755" else "100644", "type": "blob", "sha": blob_sha}
        entries.append(entry)
        upload_count += 1
        if upload_count % BATCH_LIMIT == 0:
            print(f"  blobs {upload_count}/{len(files)}")

    # 远端有、本地没有的文件 = 删除（sha=None 让 base_tree 里的旧条目失效）
    if args.incremental and ref:
        local_paths = {p for _m, _s, p in files}
        for path in remote_files:
            if path not in local_paths:
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})

    # 2) tree / commit / ref
    tree_sha = gh.create_tree(
        entries, base_tree=remote_tree_sha if args.incremental and ref else None
    )
    print("tree", tree_sha[:8])
    commit_sha = gh.create_commit(msg, tree_sha, parents)
    print("commit", commit_sha[:8])
    if ref:
        gh.update_ref(owner, name, args.branch, commit_sha)
    else:
        gh.create_ref(owner, name, f"refs/heads/{args.branch}", commit_sha)
    print(f"pushed {args.branch} -> {commit_sha[:8]}")

    # 校验：新 commit 的 tree 必须与本地 HEAD tree 一致（内容级验收）
    made = gh.req("GET", f"/commits/{commit_sha}")
    if made["commit"]["tree"]["sha"] != head_tree_sha(args.path):
        print("ERROR: remote tree mismatch!", file=sys.stderr)
        return 1
    print("tree verified == local HEAD tree")

    if args.tag:
        gh.create_tag(owner, name, args.tag, commit_sha, f"Moneyhelper {args.tag}")
        print("tag", args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
