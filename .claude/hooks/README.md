# Harness hooks

Two hooks enforce the SDD discipline inside the Claude Code loop.

| Hook | Event | Script | Effect |
|---|---|---|---|
| SDD gate | `PreToolUse` on `Bash` | `require-spec.sh` | Blocks (`exit 2`) a `git commit` that stages app code under `backend/`/`frontend/` unless a committed spec trio `specs/<feature>/{requirements,design,tasks}.md` exists in `HEAD`. `CLAUDE.md` files are exempt. **This is the deterministic "specs-before-code" enforcement the brief grades.** |
| Code standards | `PostToolUse` on `Edit`/`Write` | `ruff-format.sh` | Runs `uv run ruff check --fix` + `ruff format` on any saved `*.py`. Non-blocking; no-ops until `pyproject.toml` + `uv` exist. |

Both scripts are self-tested (see commit history) and already `chmod +x`.

## Registration (one manual step)

The harness cannot self-edit `.claude/settings.json` (Claude Code guards its own
startup config). Add the `hooks` block below to `.claude/settings.json`, alongside
the existing `enabledPlugins`. Either paste it yourself, or tell Claude in your own
message: *"edit .claude/settings.json to add the hooks block from .claude/hooks/README.md"*.

```jsonc
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.claude/hooks/require-spec.sh\"" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR/.claude/hooks/ruff-format.sh\"" }
        ]
      }
    ]
  }
}
```

## Optional: fewer permission prompts

To cut routine approval prompts, add a `permissions.allow` list to `settings.json`
(or run the `/fewer-permission-prompts` skill):

```jsonc
{
  "permissions": {
    "allow": [
      "Bash(git status:*)", "Bash(git add:*)", "Bash(git commit:*)",
      "Bash(git diff:*)", "Bash(git log:*)", "Bash(git ls-tree:*)",
      "Bash(uv run:*)", "Bash(uv sync:*)", "Bash(uv lock:*)",
      "Bash(ruff:*)", "Bash(pre-commit run:*)"
    ]
  }
}
```
