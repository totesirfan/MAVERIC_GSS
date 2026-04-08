# Mission-Owned Operator Help Contract

This document defines the minimum contract for moving **mission-specific command help**
out of the shared web UI and into the active mission package.

The goal is narrow:

- Keep the shared Help modal and shared UI structure
- Keep generic platform shortcuts in shared code
- Move only mission-specific command-entry syntax and wording to the mission layer

This is intended to prevent the platform from teaching MAVERIC-specific command
grammar to future missions.

## Problem

The web Help modal currently contains static command-entry text that reflects
MAVERIC's CLI grammar:

- `CMD [ARGS]`
- `[SRC] DEST ECHO TYPE CMD [ARGS]`

That is acceptable for MAVERIC, but not for a reusable SERC baseline. The
platform already treats command parsing as mission-owned behavior. Help text
for command entry should follow the same boundary.

## Design Goal

The platform should own:

- Help modal layout
- Generic sections such as send controls, queue controls, replay controls
- Rendering of help rows

The mission package should own:

- Command input syntax examples
- Mission-specific wording for command entry
- Optional notes about mission-specific TX builder behavior

## Non-Goals

This contract should **not** introduce:

- A general frontend plugin system
- Mission-specific React help modals
- Arbitrary mission-controlled HTML or JSX
- A large documentation framework inside the runtime

The data should stay small, structured, and text-only.

## Proposed Contract

Mission adapters may optionally expose mission-owned command help rows.

Recommended adapter method:

```python
def command_help_items(self) -> list[dict]:
    """Return mission-specific command-entry help rows.

    Each row is:
        {"keys": str, "desc": str}
    """
```

Example MAVERIC implementation:

```python
def command_help_items(self):
    return [
        {"keys": "CMD [ARGS]", "desc": "Shorthand entry (schema defaults)"},
        {"keys": "[SRC] DEST ECHO TYPE CMD [ARGS]", "desc": "Full form"},
        {"keys": "Up / Down", "desc": "Browse command history"},
        {"keys": "Enter", "desc": "Queue the command"},
    ]
```

Example minimal mission implementation:

```python
def command_help_items(self):
    return [
        {"keys": "COMMAND TEXT", "desc": "Mission-defined raw command input"},
        {"keys": "Enter", "desc": "Queue the command"},
    ]
```

## Backend Behavior

The backend should expose a small help payload for the frontend.

Recommended route:

```text
GET /api/help
```

Recommended response shape:

```json
{
  "sections": [
    {
      "title": "SENDING",
      "items": [
        {"keys": "Ctrl+S", "desc": "Send all queued commands"}
      ]
    },
    {
      "title": "COMMAND INPUT",
      "items": [
        {"keys": "CMD [ARGS]", "desc": "Shorthand entry (schema defaults)"}
      ]
    }
  ]
}
```

The platform should build this response as:

1. Shared generic sections from platform code
2. `COMMAND INPUT` section from the active mission adapter, if provided
3. Safe fallback rows if the adapter does not implement mission-owned help

Recommended fallback:

```json
[
  {"keys": "COMMAND TEXT", "desc": "Mission-defined command input"},
  {"keys": "Up / Down", "desc": "Browse command history"},
  {"keys": "Enter", "desc": "Queue the command"}
]
```

## Frontend Behavior

The shared Help modal should remain in shared UI code.

It should:

- Fetch structured help sections from the backend
- Render them using the existing shared layout
- Avoid hardcoding mission-specific command syntax

It should not:

- Import mission-specific React components
- Parse mission config files directly
- Reconstruct command grammar from schema internals

## Why This Boundary Is Worth Having

This change is worth doing now because it fixes a real reuse problem:

- The command parser already belongs to the mission
- Operator help for command syntax should match the actual parser
- Future SERC teams should not have to modify shared React code just to correct help text

This is not overengineering because:

- It is a tiny text-data contract
- It reuses the existing mission adapter boundary
- It keeps the shared Help modal intact

## What Should Stay Shared

The following should remain platform-owned for now:

- Help modal component structure
- Keyboard shortcut presentation
- Generic send / queue / replay guidance
- Session info block

Only the mission-specific command-entry rows should move into the mission layer.

## MAVERIC Placement

For MAVERIC, the command help data should live beside MAVERIC command parsing,
preferably in:

- `mav_gss_lib/missions/maveric/adapter.py`

This keeps:

- command parsing
- command validation
- command syntax help

in the same mission-owned layer.

Do not move this into `mission.example.yml`. The help rows are UI-shaped command
semantics, not station configuration or mission metadata.
