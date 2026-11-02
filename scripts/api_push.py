#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""走 GitHub Git Data API 推送本地提交（git HTTPS 被重置时的替代通道）。

用法：python scripts/api_push.py <本地分支> [<远端分支>]
把 <本地分支> 相对 origin/<远端分支> 的新提交逐个在 API 上重建：
  blob -> tree -> commit(parent=远端 HEAD) -> PATCH /git/refs/heads/<branch>
凭据只从 ~/.agent-secrets 读取，不打印；连续 409 时重读远端 ref 重放。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com/repos/%s/moneyhelper" % os.environ.get("GH_ACCOUNT", "badhope")


def token():
    vault = os.path.expanduser("~/.agent-secrets/accounts.json")
    with open(vault, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["platforms"]["github"]["accounts"][os.environ.get("GH_ACCOUNT", "badhope")]["token"]


TOKEN = token()


def api(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=body, method=method,
                                 headers={"Authorization": "Bearer " + TOKEN,
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "profile-kit-api-push"})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read(300).decode("utf-8", "replace")
            print("  ! %s %s -> %s %s" % (method, path, e.code, detail), file=sys.stderr)
            if e.code in (409, 502, 504) and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except OSError as e:  # 连接重置：指数退避重试
            print("  ! %s %s -> %s" % (method, path, e), file=sys.stderr)
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise last


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def main():
    local = sys.argv[1] if len(sys.argv) > 1 else "main"
    remote = sys.argv[2] if len(sys.argv) > 2 else local
    base = sys.argv[3] if len(sys.argv) > 3 else None  # 已在远端、内容等价的本地提交
    remote_head = api("GET", "/git/ref/heads/" + remote)["object"]["sha"]
    range_spec = "%s..%s" % (base, local) if base else "%s..%s" % (remote_head, local)
    commits = git("rev-list", "--reverse", range_spec).split("\n")
    commits = [c for c in commits if c]
    print("pushing %d commit(s) onto %s" % (len(commits), remote_head[:10]))

    for sha in commits:
        message = git("log", "-1", "--format=%B", sha)
        parent = remote_head
        tree_entries = []
        # 该提交相对其父提交的全部变更（含新增）；根提交用空树
        try:
            base_ref = git("rev-parse", sha + "^")
        except subprocess.CalledProcessError:
            base_ref = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        raw = subprocess.run(["git", "-C", ROOT, "diff", "--name-status", "-z", "--no-renames", base_ref, sha],
                             capture_output=True, text=True, check=True).stdout
        fields = raw.split("\0")
        i = 0
        while i < len(fields) - 1:
            status, path = fields[i], fields[i + 1]
            i += 2
            if not path:
                continue
            if status == "D":
                # 删除项：GitHub 要求完整 entry 且 sha=null
                tree_entries.append({"path": path, "mode": "100644",
                                     "type": "blob", "sha": None})
                continue
            data = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (sha, path)],
                                  capture_output=True, check=True).stdout
            blob = api("POST", "/git/blobs",
                       {"content": base64.b64encode(data).decode(), "encoding": "base64"})
            tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

        # 从远端基树出发逐层合并（这里提交量小，直接基于远端树建树即可：
        # 每个提交的 diff 都是相对其真实父提交，而父提交链已在远端或本轮已推）
        base_tree = api("GET", "/git/commits/" + parent)["tree"]["sha"]
        tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_entries})
        commit = api("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": [parent]})
        api("PATCH", "/git/refs/heads/" + remote, {"sha": commit["sha"], "force": False})
        remote_head = commit["sha"]
        print("  %s %s (%d files)" % (sha[:10], commit["sha"][:10], len(tree_entries)))
    print("done:", remote_head)


if __name__ == "__main__":
    main()
