---
name: json-canvas
description: >
  Create and edit Obsidian JSON Canvas (.canvas) files — visual node/edge graphs
  for spatial note organization. Use when working with .canvas files or when the
  user asks to create a visual map, diagram, or canvas in Obsidian.
model: haiku
allowed-tools: Read, Edit, Write
---

# JSON Canvas

## File Format
Extension: `.canvas` — JSON structure with nodes, edges, and groups.

## Basic Structure
```json
{
  "nodes": [],
  "edges": []
}
```

## Node Types

### Text Node
```json
{
  "id": "unique-id",
  "type": "text",
  "text": "# Heading\n\nMarkdown content here",
  "x": 0,
  "y": 0,
  "width": 400,
  "height": 200,
  "color": "1"
}
```

### File Node (links to vault note)
```json
{
  "id": "unique-id",
  "type": "file",
  "file": "folder/Note Name.md",
  "x": 500,
  "y": 0,
  "width": 400,
  "height": 300
}
```

### URL Node
```json
{
  "id": "unique-id",
  "type": "link",
  "url": "https://example.com",
  "x": 0,
  "y": 300,
  "width": 400,
  "height": 200
}
```

### Group Node (container)
```json
{
  "id": "group-id",
  "type": "group",
  "label": "Group Title",
  "x": -50,
  "y": -50,
  "width": 600,
  "height": 400,
  "color": "6"
}
```

## Edges (Connections)
```json
{
  "id": "edge-id",
  "fromNode": "node-id-1",
  "fromSide": "right",
  "toNode": "node-id-2",
  "toSide": "left",
  "label": "Optional label",
  "color": "2"
}
```
`fromSide` / `toSide`: `"top"`, `"right"`, `"bottom"`, `"left"`

## Colors
Predefined: `"1"` red, `"2"` orange, `"3"` yellow, `"4"` green, `"5"` cyan, `"6"` purple
Custom: `"#ff0000"` (hex)

## ID Convention
Use short unique strings: `"node-1"`, `"concept-auth"`, `"group-backend"`.
IDs must be unique within the file.
