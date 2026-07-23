# Design: Boukensha Python TUI (Step 11)

**Date:** 2026-07-21  
**Status:** Approved  
**Scope:** `week1_baseline/python/11_tui/`

---

## Goal

Port the Ruby `11_tui` step to Python. Replace the plain `Repl` REPL's `print`/`input` I/O with a structured four-zone terminal UI powered by [Textual](https://github.com/Textualize/textual). The plain REPL remains available via `tui=False`.

---

## Layout

```
┌──────────────────────────────────────────────┐
│  RichLog (scrollable conversation viewport)   │
├──────────────────────────────────────────────┤
│  Label  ⟳ live progress line                 │
├──────────────────────────────────────────────┤
│  boukensha>  Input widget                     │
├──────────────────────────────────────────────┤
│  Label  status bar (always-on)                │
└──────────────────────────────────────────────┘
```

Identical to the Ruby version. All four zones are present at all times (progress line shows idle state when no turn is running).

---

## Architecture

### `boukensha/tui.py` — new file

`Tui` is a `textual.app.App` subclass. It wraps an existing `Repl` instance (same relationship as Ruby).

**Layout widgets:**
- `RichLog` — scrollable conversation viewport (appended to via `write()`)
- `Label` (id `#progress`) — spinner + live progress when agent is running; idle summary when not
- `Input` (id `#input`) — prompt box, always focused
- `Label` (id `#status`) — always-on status bar at bottom

**Spinner:** cycles through `⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏`, driven by a `set_interval(0.06, ...)` timer.

**Agent thread:** `asyncio.get_event_loop().run_in_executor(None, repl.run_turn, input)` — runs the blocking agent call in a thread pool. The Textual event loop stays unblocked. Interrupt (`Escape`) calls `future.cancel()` / raises `Interrupt` in the thread.

**Event bridging:** `Logger.subscribe(callback)` is called by `Tui.__init__`. Each logger event is forwarded to the Textual event loop via `self.call_from_thread(self._handle_event, event)`. This is the equivalent of Ruby's `Queue` + `drain_events`.

**Progress line content (while active):**
```
⠙ Calling tool: read_file  (iter 2/10 · 4s · ↑ 1.2k · ↓ 340 · 3 calls)
```
**Progress line content (idle):**
```
  [ready]   ctx 1.2k   3 turns
```

**Status bar content:**
```
 boukensha v0.1.0 · anthropic (claude-sonnet-5)  ·  ctx 1.2k  ·  5 tools  ·  14:32:01
```
Updated every second by the interval timer.

### `boukensha/repl.py` — modifications

The existing `Repl` class needs three additions (mirrors the Ruby refactor):

1. `on_output(callback)` — registers a callback that receives all output strings. When set, `print()` calls are suppressed and output is routed through the callback instead.
2. `handle_command(text) -> str | None` — extracted from `start()`. Handles `/exit`, `/quit`, `/clear`, `/help`, `/quiet`, `/loud`. Returns `"quit"` on exit commands, `"command"` on other commands, `None` if not a command.
3. `run_turn(text)` — extracted from `start()`. Runs one agent turn; output goes through the `on_output` callback if set.
4. `banner`, `model`, `version`, `context` exposed as public properties.

The existing `start()` method is refactored to call `handle_command()` and `run_turn()` internally.

### `boukensha/logger.py` — modifications

Add `subscribe(callback)` method. Every `_write_log()` call broadcasts the event dict to all registered subscribers, in addition to writing to the JSONL file. This allows `Tui` to receive live `:iteration`, `:tool_call`, `:tool_result`, `:response` events.

### `boukensha/__init__.py` — modifications

`repl()` gains `tui: bool = True`. When `True`, wraps `Repl` in `Tui` and calls `app.run()`. When `False`, calls the existing `repl.start()`. The CLI flag `--no-tui` maps to `tui=False`.

`Tui` is added to `__all__`.

### `pyproject.toml` — modifications

Add `"textual>=0.80"` to `[project.dependencies]`.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Submit input or slash command |
| `Escape` | Interrupt the running agent turn |
| `Ctrl+L` | Clear conversation history |
| `Page Up` / `Page Down` | Scroll conversation viewport |
| `Ctrl+C` / `Ctrl+D` | Quit |

---

## Data Flow

```
User types → Input widget → on_key(Enter) → submit_input()
  ├─ slash command → repl.handle_command() → output callback → RichLog.write()
  └─ plain text → repl.run_turn() in thread pool
                     ├─ agent events → logger.subscribe callback
                     │                  → call_from_thread → _handle_event()
                     │                                         → progress Label update
                     └─ output → on_output callback
                                  → call_from_thread → RichLog.write()
```

---

## Error Handling

- `Escape` during a turn: sets a cancel flag; the background thread sees it via `Interrupt` raised in thread; `[interrupted]` is appended to the conversation.
- `ApiError` / `LoopError` in the background thread: caught, `[error] …` appended to conversation, progress line returns to idle.
- `tui=False` fallback: plain `Repl.start()` as before — no Textual dependency exercised.

---

## Testing

- Unit tests for `Repl` refactor: `test_repl.py` — verify `on_output`, `handle_command`, `run_turn` routing without starting a TUI.
- Unit test for `Logger.subscribe`: verify callback receives events.
- `Tui` itself is not unit-tested (Textual apps require a running event loop; integration testing is manual).
- All step 10 tests continue to pass (no regressions).

---

## Out of Scope

- The `--no-tui` CLI flag on `bin/boukensha` (that executable is managed by step 09; this step only changes `repl()`).
- Markdown rendering inside the `RichLog` (plain text, same as Ruby).
- `Tools::Mud` (not ported in any Python step).
