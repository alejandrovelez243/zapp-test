#!/usr/bin/env bash
# Code-standards hook (PostToolUse on Edit|Write) — auto-apply ruff to *.py.
#
# Mirrors pre-commit inside the agent loop. Always non-blocking (exit 0); no-ops
# until a Python project (pyproject.toml) and uv exist, so it is safe before the
# backend is scaffolded.
set -uo pipefail

input="$(cat)"
fp="$(printf '%s' "$input" \
  | python3 -c 'import sys,json;
try: print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))
except Exception: print("")' 2>/dev/null || true)"

case "$fp" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$fp" ] || exit 0

if command -v uv >/dev/null 2>&1 && [ -f "pyproject.toml" ]; then
  uv run ruff check --fix "$fp" >/dev/null 2>&1 || true
  uv run ruff format "$fp" >/dev/null 2>&1 || true
fi
exit 0
