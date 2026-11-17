#!/usr/bin/env bash
# 一键发布：重建索引 + 通过 Git Data API 推送（无需 git clone / git push）
#
# 用法：
#   bash scripts/publish.sh "release: 2026-11-05 收盘版"
#
# 令牌来源（按顺序）：
#   1. 环境变量 GH_TOKEN
#   2. macOS 钥匙串（服务名 workbuddy-gh-token / 账号 deep-research-reports）
#
# 可选环境变量：
#   BRANCH   默认 main
#   REPO     默认 zhshy/deep-research-reports
set -euo pipefail

cd "$(dirname "$0")/.."

KEYCHAIN_SERVICE="${KEYCHAIN_SERVICE:-workbuddy-gh-token}"
KEYCHAIN_ACCOUNT="${KEYCHAIN_ACCOUNT:-deep-research-reports}"

if [ -z "${GH_TOKEN:-}" ]; then
  GH_TOKEN="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" -w 2>/dev/null || true)"
fi

if [ -z "${GH_TOKEN:-}" ]; then
  cat >&2 <<'MSG'
错误：找不到发布令牌。
  方案 A：GH_TOKEN=ghp_xxx bash scripts/publish.sh "提交说明"
  方案 B：security add-generic-password -s workbuddy-gh-token -a deep-research-reports -w <TOKEN> -U
MSG
  exit 1
fi

# 子进程（ghpush.py）需要读到，必须 export
export GH_TOKEN

MSG="${1:-chore: update reports}"
BRANCH="${BRANCH:-main}"
REPO="${REPO:-zhshy/deep-research-reports}"
PY="${PYTHON:-python3}"

echo "==> 1/2 重建索引"
"$PY" scripts/build_index.py

echo "==> 2/2 推送（${REPO} @ ${BRANCH}）"
"$PY" scripts/ghpush.py . "${REPO}" "${BRANCH}" - "${MSG}"
