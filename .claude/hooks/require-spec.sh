#!/usr/bin/env bash
# SDD gate (PreToolUse on Bash) — enforce "specs before code".
#
# Blocks a `git commit` that stages application code under backend/ or frontend/
# unless a committed spec trio (requirements.md + design.md + tasks.md) for some
# feature already exists in HEAD. CLAUDE.md rule files under those dirs are exempt.
#
# Protocol: exit 0 = allow, exit 2 = block (stderr is shown to the model).
set -uo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" \
  | python3 -c 'import sys,json;
try: print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception: print("")' 2>/dev/null || true)"
# Fail-safe: if we could not parse the command, police the raw payload.
cmd="${cmd:-$input}"

# Only police git commits.
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

# Staged, change-introducing files.
staged="$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)"
[ -z "$staged" ] && exit 0

# Application code staged under backend/ or frontend/, excluding CLAUDE.md rules.
code="$(printf '%s\n' "$staged" | grep -E '^(backend|frontend)/' | grep -vE '(^|/)CLAUDE\.md$' || true)"
[ -z "$code" ] && exit 0

# Committed file tree in HEAD (empty before the first commit).
# --full-tree: list from the repo root regardless of the caller's cwd. Without it,
# `git ls-tree` restricts the listing to the current working directory, so a commit
# launched from a subdir (e.g. backend/) never sees specs/ and is wrongly BLOCKED.
if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  tree="$(git ls-tree -r --full-tree --name-only HEAD 2>/dev/null || true)"
else
  tree=""
fi

# Does a full spec trio exist for any feature?
has_trio=0
while IFS= read -r feat; do
  [ -z "$feat" ] && continue
  if printf '%s\n' "$tree" | grep -qx "specs/$feat/requirements.md" \
     && printf '%s\n' "$tree" | grep -qx "specs/$feat/design.md" \
     && printf '%s\n' "$tree" | grep -qx "specs/$feat/tasks.md"; then
    has_trio=1
    break
  fi
done < <(printf '%s\n' "$tree" | sed -n 's#^specs/\([^/]*\)/requirements\.md$#\1#p' | sort -u)

[ "$has_trio" -eq 1 ] && exit 0

{
  echo "BLOCKED by the SDD gate (specs-before-code)."
  echo "You are committing application code under backend/ or frontend/, but no committed"
  echo "spec trio specs/<feature>/{requirements,design,tasks}.md exists in HEAD yet."
  echo "Fix: author and COMMIT the feature spec first (/specify -> /design -> /plan-tasks"
  echo "via the spec-generator agent), then commit the code."
} >&2
exit 2
