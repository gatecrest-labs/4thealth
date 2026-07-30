# MUD Dashboard & TUI Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four improvements to the boukensha MUD agent: waterfall step detail panel, map room rectangles, movement arrow, and a working kill switch with pause-and-ask prompt.

**Architecture:** The kill switch adds a cooperative interrupt flag to `Repl` and `Agent` — checked at each iteration boundary. The dashboard changes are pure frontend (JS + CSS). The movement arrow requires a small backend addition to `PlayerTracker` to persist `prev_room_hash`.

**Tech Stack:** Python 3.12, Textual (TUI), Flask + SSE (dashboard), D3 v7 (map SVG), vanilla JS (waterfall), pytest

## Global Constraints

- All work happens on a new branch off `main` — create it before touching any file
- Project root: `/Users/alan.k.wodarski/code-local/ai/claude-code-camp-2026-Q2/week2_capable/agent-exp`
- Run tests with: `cd <project-root> && .venv/bin/pytest`
- The `.venv` is already provisioned — no `pip install` needed
- Do not modify any file outside `src/boukensha/` and `tests/` (except this plan)
- Existing tests must continue to pass after every task

---

## File Map

| File | Change | Purpose |
|------|--------|---------|
| `src/boukensha/repl.py` | Modify | Add `_interrupt_requested` Event, `request_interrupt()`, `clear_interrupt()` |
| `src/boukensha/agent.py` | Modify | Accept `interrupt_event` param; check flag at top of each iteration |
| `src/boukensha/tui.py` | Modify | Wire `action_interrupt_turn()` to flag; add pause-mode prompt logic |
| `src/boukensha/memory/player_tracker.py` | Modify | Persist `prev_room_hash` on room change |
| `src/boukensha/dashboard/static/waterfall.js` | Modify | Retain args/result/timestamps; split-pane detail panel on click |
| `src/boukensha/dashboard/static/map.js` | Modify | Rect nodes; movement arrows |
| `src/boukensha/dashboard/static/style.css` | Modify | Waterfall split layout; detail panel styles |
| `src/boukensha/dashboard/templates/index.html` | Modify | Add detail panel div inside waterfall tab |
| `tests/test_agent.py` | Modify | Add interrupt-flag tests |
| `tests/test_player_tracker.py` | Modify | Add prev_room_hash persistence tests |

---

## Task 1: Create Feature Branch

**Files:**
- No source files changed

**Interfaces:**
- Produces: branch `feature/dashboard-tui-enhancements` checked out in the project repo

- [ ] **Step 1: Create and check out the branch**

```bash
cd /Users/alan.k.wodarski/code-local/ai/claude-code-camp-2026-Q2/week2_capable/agent-exp
git checkout -b feature/dashboard-tui-enhancements
```

- [ ] **Step 2: Verify branch exists**

```bash
git branch --show-current
```
Expected output: `feature/dashboard-tui-enhancements`

---

## Task 2: Kill Switch — Interrupt Flag in Repl and Agent

**Files:**
- Modify: `src/boukensha/repl.py`
- Modify: `src/boukensha/agent.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Produces:
  - `Repl.request_interrupt() -> None` — sets `_interrupt_requested`
  - `Repl.clear_interrupt() -> None` — clears `_interrupt_requested`
  - `Repl._interrupt_requested: threading.Event` — shared with Agent
  - `Agent.__init__(..., interrupt_event: threading.Event | None = None)` — new optional param
  - `Agent.run()` raises `InterruptRequested` (new exception class in `errors.py`) when flag is set at iteration start
  - `Repl.run_turn()` catches `InterruptRequested` and sets `agent.last_stop_reason = "interrupted"`

- [ ] **Step 1: Add `InterruptRequested` to errors.py**

Read `src/boukensha/errors.py` first. Then add at the end:

```python
class InterruptRequested(Exception):
    """Raised by Agent when the interrupt flag is set at an iteration boundary."""
```

- [ ] **Step 2: Write failing tests**

Open `tests/test_agent.py`. Find the existing test structure (likely uses a mock client). Add these tests:

```python
import threading
from boukensha.errors import InterruptRequested

def test_agent_stops_when_interrupt_set_before_run(mock_context, mock_registry, mock_builder, mock_client):
    """Agent should raise InterruptRequested on first iteration if flag is already set."""
    flag = threading.Event()
    flag.set()
    agent = Agent(
        context=mock_context,
        registry=mock_registry,
        builder=mock_builder,
        client=mock_client,
        interrupt_event=flag,
    )
    with pytest.raises(InterruptRequested):
        agent.run()


def test_agent_stops_when_interrupt_set_during_run(mock_context, mock_registry, mock_builder, mock_client):
    """Agent should raise InterruptRequested at next iteration boundary after flag is set."""
    flag = threading.Event()
    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            flag.set()
        # Return a tool_use response so the loop continues
        return mock_client.call(**kwargs)  # delegate to the existing mock

    mock_client.call = side_effect
    agent = Agent(
        context=mock_context,
        registry=mock_registry,
        builder=mock_builder,
        client=mock_client,
        interrupt_event=flag,
    )
    with pytest.raises(InterruptRequested):
        agent.run()
```

> **Note:** Look at the existing tests in `test_agent.py` for the exact fixture names (`mock_context`, `mock_registry`, etc.) and mock patterns. Match them — don't invent new fixtures.

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/alan.k.wodarski/code-local/ai/claude-code-camp-2026-Q2/week2_capable/agent-exp
.venv/bin/pytest tests/test_agent.py -k "interrupt" -v
```
Expected: FAIL (InterruptRequested not yet defined / agent doesn't check flag)

- [ ] **Step 4: Implement in `agent.py`**

Add `interrupt_event` param to `Agent.__init__`:

```python
def __init__(
    self,
    *,
    context: Any,
    registry: Any,
    builder: Any,
    client: Any,
    logger: Logger | None = None,
    task_settings: dict[str, Any] | None = None,
    max_iterations: int | None = None,
    max_turn_tokens: int | None = None,
    max_output_tokens: int | None = None,
    interrupt_event: threading.Event | None = None,   # <-- add this
) -> None:
    ...
    self._interrupt_event = interrupt_event  # <-- store it
```

Add `import threading` at the top of `agent.py`.

At the very top of the `while True:` loop in `run()`, before the existing `_iteration_limit_reached()` check, add:

```python
if self._interrupt_event and self._interrupt_event.is_set():
    from .errors import InterruptRequested
    raise InterruptRequested()
```

- [ ] **Step 5: Add `request_interrupt` / `clear_interrupt` to `repl.py`**

Add `import threading` at the top (after existing imports).

In `Repl.__init__`, add:
```python
self._interrupt_requested = threading.Event()
```

After `__init__`, add two methods:
```python
def request_interrupt(self) -> None:
    self._interrupt_requested.set()

def clear_interrupt(self) -> None:
    self._interrupt_requested.clear()
```

In `_run_turn_sync`, pass the event to `Agent`:
```python
agent = Agent(
    context=self._context,
    registry=self._registry,
    builder=self._builder,
    client=self._client,
    logger=self._logger,
    task_settings=self._task_settings,
    max_iterations=self._max_iterations,
    max_turn_tokens=self._max_turn_tokens,
    max_output_tokens=self._max_output_tokens,
    interrupt_event=self._interrupt_requested,   # <-- add
)
```

> **Note:** The `Agent(...)` constructor call is inside `run_turn()` in `repl.py` (around line 175), not inside `_run_turn_sync`. Add `interrupt_event=self._interrupt_requested` to that existing `Agent(...)` call.

Catch `InterruptRequested` in `run_turn()` — add after the `except ApiError` block:

```python
from .errors import InterruptRequested
except InterruptRequested:
    pass  # TUI will handle the pause prompt; just return cleanly
```

Also, guard the auto-continue branch so it does not fire when interrupted:

```python
if (
    agent.last_stop_reason == "max_iterations"
    and _auto_continue_count < self._max_auto_continues
    and self._goal_is_active()
    and not self._interrupt_requested.is_set()   # <-- add this guard
):
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_agent.py -k "interrupt" -v
```
Expected: PASS

- [ ] **Step 7: Run full test suite**

```bash
.venv/bin/pytest
```
Expected: all existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add src/boukensha/errors.py src/boukensha/agent.py src/boukensha/repl.py tests/test_agent.py
git commit -m "feat: add cooperative interrupt flag to Agent and Repl"
```

---

## Task 3: Kill Switch — TUI Pause-and-Ask Prompt

**Files:**
- Modify: `src/boukensha/tui.py`

**Interfaces:**
- Consumes: `Repl.request_interrupt()`, `Repl.clear_interrupt()`, `Repl._interrupt_requested` (from Task 2)
- Produces: When Escape is pressed during a running turn, the agent stops at the next iteration boundary and the TUI shows a one-line pause prompt. The user types `c`, `s`, or new instructions to resume/stop/redirect.

- [ ] **Step 1: Update `action_interrupt_turn`**

Replace the existing body of `action_interrupt_turn` in `tui.py`:

```python
def action_interrupt_turn(self) -> None:
    if self._live.get("active"):
        self._repl.request_interrupt()
```

- [ ] **Step 2: Add pause-mode state**

Add `self._pause_mode = False` to `Tui.__init__` after the existing instance variables.

- [ ] **Step 3: Enter pause mode when an interrupted turn completes**

In `_on_turn_complete`, add at the start:

```python
def _on_turn_complete(self) -> None:
    if self._repl._interrupt_requested.is_set():
        self._enter_pause_mode()
        return
    self.query_one("#input", Input).disabled = False
    self._live = self._idle_state()
    self._turn_count += 1
```

Add the new helper method:

```python
def _enter_pause_mode(self) -> None:
    self._pause_mode = True
    self._live = self._idle_state()
    inp = self.query_one("#input", Input)
    inp.disabled = False
    inp.placeholder = "c=continue  s=stop  or type new instructions…"
    log = self.query_one("#log", RichLog)
    log.write("[paused — c=continue  s=stop  or type new instructions]")
    inp.focus()
```

- [ ] **Step 4: Handle pause-mode input**

In `on_input_submitted`, add a check at the top of the method, before the existing `result = self._repl.handle_command(text)` line:

```python
def on_input_submitted(self, event: Input.Submitted) -> None:
    text = event.value.strip()
    event.input.clear()
    if not text:
        return

    if self._pause_mode:
        self._handle_pause_response(text)
        return

    # ... existing code continues unchanged ...
```

Add the handler method:

```python
def _handle_pause_response(self, text: str) -> None:
    self._pause_mode = False
    self._repl.clear_interrupt()
    inp = self.query_one("#input", Input)
    inp.placeholder = "Type a message…"

    if text.lower() in ("c", "continue"):
        from .repl import AUTO_CONTINUE_DIRECTIVE
        log = self.query_one("#log", RichLog)
        log.write("> (continuing…)")
        self._launch_turn(AUTO_CONTINUE_DIRECTIVE)
    elif text.lower() in ("s", "stop"):
        log = self.query_one("#log", RichLog)
        log.write("[stopped]")
        self._turn_count += 1
    else:
        log = self.query_one("#log", RichLog)
        log.write(f"> {text}")
        self._launch_turn(text)
```

- [ ] **Step 5: Verify manually (no automated test for TUI interaction)**

Run the app with `boukensha` CLI, trigger a long-running turn, press Escape, confirm the pause prompt appears, type `s` to stop. Confirm normal prompt returns.

If you cannot run the app in this environment, skip this step and note it.

- [ ] **Step 6: Run full test suite**

```bash
.venv/bin/pytest
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add src/boukensha/tui.py
git commit -m "feat: Escape key pauses agent with continue/stop/redirect prompt"
```

---

## Task 4: Movement Arrow — PlayerTracker prev_room_hash

**Files:**
- Modify: `src/boukensha/memory/player_tracker.py`
- Modify: `tests/test_player_tracker.py`

**Interfaces:**
- Produces: `PlayerTracker.update(name, room_hash, title)` — unchanged signature, but now writes `prev_room_hash: str | None` into `players.json` when the room changes. `/api/players` response automatically includes `prev_room_hash` with no API changes needed.

- [ ] **Step 1: Write failing tests**

Open `tests/test_player_tracker.py`. Add:

```python
def test_prev_room_hash_set_on_room_change(tmp_path):
    tracker = PlayerTracker(tmp_path)
    tracker.update("Aria", "room_a", "Entry Hall")
    tracker.update("Aria", "room_b", "Dark Corridor")
    data = tracker.read_all()
    assert data["Aria"]["room_hash"] == "room_b"
    assert data["Aria"]["prev_room_hash"] == "room_a"


def test_prev_room_hash_none_on_first_update(tmp_path):
    tracker = PlayerTracker(tmp_path)
    tracker.update("Aria", "room_a", "Entry Hall")
    data = tracker.read_all()
    assert data["Aria"]["prev_room_hash"] is None


def test_prev_room_hash_unchanged_when_room_same(tmp_path):
    tracker = PlayerTracker(tmp_path)
    tracker.update("Aria", "room_a", "Entry Hall")
    tracker.update("Aria", "room_b", "Dark Corridor")
    tracker.update("Aria", "room_b", "Dark Corridor")  # same room again
    data = tracker.read_all()
    # prev_room_hash should still be room_a (last real move), not room_b
    assert data["Aria"]["prev_room_hash"] == "room_a"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_player_tracker.py -k "prev_room" -v
```
Expected: FAIL

- [ ] **Step 3: Implement in `player_tracker.py`**

Replace the `update` method:

```python
def update(self, name: str, room_hash: str, title: str) -> None:
    data = self.read_all()
    existing = data.get(name, {})
    prev = existing.get("room_hash")
    data[name] = {
        "room_hash": room_hash,
        "title": title,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "prev_room_hash": prev if prev and prev != room_hash else existing.get("prev_room_hash"),
    }
    self._write(data)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_player_tracker.py -k "prev_room" -v
```
Expected: PASS (3 new tests)

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/boukensha/memory/player_tracker.py tests/test_player_tracker.py
git commit -m "feat: persist prev_room_hash in PlayerTracker for movement arrows"
```

---

## Task 5: Map Room Rectangles

**Files:**
- Modify: `src/boukensha/dashboard/static/map.js`

**Interfaces:**
- Consumes: existing `nodes`, `links`, D3 zoom/pan, `showRoomPopup`, `positionPopup`, `nodeById`, `playersLayer`
- Produces: rooms render as `<rect>` (110×30px) centered at `(node.x, node.y)` with `<text>` label inside; click behavior unchanged

No automated tests — visual change verified by loading the dashboard.

- [ ] **Step 1: Replace circle + label rendering**

In `loadMap()` in `map.js`, find the block that creates `node` (the `circle` selection) and `label` (the `text.node-label` selection). It currently looks like:

```js
const node = g.append('g').selectAll('circle').data(nodes).join('circle')
  .attr('r', 8) ...

const label = g.append('g').selectAll('text.node-label').data(nodes).join('text')
  .attr('class', 'node-label') ...
```

Replace both blocks with:

```js
const RECT_W = 110, RECT_H = 30;
const ROOM_LABEL_MAX = 15;

function shortRoomLabel(title) {
  return title.length > ROOM_LABEL_MAX ? title.slice(0, ROOM_LABEL_MAX - 1) + '…' : title;
}

const nodeGroup = g.append('g').selectAll('g.room-node').data(nodes).join('g')
  .attr('class', 'room-node')
  .attr('transform', d => `translate(${d.x - RECT_W / 2},${d.y - RECT_H / 2})`)
  .style('cursor', 'pointer')
  .on('click', (event, d) => {
    event.stopPropagation();
    const svgRect = svg.node().getBoundingClientRect();
    const t = currentZoomTransform;
    const screenX = svgRect.left - container.getBoundingClientRect().left + t.applyX(d.x);
    const screenY = svgRect.top - container.getBoundingClientRect().top + t.applyY(d.y);
    showRoomPopup(d, screenX, screenY, container);
  });

nodeGroup.append('rect')
  .attr('width', RECT_W).attr('height', RECT_H)
  .attr('rx', 4)
  .attr('fill', '#1e3a5f').attr('stroke', '#4af').attr('stroke-width', 1.5);

nodeGroup.append('text')
  .attr('x', RECT_W / 2).attr('y', RECT_H / 2)
  .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
  .attr('fill', '#aaa').attr('font-size', 11).attr('font-family', 'monospace')
  .attr('stroke', '#181818').attr('stroke-width', 2).attr('paint-order', 'stroke fill')
  .text(d => shortRoomLabel(d.title));

nodeGroup.append('title').text(d => d.title);
```

Also remove the old `const LABEL_MAX_CHARS = 20` and `function shortLabel(title)` declarations at the top of the file since they are replaced by `ROOM_LABEL_MAX` and `shortRoomLabel`.

- [ ] **Step 2: Update player star Y offset**

In `renderPlayers`, the star `y` is currently `node.y - 22`. Change to `node.y - 24` so it clears the top edge of the 30px-tall rect (top edge is at `node.y - 15`, star sits 9px above it):

```js
const starY = node.y - 24;
```

- [ ] **Step 3: Verify in browser**

Start the dashboard (or open the existing one if already running), switch to the Map tab, and confirm rooms are now rectangles with names inside. Click a rectangle — the popup should appear as before.

If you cannot run a browser in this environment, skip this step and note it.

- [ ] **Step 4: Commit**

```bash
git add src/boukensha/dashboard/static/map.js
git commit -m "feat: replace map room circles with labeled rectangles"
```

---

## Task 6: Movement Arrow on Map

**Files:**
- Modify: `src/boukensha/dashboard/static/map.js`

**Interfaces:**
- Consumes: `prev_room_hash` field now present in `/api/players` response (from Task 4), `nodeById` Map, `playersLayer` D3 group
- Produces: yellow arrow from `prev_room` node to current node for each player with a recorded move

- [ ] **Step 1: Define SVG arrowhead marker**

In `loadMap()`, right after `const g = svg.append('g');`, add a `<defs>` block to the SVG (not to `g`, since defs should be top-level):

```js
svg.append('defs').html(`
  <marker id="arrow-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
    <path d="M0,0 L0,6 L8,3 z" fill="#ffd23f" />
  </marker>
`);
```

- [ ] **Step 2: Draw arrows in `renderPlayers`**

In `renderPlayers(players)`, after the existing loop that draws stars and names, add:

```js
for (const p of players) {
  if (!p.prev_room_hash || p.prev_room_hash === p.room_hash) continue;
  const fromNode = nodeById.get(p.prev_room_hash);
  const toNode = nodeById.get(p.room_hash);
  if (!fromNode || !toNode) continue;

  playersLayer.append('line')
    .attr('x1', fromNode.x).attr('y1', fromNode.y)
    .attr('x2', toNode.x).attr('y2', toNode.y)
    .attr('stroke', '#ffd23f')
    .attr('stroke-width', 2.5)
    .attr('marker-end', 'url(#arrow-head)')
    .attr('opacity', 0.8);
}
```

- [ ] **Step 3: Verify in browser**

Move the tracked character between rooms in the MUD, then check the Map tab. A yellow arrow should appear from the previous room to the current room, with the star at the current room.

If you cannot run the app, skip and note it.

- [ ] **Step 4: Commit**

```bash
git add src/boukensha/dashboard/static/map.js
git commit -m "feat: add yellow movement arrow on map between prev and current room"
```

---

## Task 7: Waterfall Step Detail Panel

**Files:**
- Modify: `src/boukensha/dashboard/static/waterfall.js`
- Modify: `src/boukensha/dashboard/templates/index.html`
- Modify: `src/boukensha/dashboard/static/style.css`

**Interfaces:**
- Consumes: SSE events with `args`, `result`, `at`, `usage` fields (already present in the event stream — see `logger.py`)
- Produces: Clicking a waterfall bar populates a right-side detail panel with tool args, MUD response, timing, and token counts

- [ ] **Step 1: Add detail panel HTML**

In `index.html`, replace:

```html
<section id="tab-waterfall" class="tab-pane">
  <div id="waterfall-container"></div>
</section>
```

With:

```html
<section id="tab-waterfall" class="tab-pane">
  <div id="waterfall-split">
    <div id="waterfall-container"></div>
    <div id="waterfall-detail" hidden>
      <div id="waterfall-detail-title"></div>
      <div class="wf-detail-section">
        <div class="wf-detail-label">Timing</div>
        <div id="wf-timing"></div>
      </div>
      <div class="wf-detail-section">
        <div class="wf-detail-label">Tokens</div>
        <div id="wf-tokens"></div>
      </div>
      <div class="wf-detail-section">
        <div class="wf-detail-label">Tool Args</div>
        <pre id="wf-args"></pre>
      </div>
      <div class="wf-detail-section">
        <div class="wf-detail-label">MUD Response</div>
        <pre id="wf-result"></pre>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Add CSS for split layout and detail panel**

In `style.css`, replace:

```css
#waterfall-container { width: 100%; overflow-x: auto; }
```

With:

```css
#waterfall-split { display: flex; gap: 12px; flex: 1; min-height: 0; }
#waterfall-container { flex: 1; overflow-x: auto; min-width: 0; }
#waterfall-detail {
  width: 320px;
  flex-shrink: 0;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 12px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.5;
}
#waterfall-detail[hidden] { display: none; }
#waterfall-detail-title { color: #4af; font-weight: bold; margin-bottom: 10px; font-size: 13px; }
.wf-detail-section { margin-bottom: 12px; }
.wf-detail-label { color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
#wf-timing, #wf-tokens { color: #ccc; }
#wf-args, #wf-result {
  background: #111;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
  padding: 8px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 180px;
  overflow-y: auto;
  color: #8f8;
  margin: 0;
}
```

- [ ] **Step 3: Rewrite `waterfall.js` to retain payload and support click selection**

Replace the entire contents of `waterfall.js` with:

```js
const _steps = [];
let _startTime = null;
let _selectedIdx = null;

// Each step: { label, start, end, type, startAt, endAt, args, result, inputTokens, outputTokens }

window.addWaterfallEvent = function addWaterfallEvent(event) {
  const now = Date.now();
  if (!_startTime) _startTime = now;
  const elapsed = now - _startTime;

  if (event.phase === 'iteration') {
    _steps.push({
      label: 'Iter ' + event.n,
      start: elapsed, end: null,
      type: 'iteration',
      startAt: event.at || null, endAt: null,
      args: null, result: null,
      inputTokens: null, outputTokens: null,
    });
  } else if (event.phase === 'tool_call') {
    _steps.push({
      label: event.name,
      start: elapsed, end: null,
      type: 'tool',
      startAt: event.at || null, endAt: null,
      args: event.args || null,
      result: null,
      inputTokens: null, outputTokens: null,
    });
  } else if (event.phase === 'tool_result') {
    const last = _steps.findLast(s => s.type === 'tool' && s.end === null);
    if (last) {
      last.end = elapsed;
      last.endAt = event.at || null;
      last.result = event.result || null;
    }
  } else if (event.phase === 'response') {
    // Close the current open step (tool or iteration)
    const last = _steps.findLast(s => s.end === null);
    if (last) {
      last.end = elapsed;
      last.endAt = event.at || null;
    }
    // Attach token counts to the most recent iteration step
    const iterStep = _steps.findLast(s => s.type === 'iteration');
    if (iterStep && event.usage) {
      iterStep.inputTokens = event.usage.input_tokens ?? null;
      iterStep.outputTokens = event.usage.output_tokens ?? null;
    }
  }
  renderWaterfall();
};

function renderWaterfall() {
  const container = document.getElementById('waterfall-container');
  if (!_steps.length) return;
  const maxTime = Math.max(..._steps.map(s => s.end || Date.now() - _startTime));
  const rowH = 28, pad = 4, labelW = 160;
  const svgW = Math.max(container.clientWidth - labelW, 400);
  const svgH = _steps.length * rowH + 20;
  const scale = svgW / (maxTime || 1);

  container.innerHTML = `<svg width="${labelW + svgW}" height="${svgH}" style="display:block;cursor:pointer">` +
    _steps.map((s, i) => {
      const y = i * rowH + pad;
      const x = s.start * scale;
      const w = Math.max(4, ((s.end || maxTime) - s.start) * scale);
      const fill = s.type === 'tool' ? '#4af' : '#fa4';
      const dur = s.end ? (s.end - s.start) + 'ms' : '…';
      const selected = i === _selectedIdx;
      const stroke = selected ? ' stroke="#fff" stroke-width="2"' : '';
      return `<g data-idx="${i}">` +
        `<text x="2" y="${y + 16}" fill="#888" font-size="12" font-family="monospace">${escapeHtml(s.label)}</text>` +
        `<rect x="${labelW + x}" y="${y}" width="${w}" height="${rowH - 8}" fill="${fill}" rx="3" opacity="0.8"${stroke}/>` +
        `<text x="${labelW + x + w + 4}" y="${y + 14}" fill="#666" font-size="11">${dur}</text>` +
        `</g>`;
    }).join('') + '</svg>';

  container.querySelector('svg').addEventListener('click', e => {
    const g = e.target.closest('g[data-idx]');
    if (!g) { clearDetail(); return; }
    const idx = parseInt(g.dataset.idx, 10);
    _selectedIdx = idx;
    renderWaterfall();
    showDetail(_steps[idx]);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function showDetail(step) {
  const panel = document.getElementById('waterfall-detail');
  panel.hidden = false;

  document.getElementById('waterfall-detail-title').textContent = step.label;

  // Timing
  const dur = step.end != null ? (step.end - step.start) + ' ms' : '(running…)';
  const startFmt = step.startAt ? new Date(step.startAt).toLocaleTimeString() : '—';
  const endFmt = step.endAt ? new Date(step.endAt).toLocaleTimeString() : '—';
  document.getElementById('wf-timing').textContent =
    `start: ${startFmt}  end: ${endFmt}  duration: ${dur}`;

  // Tokens
  const inp = step.inputTokens != null ? step.inputTokens : '—';
  const out = step.outputTokens != null ? step.outputTokens : '—';
  document.getElementById('wf-tokens').textContent = `input: ${inp}  output: ${out}`;

  // Args
  document.getElementById('wf-args').textContent =
    step.args != null ? JSON.stringify(step.args, null, 2) : '(no args)';

  // Result
  document.getElementById('wf-result').textContent =
    step.result != null ? step.result : '(no result)';
}

function clearDetail() {
  _selectedIdx = null;
  document.getElementById('waterfall-detail').hidden = true;
  renderWaterfall();
}
```

- [ ] **Step 4: Verify in browser**

Load the dashboard, trigger a turn that makes tool calls, switch to the Waterfall tab. Confirm that clicking a bar shows the detail panel with args, result, timing, and tokens. Clicking another bar swaps the panel content.

If you cannot run the app in this environment, skip and note it.

- [ ] **Step 5: Commit**

```bash
git add src/boukensha/dashboard/static/waterfall.js \
        src/boukensha/dashboard/templates/index.html \
        src/boukensha/dashboard/static/style.css
git commit -m "feat: waterfall step detail panel with args, result, timing, tokens"
```

---

## Task 8: Final Verification and PR Prep

**Files:** No source changes

- [ ] **Step 1: Run full test suite on the feature branch**

```bash
cd /Users/alan.k.wodarski/code-local/ai/claude-code-camp-2026-Q2/week2_capable/agent-exp
.venv/bin/pytest -v
```
Expected: all tests pass

- [ ] **Step 2: Review the diff**

```bash
git log main..HEAD --oneline
git diff main..HEAD --stat
```

Confirm: 5-6 commits, touching only the files listed in the File Map above.

- [ ] **Step 3: Push branch**

```bash
git push -u origin feature/dashboard-tui-enhancements
```

- [ ] **Step 4: Open PR**

Create a PR from `feature/dashboard-tui-enhancements` → `main` with title:

> `feat: waterfall detail panel, map rectangles, movement arrow, kill switch`

Body summary:
- #1 Waterfall: click any step to see full tool args, MUD response, timing, tokens
- #2 Map: rooms are now labeled rectangles instead of circles
- #3 Map: yellow movement arrow shows prev → current room for each tracked character
- #4 TUI: Escape key now actually pauses the agent and prompts continue/stop/redirect
