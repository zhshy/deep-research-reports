#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地目录按 Git Data API 原子提交到 GitHub（无需 git clone / git push）。

用法：GH_TOKEN=xxx python3 ghpush.py <local_dir> <owner/repo> <branch> <tag> <message>
"""
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN", "").strip()
if not TOKEN:
    sys.exit("缺少 GH_TOKEN")


def call(method, path, payload=None):
    url = API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "token " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:600]
        sys.exit(f"HTTP {e.code} on {method} {path}\n{body}")


def blob_sha(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob " + str(len(data)).encode() + b"\0")
    h.update(data)
    return h.hexdigest()


def scan(root):
    """返回 {相对路径: 绝对路径}，跳过 .DS_Store 与隐藏文件。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            ap = os.path.join(dirpath, fn)
            rp = os.path.relpath(ap, root).replace(os.sep, "/")
            out[rp] = ap
    return out


def main():
    local_dir, repo, branch, tag, msg = sys.argv[1:6]

    me = call("GET", "/user")
    print(f"认证用户: {me.get('login')}")

    ref = call("GET", f"/repos/{repo}/git/ref/heads/{branch}")
    head = ref["object"]["sha"]
    print(f"远端 {branch} HEAD: {head[:12]}")

    base_tree = call("GET", f"/repos/{repo}/git/commits/{head}")["tree"]["sha"]
    remote = {}
    for e in call("GET", f"/repos/{repo}/git/trees/{base_tree}?recursive=1")["tree"]:
        if e["type"] == "blob":
            remote[e["path"]] = e["sha"]
    print(f"远端文件数: {len(remote)}")

    files = scan(local_dir)
    local = {}
    raw = {}
    for rp, ap in files.items():
        with open(ap, "rb") as f:
            data = f.read()
        raw[rp] = data
        local[rp] = blob_sha(data)
    print(f"本地文件数: {len(local)}")

    added = sorted(p for p in local if p not in remote)
    modified = sorted(p for p in local if p in remote and remote[p] != local[p])
    deleted = sorted(p for p in remote if p not in local)
    print(f"新增 {len(added)} / 修改 {len(modified)} / 删除 {len(deleted)}")
    for p in added:
        print("  +", p)
    for p in modified:
        print("  ~", p)
    for p in deleted:
        print("  -", p)

    if not (added or modified or deleted):
        print("无需提交：本地与远端逐字节一致。")
        return

    tree = []
    for p in added + modified:
        bl = call("POST", f"/repos/{repo}/git/blobs",
                  {"content": base64.b64encode(raw[p]).decode(), "encoding": "base64"})
        if bl["sha"] != local[p]:
            sys.exit(f"blob sha 不一致: {p}")
        tree.append({"path": p, "mode": "100644", "type": "blob", "sha": bl["sha"]})
    for p in deleted:
        tree.append({"path": p, "mode": "100644", "type": "blob", "sha": None})

    new_tree = call("POST", f"/repos/{repo}/git/trees",
                    {"base_tree": base_tree, "tree": tree})["sha"]
    commit = call("POST", f"/repos/{repo}/git/commits",
                  {"message": msg, "tree": new_tree, "parents": [head]})
    print(f"新提交: {commit['sha'][:12]}  tree: {new_tree[:12]}")

    call("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", {"sha": commit["sha"]})
    print(f"已更新 refs/heads/{branch}")

    if tag and tag not in ("-", "none"):
        try:
            call("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/tags/{tag}", "sha": commit["sha"]})
            print(f"已打标签 {tag}")
        except SystemExit as e:
            print(f"打标签失败（可能已存在）: {e}")

    # 逐字节校验：重取远端树，与本地 blob sha 全量比对
    check = {}
    for e in call("GET", f"/repos/{repo}/git/trees/{commit['sha']}?recursive=1")["tree"]:
        if e["type"] == "blob":
            check[e["path"]] = e["sha"]
    diff = [p for p in local if check.get(p) != local[p]]
    extra = [p for p in check if p not in local]
    print(f"\n校验：期望 {len(local)} 个文件，远端 {len(check)} 个")
    print(f"不一致: {diff if diff else '无'}   多余: {extra if extra else '无'}")
    print("✅ 逐字节一致" if not diff and not extra else "❌ 校验未通过")


if __name__ == "__main__":
    main()
