---
name: check-updates
description: >
  Checks all ELIGIA stack components for available updates (Docker images, Python packages,
  git repos, skills-manager.exe, Hermes, npm). Applies safe Docker updates with healthcheck
  and automatic rollback. Sends formatted report via WhatsApp.
model: sonnet
allowed-tools: Bash
---

# check-updates — Stack Update Checker

Checks all ELIGIA stack components for updates and applies safe ones.

## Steps

### Step 1 — Resolve paths

```bash
ONEDRIVE_PATH="${ONEDRIVE_PATH:-$OneDrive}"
ELIGIA_DIR="${ELIGIA_DIR:-C:/EligIA}"
SCRIPT="${ONEDRIVE_PATH}/.eligia/stack/scripts/check-updates.py"
```

Verify `$SCRIPT` exists. If not, print error and stop.

### Step 2 — Run update checker

```bash
python "$SCRIPT" --apply --json --save 2>&1
```

Capture the JSON output. If the command fails, retry without `--apply` (dry-run fallback).

### Step 3 — Format and deliver report

Parse the JSON output and generate a WhatsApp-friendly summary:

```
🔄 *Stack Update Report — YYYY-MM-DD*

🐳 *Docker*
  ✅ atlassian-marlink — al día
  ⬆️ hindsight — actualizado (abc123→def456)

📦 *Python*
  ✅ litellm 1.83.3
  ⬆️ fastmcp 3.2.0 → 3.2.1
     pip install --upgrade fastmcp

🗂️ *Git Repos*
  ⬆️ paperclip-mcp — 3 commits disponibles

🖥️ *Desktop*
  ⬆️ skills-manager.exe — nueva versión disponible
     https://github.com/xingkongliang/skills-manager/releases/latest

🤖 *Hermes*
  ⚠️ 69 commits de retraso
     hermes update && repair-hermes-windows.ps1

📋 *npm*
  ℹ️ trello-mcp latest: 1.1.0
```

Only include components with status != `up_to_date` in the summary.
If everything is up to date, send: `✅ Todo el stack está al día.`

$ARGUMENTS
