---
name: obsidian-cli
description: >
  Interact with Obsidian vaults using the Obsidian CLI — read, create, search,
  and manage notes, tasks, properties, and more. Also supports plugin development
  (reload, eval, DOM inspection). Use when the user asks to interact with an
  Obsidian vault from the command line. Requires: npm install -g @obsidianmd/obsidian-cli
model: sonnet
allowed-tools: Bash
---

# Obsidian CLI

## Syntax
```bash
obsidian <command> [parameters] [flags]
```
Parameters: `name="value"` (wikilink resolution) or `path="exact/path.md"` (exact path)
First parameter for multi-vault setups: `vault="Vault Name"`

## File Targeting
- By name (wikilink): `file="Note Name"` — Obsidian resolves ambiguity
- By path: `path="folder/Note Name.md"` — exact path from vault root
- Daily note: `daily:read`, `daily:append content="text"`

## Core Commands
```bash
# Read a note
obsidian read file="Note Name"

# Create a note
obsidian create file="New Note" content="# Title\n\nContent here"

# Append to a note
obsidian append file="Note Name" content="New paragraph"

# Search vault
obsidian search query="search terms"

# List tasks in a note
obsidian tasks file="Note Name"

# List all tags
obsidian tags

# Get backlinks for a note
obsidian backlinks file="Note Name"
```

## Property Management
```bash
# Set a property
obsidian property:set file="Note Name" property="status" value="active"

# Read properties
obsidian read file="Note Name" --json | jq '.properties'
```

## Output Flags
- `--copy` — copy output to clipboard
- `silent` — don't open the note in Obsidian
- `total` — return count only
- `--json` — machine-readable JSON output

## Plugin Development
```bash
obsidian plugin:reload plugin="plugin-id"
obsidian eval script="console.log(app.vault.getName())"
obsidian dev:errors
obsidian dev:screenshot output="screenshot.png"
obsidian dev:console
obsidian dev:dom selector=".markdown-preview-view"
```

## Prerequisites
```bash
npm install -g @obsidianmd/obsidian-cli
# Obsidian must be running for CLI commands to work
```
