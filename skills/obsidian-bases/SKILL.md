---
name: obsidian-bases
description: >
  Create and edit Obsidian Bases (.base files) — database-like views of notes
  with filters, formulas, and summaries. Use when working with .base files,
  creating table/card/list/map views of vault notes, or when the user mentions
  Bases, database views, filters, or formulas in Obsidian.
model: haiku
allowed-tools: Read, Edit, Write
---

# Obsidian Bases

## File Format
Extension: `.base` — YAML content defining views, filters, and formulas.

## Basic Structure
```yaml
filters:
  and:
    - property: status
      operator: equals
      value: active
    - property: tags
      operator: contains
      value: project

views:
  - type: table
    name: Active Projects
    columns:
      - property: title
      - property: status
      - property: due_date

  - type: cards
    name: Card View
    cover: banner

  - type: list
    name: Simple List
```

## Filter Operators
- `equals`, `not-equals`
- `contains`, `not-contains`
- `greater-than`, `less-than`, `greater-than-or-equal`, `less-than-or-equal`
- `is-empty`, `is-not-empty`
- `starts-with`, `ends-with`
- Combine with `and` / `or`

## Formulas
```yaml
formulas:
  days_until_due:
    expression: "dateDiff(today(), prop('due_date'), 'days')"
  is_overdue:
    expression: "prop('due_date') < today()"
```

## View Types
- `table` — spreadsheet-like with configurable columns
- `cards` — visual card layout with optional cover image
- `list` — simple list view
- `map` — geographic map (requires location property)

## Summaries
```yaml
summaries:
  - property: effort
    function: sum
  - property: status
    function: count-by-value
```

## Properties Reference
Use `prop('property_name')` in formulas to reference note properties.
Property names are case-sensitive and must match frontmatter keys exactly.
