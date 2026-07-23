# Boukensha Smart Navigation Design

**Date:** 2026-07-23
**Status:** Approved

## Goal

Improve the Boukensha MUD agent's navigation so it:
1. Finds rooms by capability (e.g. "can drink here") not just title
2. Navigates more reliably with loop detection and smarter matching
3. Automatically notices when the player is thirsty or hurt and hints the agent toward the right room — without the user issuing basic survival commands

---

## Problem Summary

### Problem 1 — Navigation failures

`map_path_to` currently matches only on room title substring. Three failure modes:
- **Wrong room** — "Fountain" matches "Fountain of Youth" and "The Fountain Room" equally; first alphabetical wins
- **No path** — directed graph only has edges the agent has physically walked; return paths often missing
- **Loop** — if the model calls `move` in a direction that doesn't advance toward the goal, it can repeat the same sequence indefinitely

### Problem 2 — No room capability awareness

The agent has no way to ask "which rooms allow me to drink/eat/rest/heal?". The room title ("Town Square") gives no hint. The description ("a stone fountain gurgles here") does. Currently, no part of the system reads the description for affordances.

### Problem 3 — No vitals awareness

The agent must explicitly call `check kind=score` and parse the freeform MUD text to know if it's hurt or thirsty. Nothing passively monitors vitals. If the model doesn't think to check, it wanders into danger.

---

## Design

### Component 1 — Vitals tracking (`src/boukensha/tools/vitals.py`)

A new module with two responsibilities:

**Passive phrase detection** — scan every MUD socket response for known status phrases: "You are thirsty", "You are hungry", "You feel weak", etc. Update a `PlayerVitals` dataclass holding boolean flags (`is_thirsty`, `is_hungry`, `is_hurt`) plus last-seen HP/mana fractions when parseable.

**Score response parsing** — when a response looks like a `score` reply (contains "Hit Points" or "HP:"), extract the numeric values with regex and update the same `PlayerVitals`. This gives precise fractional values.

`PlayerVitals` is a simple frozen-after-update dataclass. `VitalsTracker` wraps it with a `update(response: str) -> None` method and a `hint() -> str | None` property that returns a one-line action hint when a threshold is crossed (`None` when vitals are fine).

**Thresholds:**
- Thirsty flag or no HP data yet → no hint for thirst (passive phrase only)
- `is_thirsty=True` → hint: `"[vitals] You are thirsty — find a room with can_drink capability"`
- `is_hungry=True` → hint: `"[vitals] You are hungry — find a room with can_eat capability"`
- HP fraction ≤ 0.40 → hint: `"[vitals] Low HP ({pct}%) — find a room with can_rest capability and rest"`

Only one hint at a time, priority order: HP → thirst → hunger.

### Component 2 — Room capability tagging (`src/boukensha/tools/map.py` changes)

**Affordance inference** — on every `observe()` call, scan the room description + title for keyword groups and tag the node:

| Affordance tag | Keywords |
|---|---|
| `can_drink` | fountain, well, spring, pool, brook, stream, water, pitcher, tap, cistern |
| `can_eat` | bakery, tavern, inn, kitchen, food, meal, feast, bread, vendor, market |
| `can_rest` | inn, tavern, safe, peaceful, quiet, sanctuary, temple, chapel |
| `can_heal` | temple, chapel, shrine, healer, cleric, priest, medic |

Tags are stored as a list on the node: `affordances: list[str]`. Inferred on first visit; can be promoted to `confirmed` later (Task 4).

**New `map_find_capability(capability)` tool** — returns the shortest path to any room tagged with the given affordance. Returns all matching rooms sorted by hop count. If multiple rooms tie for closest, return all. Format: `"Nearest can_drink room: 'Town Square' — north → east (2 hops)"`.

**Improved `map_path_to`** — add loop detection: track visited nodes during the path walk; if `_current` appears in path computation (walk would revisit a node we started from), flag it. Also expand candidate matching to include affordance tags as a fallback: if no title match, check if `destination` matches a known affordance tag (e.g. "fountain" → `can_drink`).

**Loop detection in description** — `map_here` gains a `_navigation_history: deque[str]` (last 6 room keys). If the same key appears 3+ times in the last 6 moves, append a warning: `"[navigation warning] Possible loop detected — you have visited this room 3 times recently."` This appears in the `map_here` tool result, visible to the model.

### Component 3 — Vitals hint injection (`src/boukensha/agent.py` change)

After each tool result is appended to context (in `_handle_tool_calls`), call `vitals_tracker.update(result)`. After all tool calls in the batch are processed, call `vitals_tracker.hint()`. If non-None, append it as an additional `tool_result` message with a synthetic tool_use_id so the model sees it in context naturally.

`VitalsTracker` is passed into `Agent.__init__` as an optional parameter (`vitals: VitalsTracker | None = None`). When `None`, the feature is a no-op. This keeps backward compatibility with all existing tests.

### Component 4 — Affordance confirmation (mud.py `_observe` hook)

When the agent successfully drinks (`drink`, `quaff`) or eats (`eat`) in a room, confirm `can_drink`/`can_eat` on that node. This is done by patching the result-passthrough in `_observe`: if `cmd` is in `{"drink", "quaff"}` and the result does NOT contain "can't" or "nothing to drink", call `graph.confirm_affordance(_current, "can_drink")`.

`confirm_affordance(node_key, tag)` promotes the tag from `inferred` to `confirmed` in node data: `affordances_confirmed: list[str]`.

### Updated system prompt (`prompts/system.md`)

Add guidance for the new tools and vitals hints:

```
Navigation memory: a persistent room map is maintained automatically as you move.
- map_here: current room, exits (mapped/unexplored), loop warning if stuck
- map_path_to(dest): shortest path to a named room; also accepts capability names like "fountain" or "bakery"
- map_find_capability(capability): find nearest room where you can drink / eat / rest / heal
- map_summary: full overview of known world

Vitals: [vitals] hints appear automatically when HP is low or you are thirsty/hungry. Act on them immediately — navigate to the suggested capability room before doing anything else.
```

---

## Data structures

```python
# vitals.py
@dataclass
class PlayerVitals:
    is_thirsty: bool = False
    is_hungry: bool = False
    hp_current: int | None = None
    hp_max: int | None = None

    @property
    def hp_fraction(self) -> float | None:
        if self.hp_current is None or self.hp_max is None or self.hp_max == 0:
            return None
        return self.hp_current / self.hp_max
```

```python
# map.py node attributes (additions)
{
    "title": str,
    "description": str,
    "exits": list[str],
    "affordances": list[str],           # inferred tags
    "affordances_confirmed": list[str], # confirmed by successful action
}
```

---

## What this does NOT do

- No autonomous action execution — the agent still decides every move
- No full MUD score parser (too MUD-specific; phrase detection is sufficient)
- No pathfinding for rooms not yet visited (can't route to unknown rooms)
- No multi-hop navigation executor ("go to fountain in 3 steps automatically") — the model follows the directions

---

## Files touched

| File | Change |
|---|---|
| `src/boukensha/tools/vitals.py` | **New** — `PlayerVitals`, `VitalsTracker` |
| `src/boukensha/tools/map.py` | **Modify** — affordance tagging, `map_find_capability`, improved `map_path_to`, loop detection |
| `src/boukensha/tools/mud.py` | **Modify** — pass `vitals_tracker` into `_observe`; affordance confirmation on drink/eat |
| `src/boukensha/agent.py` | **Modify** — accept optional `VitalsTracker`; inject hints after tool calls |
| `prompts/system.md` | **Modify** — update navigation + vitals guidance |
| `tests/test_vitals.py` | **New** — unit tests for `VitalsTracker` |
| `tests/test_tools_map.py` | **Modify** — tests for affordance tagging, `map_find_capability`, loop detection |
| `tests/test_agent.py` | **Modify** — test hint injection |
