# agent-exp: Enhanced MUD Agent Design

**Date:** 2026-07-27  
**Folder:** `week2_capable/agent-exp/`

---

## Goal

Refactor the `boukensha` MUD agent (forked from step 12 context management) to add:

1. Persistent room memory with auto-pathfinding
2. Goal tracking with HP-triggered flee logic
3. A Python web dashboard (replaces Ruby log_viz) with live feed, map, waterfall, and goals tabs
4. Token-minimization programs that handle navigation, room processing, and combat loops in Python — calling the LLM only when decisions are genuinely needed

---

## Decisions Made

| Question | Answer |
|---|---|
| Map format | Force-directed graph (D3.js) — nodes = rooms, edges = exits |
| UI strategy | Web-first with TUI as fallback (`--no-web` flag) |
| Dashboard language | Python (Flask + SSE) — retire Ruby Sinatra app |
| Room hash key | `sha256(title + "\n" + description)[:12]` |
| Goal file format | Structured YAML with defined fields |

---

## Architecture

See `agent-exp/architecture.md` for the full component overview, data-flow diagram, sequence diagrams, and file layout.

### New subsystems

**Memory** (`src/boukensha/memory/`)
- `RoomParser` — parses raw MUD `look` text into structured dict; pure function, no side effects
- `RoomMemory` — persists each unique room as `{hash}.json` under `.boukensha/memory/rooms/`
- `WorldGraph` — NetworkX DiGraph connecting room hashes via exit edges; persisted as JSON
- `Pathfinder` — Dijkstra over WorldGraph; returns direction sequence

**Goals** (`src/boukensha/goals/`)
- `GoalManager` — atomic read/write of `.boukensha/goals/current.yaml`
- `CombatMonitor` — stateless HP-threshold check; updates goal to `flee` if triggered

**Token-saving tools** (`src/boukensha/tools/`)
- `navigate_to(destination)` — Python pathfinding + move loop, zero LLM calls for known paths
- `process_room()` — returns only the diff vs stored memory (empty string for known unchanged rooms)
- `combat_loop(target, flee_hp)` — Python fight loop; LLM consulted only for skill selection

**Dashboard** (`src/boukensha/dashboard/`)
- Flask app with SSE for live streaming
- Five tabs: Live, Map, Waterfall, Goals, Sessions
- Modular: add a tab by adding a JS module + optional API endpoint

---

## Goal File Schema

```yaml
current_goal: "string"
priority: explore | fight | heal | flee | idle
hp_flee_threshold: int
status: active | paused | completed | flee
notes: "string"
last_updated: "ISO8601"
mud_basics: |
  multiline help text for the agent
```

---

## Token Minimization Summary

| Situation | Program handles | LLM still needed |
|---|---|---|
| Known room re-entry | `process_room()` returns empty diff | Never |
| Known-path navigation | `navigate_to()` issues moves in Python | Never |
| Routine combat | `combat_loop()` loops attack commands | Skill choice only |
| HP threshold breach | `CombatMonitor` updates goal | Reads directive |
| Unknown first-visit room | `process_room()` returns full data | Yes — first visit |

---

## Implementation Phases

1. **Memory subsystem** — `RoomParser`, `RoomMemory`, `WorldGraph`, `Pathfinder` + tests
2. **Goal subsystem** — `GoalManager`, `CombatMonitor` + tests
3. **Token-saving tools** — `navigate_to`, `process_room`, `combat_loop` + wire into `__init__.py`
4. **Dashboard** — Flask app, SSE, five tabs, D3 map, waterfall chart
5. **bin/boukensha** — CLI entry point, `--web`/`--no-web` flags
6. **Integration** — connect Logger → EventBus → SSE; connect `process_room` to `look` tool; end-to-end test

---

## Out of Scope

- Multiplayer or multi-character support
- Spell/magic automation (beyond existing `cast_spell` tool)
- Character creation flow
- Ruby log_viz migration path (superseded, can be deleted)
