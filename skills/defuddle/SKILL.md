---
name: defuddle
description: >
  Extract clean markdown from web pages using the Defuddle CLI — removes
  navigation, ads, and clutter to save tokens. Use instead of WebFetch when
  the user provides a URL to read or analyze (articles, docs, blog posts).
  Do NOT use for URLs ending in .md (already markdown — use WebFetch directly).
  Requires: npm install -g defuddle
model: haiku
allowed-tools: Bash
---

# Defuddle

Extracts clean, token-efficient markdown from web pages.
Preferred over WebFetch for article/documentation URLs.

## Basic Usage
```bash
# Extract to stdout (markdown)
defuddle parse <url> --md

# Save to file
defuddle parse <url> --md -o content.md

# Get metadata only
defuddle parse <url> -p title
defuddle parse <url> -p description
defuddle parse <url> -p author
```

## When to Use
- Articles, blog posts, documentation pages
- Any page where you want content without navigation/ads

## When NOT to Use
- URLs ending in `.md` → use WebFetch directly
- JS-heavy SPAs that require execution → use Playwright fallback
- Anti-bot protected pages → use Camoufox MCP

## Install (once)
```bash
npm install -g defuddle
```
