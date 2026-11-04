#!/usr/bin/env bash
# 一键发布：重建索引 + 通过 Git Data API 推送（无需 git clone / git push）
#
# 用法：
#   GH_TOKEN=ghp_xxx bash scripts/publish.sh "release: 2026-11-05 日报"
#
# 可选环境变量：
#   BRANCH   默认 main
#   REPO     默认 zhshy/deep-research-reports
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${GH_TOKEN:-}" ]; then
  echo "错误：缺少 GH_TOKEN。用法：GH_TOKEN=xxx bash scripts/publish.sh \"提交说明\"" >&2
  exit 1
fi

MSG="${1:-chore: update reports}"
BRANCH="${BRANCH:-main}"
REPO="${REPO:-zhshy/deep-research-reports}"
PY="${PYTHON:-python3}"

echo "==> 1/2 重建索引"
"$PY" scripts/build_index.py

echo "==> 2/2 推送（$REPO @ $BRANCH）"
"$PY" scripts/ghpush.py . "$REPO" "$BRANCH" - "$MSG"
