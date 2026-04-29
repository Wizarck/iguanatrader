---
name: push
description: "Use when the user wants all local changes staged, committed with an auto-generated message, and pushed to remote in one step."
argument-hint: "[optional commit message]"
model: sonnet
context: fork
allowed-tools: Bash, Read, Grep, Glob
---

# Git Push Shortcut

Stage all changes, create a descriptive commit, and push to the remote.

## Workflow

1. Run `git status` and `git diff --stat` to understand all changes
2. **Commit message**:
   - If `$ARGUMENTS` contains text, use it as the commit message
   - Otherwise, generate a concise commit message from the diff (feat/fix/chore/docs prefix, 1-2 sentences)
3. Run `git add .`
4. Commit with the message, always append:
   ```
   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   ```
5. Run `git push`
6. Report: commit hash, message, and files changed count

## Rules

- If there are no changes to commit, say so and stop
- Never use `--force` or `--no-verify`
- Use HEREDOC format for commit messages:
  ```bash
  git commit -m "$(cat <<'EOF'
  message here

  Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
  EOF
  )"
  ```
- If push fails (e.g., remote rejected), report the error — do NOT retry with force

## Request

$ARGUMENTS
