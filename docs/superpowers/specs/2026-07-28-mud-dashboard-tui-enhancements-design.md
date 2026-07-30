# MUD Dashboard & TUI Enhancements — Design Spec

**Date:** 2026-07-28  
**Project:** boukensha (agent-exp)  
**Branch:** development branch (to be created)

---

## Overview

Four targeted improvements to the boukensha MUD agent dashboard and TUI:

1. Waterfall step detail panel — click any step to see full MUD I/O
2. Map room rectangles — replace circles with labeled rectangles
3. Movement arrow — yellow arrow shows where the current character came from
4. Kill switch — Escape key pauses the running agent and asks what to do next

---

## Feature 1 — Waterfall Step Detail Panel

### Problem

`waterfall.js` discards `args` and `result` from SSE events as they arrive. Each step only retains `{label, start, end, type}`, so there is no way to inspect what was sent to the MUD or what came back.

### Design

**Data layer (`waterfall.js`):**

- Each step object gains four new fields:
  - `args` — copied from `event.args` on `tool_call` events
  - `result` — copied from `event.result` on the matching `tool_result` event
  - `startAt` — ISO timestamp from `event.at` on `tool_call`
  - `endAt` — ISO timestamp from `event.at` on `tool_result`
- Iteration steps additionally track `inputTokens` / `outputTokens` collected from the `response` event that closes the iteration.

**UI (`waterfall.js`, `index.html`, `style.css`):**

- The waterfall tab splits into two columns: the chart on the left (≥60% width), a detail panel on the right.
- Clicking a waterfall bar sets it as selected (highlighted border) and populates the detail panel.
- The detail panel renders four sections:
  1. **Timing** — start time, end time, duration in ms
  2. **Tokens** — input / output token counts (shown as `—` for tool steps where no response event is attached)
  3. **Tool args** — pretty-printed JSON of `args`
  4. **MUD response** — raw text of `result`, in a scrollable `<pre>`
- Clicking elsewhere in the chart deselects and clears the panel.
- No modal, no new page — everything in-tab.

**Token association:** The `response` event follows the iteration's tool results. When a `response` event arrives, its token counts are applied to the most recent `iteration`-type step (not the tool step).

### Files changed

- `src/boukensha/dashboard/static/waterfall.js`
- `src/boukensha/dashboard/templates/index.html` (add detail panel div)
- `src/boukensha/dashboard/static/style.css` (split layout, detail panel styles)

---

## Feature 2 — Map Room Rectangles

### Problem

Rooms render as `<circle r="8">` with a text label floating to the right. This is hard to read and doesn't convey room name clearly at a glance.

### Design

**Shape:** Replace each `circle` + adjacent `text.node-label` with a `<rect>` (110px wide × 30px tall) centered on the compass grid position (`cx = node.x`, `cy = node.y`). Room name is rendered as a `<text>` centered inside the rectangle. Names longer than ~15 characters are truncated with `…`.

**Connections:** Exit lines currently connect to the node's `(x, y)` point. With rectangles, lines will still connect to `(x, y)` — the center. This is visually acceptable since the grid spacing (220px) is much larger than the rectangle (110×30px), so lines will visually approach the rectangle edge closely enough. No clipping math needed.

**Click handler:** The `click` event moves from the `circle` to the `rect`. The existing `showRoomPopup` / `positionPopup` logic is unchanged — it already uses screen coordinates, not node shape.

**Player markers:** The star (`★`) is currently rendered 22px above `node.y`. With a 30px-tall rect centered at `node.y`, the top of the rect is at `node.y - 15`. The star offset changes to `node.y - 24` to sit just above the rect's top edge.

**Constant:** `LABEL_MAX_CHARS` drops from 20 to 15 to fit the fixed-width box.

### Files changed

- `src/boukensha/dashboard/static/map.js`

---

## Feature 3 — Movement Arrow

### Problem

`PlayerTracker` only stores a player's current room. There is no record of where they came from, so no arrow can be drawn.

### Design

**Backend (`memory/player_tracker.py`):**

- `update(name, room_hash, title)` now reads the current record before writing.
- If a current `room_hash` exists and differs from the new one, it writes the old value into `prev_room_hash` in the updated record.
- If the room hasn't changed, `prev_room_hash` is preserved as-is (so the last real movement arrow persists).
- `prev_room_hash` is `None` on first encounter.

**API (`dashboard/app.py`):**

- `/api/players` already returns the full `PlayerTracker.read_all()` dict, so `prev_room_hash` flows through automatically with no API changes.

**Frontend (`map.js`):**

- After rendering player star markers, iterate players again.
- For each player with a non-null `prev_room_hash` that maps to a node in `nodeById`:
  - Draw a `<line>` from `prev_node.{x,y}` to `current_node.{x,y}`.
  - Color: `#ffd23f` (same yellow as the star).
  - Stroke-width: 2.5px.
  - End: an SVG `<marker>` arrowhead (triangle, filled `#ffd23f`), defined once in the SVG `<defs>` block.
- The arrow is drawn in `playersLayer` (same group as stars), so it moves with zoom/pan automatically.
- Only one arrow per player (prev → current). No history trail.

**SVG marker definition:** Added once to the `<defs>` of `#map-svg` during `loadMap()`:

```xml
<marker id="arrow-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
  <path d="M0,0 L0,6 L8,3 z" fill="#ffd23f" />
</marker>
```

### Files changed

- `src/boukensha/memory/player_tracker.py`
- `src/boukensha/dashboard/static/map.js`

---

## Feature 4 — Kill Switch / Pause-and-Ask

### Problem

`action_interrupt_turn()` in `tui.py` calls `self._future.cancel()`, which has no effect on a `ThreadPoolExecutor` task that is already running. The agent loop runs uninterrupted. Additionally, `run_turn()` calls itself recursively via auto-continue when `last_stop_reason == "max_iterations"`, which can produce extended loops that are impossible to break out of.

### Design

**Interrupt flag (`repl.py`):**

- `Repl` gains a `threading.Event` called `_interrupt_requested`.
- New method `request_interrupt()` sets the flag.
- New method `clear_interrupt()` clears the flag.

**Agent loop check (`agent.py`):**

- At the top of each iteration in `Agent.run()`, check `self._logger`-adjacent or injected interrupt flag.
- Cleanest approach: `Agent.__init__` accepts an optional `interrupt_event: threading.Event | None = None`.
- `Repl._run_turn_sync` passes `self._interrupt_requested` to the `Agent` constructor.
- When `interrupt_event.is_set()` at the start of an iteration, `Agent.run()` sets `last_stop_reason = "interrupted"` and returns the current result string (same path as `max_iterations`).

**TUI pause prompt (`tui.py`):**

- `action_interrupt_turn()` now calls `self._repl.request_interrupt()` instead of `self._future.cancel()`.
- When `_on_turn_complete` fires and `_repl._interrupt_requested.is_set()`, the TUI enters **pause mode**:
  - Input is re-enabled.
  - A one-line status message appears: `[paused — c=continue  s=stop  or type new instructions]`
  - The next submission is interpreted as a pause response:
    - `c` or `continue` → clears the flag first, then re-runs `run_turn(AUTO_CONTINUE_DIRECTIVE)`
    - `s` or `stop` → clears the flag, stays idle (returns to normal prompt)
    - Any other text → clears the flag first, then runs `run_turn(that_text)` as a new instruction
  - The flag is always cleared before acting on the response, so the new turn never sees a stale set flag.
  - After one response, pause mode exits regardless.

**Auto-continue guard:** When `_interrupt_requested` is set, `run_turn()` does not enter the auto-continue branch even if `last_stop_reason == "max_iterations"`. This catches the recursive-loop case cleanly.

### Files changed

- `src/boukensha/repl.py`
- `src/boukensha/agent.py`
- `src/boukensha/tui.py`

---

## Branch Strategy

All four features are developed together on a single branch (e.g., `feature/dashboard-tui-enhancements`) off `main`. They are independent enough to implement sequentially without conflict.

## Implementation Order (recommended)

1. **#4 Kill switch** — touches core loop; best to have it working before doing extended testing of the others
2. **#1 Waterfall detail** — pure frontend, no backend changes
3. **#2 Map rectangles** — pure frontend, isolated to map.js
4. **#3 Movement arrows** — small backend change + frontend addition

## Out of Scope

- Dashboard kill switch button (browser) — deferred per user preference
- Movement history trail (only last move is shown)
- Arrowhead when prev and current room are the same (no arrow drawn)
