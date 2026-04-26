---
name: obsidian-markdown
description: >
  Create and edit Obsidian Flavored Markdown — wikilinks, embeds, callouts,
  frontmatter properties, and tags. Use when working with .md files in an
  Obsidian vault, or when the user mentions wikilinks, callouts, frontmatter,
  tags, embeds, or Obsidian notes.
model: haiku
allowed-tools: Read, Edit, Write, Glob, Grep
---

# Obsidian Markdown

## Wikilinks
- Internal link: `[[Note Name]]`
- Link with alias: `[[Note Name|Display Text]]`
- Link to heading: `[[Note Name#Heading]]`
- Link to block: `[[Note Name^block-id]]`
- Embed note: `![[Note Name]]`
- Embed heading section: `![[Note Name#Heading]]`
- Embed image/file: `![[image.png]]`

## Properties (Frontmatter)
YAML block at the top of the file, between `---` delimiters.
```yaml
---
title: Note Title
tags: [tag1, tag2]
date: 2026-04-06
status: active
---
```
Property types: text, list, number, checkbox (true/false), date (YYYY-MM-DD), datetime.
Always quote strings containing colons or special characters.

## Tags
- Inline: `#tag`, `#nested/tag`
- Frontmatter: `tags: [tag1, tag2]` (preferred for multi-tag)
- Tags must start with a letter, can contain letters, numbers, `-`, `_`, `/`

## Callouts
```
> [!note] Optional Title
> Content inside the callout.

> [!warning]+ Expanded by default
> Content here.

> [!tip]- Collapsed by default
> Content here.
```
Types: `note`, `tip`, `info`, `warning`, `danger`, `success`, `question`, `quote`, `abstract`, `bug`, `example`, `todo`, `failure`

## Block IDs
Add at end of a paragraph to create a linkable anchor:
```
This is a paragraph. ^my-block-id
```
Reference with: `[[Note#^my-block-id]]`

## Comments
Hidden from preview: `%% This text is hidden %%`

## Math
Inline: `$E = mc^2$`
Block:
```
$$
\int_a^b f(x)\,dx
$$
```

## Diagrams (Mermaid)
````
```mermaid
graph TD
    A --> B
```
````
