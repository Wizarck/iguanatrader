---
name: context7
description: >
  Fetch up-to-date library documentation via Context7 MCP.
  Given a library name and optional topic, resolves the library ID and
  retrieves current docs to ground coding tasks in accurate, versioned APIs.
  Use when implementing features with libraries that change frequently
  (frameworks, AI SDKs, ORMs, cloud SDKs, etc.).
argument-hint: "<library> [topic]"
model: haiku
allowed-tools: mcp__context7__resolve-library-id, mcp__context7__get-library-docs
---

# Context7 — Library Documentation Fetcher

You fetch up-to-date library documentation using the Context7 MCP server.

## Input parsing

The argument is: `$ARGUMENTS`

Parse it as: `<library> [topic]`

- **library** (required): the library or framework name (e.g. `fastapi`, `next.js`, `langchain`, `anthropic`)
- **topic** (optional): the specific area of interest (e.g. `routing`, `streaming`, `tool use`)

If no argument is provided, print:
```
Usage: /context7 <library> [topic]
Examples:
  /context7 fastapi routing
  /context7 anthropic tool-use
  /context7 next.js app-router
```
Then stop.

## Steps

### Step 1 — Resolve library ID

Call `resolve-library-id` with the library name as the query.

- If no match found → print `Library "<library>" not found in Context7. Try a different name.` and stop.
- If multiple matches → pick the most popular/relevant one (highest stars or most specific match).

### Step 2 — Fetch docs

Call `get-library-docs` with:
- The resolved library ID from Step 1
- The topic as the `topic` parameter (if provided), otherwise omit it

### Step 3 — Present results

Return the documentation concisely:
- Lead with the library name + version (if available)
- Focus on the topic if one was specified
- Include relevant code examples from the docs
- Keep it tight — this is context for a coding task, not a tutorial
