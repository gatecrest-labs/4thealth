# Boukensha Smart Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add vitals tracking, room capability tagging, smarter navigation, and automatic hint injection so the Boukensha agent handles thirst/hunger/healing without explicit user commands.

**Architecture:** Three new capabilities wired together: (1) `VitalsTracker` parses every MUD response for health/thirst/hunger state; (2) `RoomGraph` tags rooms with affordances (can_drink, can_eat, can_rest, can_heal) on first visit and confirms them on successful action; (3) `Agent` injects a one-line vitals hint into context after each tool batch when thresholds are crossed. Navigation also gains loop detection and capability-based room lookup.

**Tech Stack:** Python 3.11+, networkx (already a dependency), dataclasses (stdlib), re (stdlib), collections.deque (stdlib)

## Global Constraints

- Python ≥ 3.11; no new third-party dependencies
- All tests: `cd week1_baseline/python/13_memory && uv run pytest tests/ -v`
- Working directory for all commands: `/Users/alan.k.wodarski/code-local/ai/claude-code-camp-2026-Q2/week1_baseline/python/13_memory`
- Follow existing code style: `from __future__ import annotations`, dataclasses, no type: ignore except on known stubs
- Do not break any existing tests

---

### Task 1: VitalsTracker — passive phrase detection and score parsing

**Files:**
- Create: `src/boukensha/tools/vitals.py`
- Create: `tests/test_vitals.py`

**Interfaces:**
- Produces:
  - `class PlayerVitals` — dataclass with fields `is_thirsty: bool`, `is_hungry: bool`, `hp_current: int | None`, `hp_max: int | None`, property `hp_fraction: float | None`
  - `class VitalsTracker` — `update(response: str) -> None`, property `hint: str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vitals.py`:

```python
"""Tests for VitalsTracker."""
from __future__ import annotations
import pytest
from boukensha.tools.vitals import PlayerVitals, VitalsTracker


def test_initial_state_is_fine():
    vt = VitalsTracker()
    assert vt.hint is None


def test_detects_thirst_phrase():
    vt = VitalsTracker()
    vt.update("You are thirsty.\n> ")
    assert vt._vitals.is_thirsty is True


def test_detects_hunger_phrase():
    vt = VitalsTracker()
    vt.update("You are hungry.\n> ")
    assert vt._vitals.is_hungry is True


def test_clears_thirst_on_drink_response():
    vt = VitalsTracker()
    vt.update("You are thirsty.\n> ")
    vt.update("You drink the water.  You don't feel thirsty anymore.\n> ")
    assert vt._vitals.is_thirsty is False


def test_clears_hunger_on_eat_response():
    vt = VitalsTracker()
    vt.update("You are hungry.\n> ")
    vt.update("You eat the bread.  You are full.\n> ")
    assert vt._vitals.is_hungry is False


def test_parses_hp_from_score():
    vt = VitalsTracker()
    score_response = "Hit Points: 45/120\nMana: 80/100\n> "
    vt.update(score_response)
    assert vt._vitals.hp_current == 45
    assert vt._vitals.hp_max == 120


def test_parses_hp_colon_format():
    vt = VitalsTracker()
    vt.update("HP: 10/200  Mana: 50/100\n> ")
    assert vt._vitals.hp_current == 10
    assert vt._vitals.hp_max == 200


def test_hint_none_when_healthy():
    vt = VitalsTracker()
    vt.update("HP: 100/100  Mana: 100/100\n> ")
    assert vt.hint is None


def test_hint_low_hp():
    vt = VitalsTracker()
    vt.update("HP: 40/100  Mana: 50/100\n> ")
    assert vt.hint is not None
    assert "can_rest" in vt.hint
    assert "40%" in vt.hint


def test_hint_thirst():
    vt = VitalsTracker()
    vt.update("You are thirsty.\n> ")
    assert vt.hint is not None
    assert "can_drink" in vt.hint


def test_hint_hunger():
    vt = VitalsTracker()
    vt.update("You are hungry.\n> ")
    assert vt.hint is not None
    assert "can_eat" in vt.hint


def test_hint_hp_takes_priority_over_thirst():
    vt = VitalsTracker()
    vt.update("You are thirsty.\n> ")
    vt.update("HP: 30/100\n> ")
    assert "can_rest" in vt.hint


def test_hp_fraction_none_when_no_data():
    v = PlayerVitals()
    assert v.hp_fraction is None


def test_hp_fraction_calculated():
    v = PlayerVitals(hp_current=50, hp_max=100)
    assert v.hp_fraction == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_vitals.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `vitals.py` does not exist yet.

- [ ] **Step 3: Implement `src/boukensha/tools/vitals.py`**

```python
"""Player vitals tracking — passive phrase detection + score parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Phrases that set flags
_THIRSTY_SET   = re.compile(r"you are thirsty", re.IGNORECASE)
_HUNGRY_SET    = re.compile(r"you are hungry", re.IGNORECASE)
_THIRSTY_CLEAR = re.compile(r"don.t feel thirsty|no longer thirsty|quench", re.IGNORECASE)
_HUNGRY_CLEAR  = re.compile(r"you are full|no longer hungry|satiat", re.IGNORECASE)

# Score formats: "Hit Points: 45/120" or "HP: 45/120"
_HP_RE = re.compile(r"(?:hit points|hp)\s*:\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)

_HP_THRESHOLD = 0.40  # hint when HP ≤ 40%


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


class VitalsTracker:
    def __init__(self) -> None:
        self._vitals = PlayerVitals()

    def update(self, response: str) -> None:
        if _THIRSTY_CLEAR.search(response):
            self._vitals.is_thirsty = False
        elif _THIRSTY_SET.search(response):
            self._vitals.is_thirsty = True

        if _HUNGRY_CLEAR.search(response):
            self._vitals.is_hungry = False
        elif _HUNGRY_SET.search(response):
            self._vitals.is_hungry = True

        m = _HP_RE.search(response)
        if m:
            self._vitals.hp_current = int(m.group(1))
            self._vitals.hp_max = int(m.group(2))

    @property
    def hint(self) -> str | None:
        frac = self._vitals.hp_fraction
        if frac is not None and frac <= _HP_THRESHOLD:
            pct = round(frac * 100)
            return f"[vitals] Low HP ({pct}%) — find a room with can_rest capability and rest"
        if self._vitals.is_thirsty:
            return "[vitals] You are thirsty — find a room with can_drink capability"
        if self._vitals.is_hungry:
            return "[vitals] You are hungry — find a room with can_eat capability"
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_vitals.py -v
```
Expected: all 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/boukensha/tools/vitals.py tests/test_vitals.py
git commit -m "feat: add VitalsTracker for passive HP/thirst/hunger detection"
```

---

### Task 2: Room affordance tagging in RoomGraph

**Files:**
- Modify: `src/boukensha/tools/map.py`
- Modify: `tests/test_tools_map.py`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `RoomGraph.observe()` now tags each node with `affordances: list[str]` and `affordances_confirmed: list[str]`
  - `RoomGraph.confirm_affordance(node_key: str, tag: str) -> None`
  - `RoomGraph.rooms_with_affordance(tag: str) -> list[str]` — returns list of node keys

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_map.py`:

```python
# ---------------------------------------------------------------------------
# Affordance tagging
# ---------------------------------------------------------------------------

LOOK_FOUNTAIN_ROOM = """\
The Town Square
A wide cobblestone plaza.  A stone fountain gurgles in the center.
Obvious exits: north, east, south
"""

LOOK_BAKERY_ROOM = """\
The Bakery
The smell of fresh bread fills the air.  A vendor sells loaves here.
Obvious exits: west
"""

LOOK_TEMPLE_ROOM = """\
The Temple of Healing
A cleric tends to the wounded at the shrine.
Obvious exits: south
"""

LOOK_PLAIN_ROOM = """\
A Dark Corridor
Damp stone walls.  Nothing of note here.
Obvious exits: north, south
"""


def test_affordance_can_drink_inferred_from_description(graph: RoomGraph):
    graph.observe(LOOK_FOUNTAIN_ROOM, "look")
    node_data = graph._graph.nodes[graph._current]
    assert "can_drink" in node_data.get("affordances", [])


def test_affordance_can_eat_inferred_from_description(graph: RoomGraph):
    graph.observe(LOOK_BAKERY_ROOM, "look")
    node_data = graph._graph.nodes[graph._current]
    assert "can_eat" in node_data.get("affordances", [])


def test_affordance_can_heal_inferred_from_description(graph: RoomGraph):
    graph.observe(LOOK_TEMPLE_ROOM, "look")
    node_data = graph._graph.nodes[graph._current]
    assert "can_heal" in node_data.get("affordances", [])


def test_affordance_can_rest_inferred_from_description(graph: RoomGraph):
    graph.observe(LOOK_TEMPLE_ROOM, "look")
    node_data = graph._graph.nodes[graph._current]
    assert "can_rest" in node_data.get("affordances", [])


def test_no_affordance_on_plain_room(graph: RoomGraph):
    graph.observe(LOOK_PLAIN_ROOM, "look")
    node_data = graph._graph.nodes[graph._current]
    assert node_data.get("affordances", []) == []


def test_rooms_with_affordance_returns_matching_keys(graph: RoomGraph):
    graph.observe(LOOK_FOUNTAIN_ROOM, "look")
    fountain_key = graph._current
    graph.observe(LOOK_PLAIN_ROOM, "north")
    results = graph.rooms_with_affordance("can_drink")
    assert fountain_key in results
    assert graph._current not in results


def test_confirm_affordance_adds_to_confirmed(graph: RoomGraph):
    graph.observe(LOOK_FOUNTAIN_ROOM, "look")
    key = graph._current
    graph.confirm_affordance(key, "can_drink")
    node_data = graph._graph.nodes[key]
    assert "can_drink" in node_data.get("affordances_confirmed", [])


def test_confirm_affordance_also_ensures_inferred(graph: RoomGraph):
    graph.observe(LOOK_PLAIN_ROOM, "look")
    key = graph._current
    graph.confirm_affordance(key, "can_drink")
    node_data = graph._graph.nodes[key]
    assert "can_drink" in node_data.get("affordances", [])


def test_affordances_survive_round_trip(tmp_save: Path):
    g1 = RoomGraph(tmp_save)
    g1.observe(LOOK_FOUNTAIN_ROOM, "look")
    g2 = RoomGraph(tmp_save)
    node_data = g2._graph.nodes[g2._current]
    assert "can_drink" in node_data.get("affordances", [])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_map.py -v -k "affordance"
```
Expected: FAIL — `rooms_with_affordance` and `confirm_affordance` do not exist yet.

- [ ] **Step 3: Add affordance inference to `map.py`**

Add these constants near the top of `src/boukensha/tools/map.py` (after the `_ANSI_RE` line):

```python
# Affordance keyword sets — matched against title + description (case-insensitive)
_AFFORDANCE_KEYWORDS: dict[str, list[str]] = {
    "can_drink": [
        "fountain", "well", "spring", "pool", "brook", "stream",
        "water", "pitcher", "tap", "cistern",
    ],
    "can_eat": [
        "bakery", "tavern", "inn", "kitchen", "food", "meal",
        "feast", "bread", "vendor", "market",
    ],
    "can_rest": [
        "inn", "tavern", "safe", "peaceful", "quiet",
        "sanctuary", "temple", "chapel",
    ],
    "can_heal": [
        "temple", "chapel", "shrine", "healer", "cleric", "priest", "medic",
    ],
}


def _infer_affordances(title: str, description: str) -> list[str]:
    text = (title + " " + description).lower()
    return [
        tag
        for tag, keywords in _AFFORDANCE_KEYWORDS.items()
        if any(kw in text for kw in keywords)
    ]
```

In `RoomGraph.observe()`, replace the block that adds/updates the node:

```python
        affordances = _infer_affordances(title, description)
        if not self._graph.has_node(key):
            self._graph.add_node(
                key,
                title=title,
                description=description,
                exits=exits,
                affordances=affordances,
                affordances_confirmed=[],
            )
        else:
            self._graph.nodes[key]["exits"] = exits
            # Merge any newly inferred affordances (don't drop confirmed ones)
            existing = self._graph.nodes[key].get("affordances", [])
            merged = list(dict.fromkeys(existing + affordances))
            self._graph.nodes[key]["affordances"] = merged
```

Add two new methods to `RoomGraph` (after `map_summary`):

```python
    def rooms_with_affordance(self, tag: str) -> list[str]:
        """Return node keys for all rooms tagged with the given affordance."""
        return [
            n for n, d in self._graph.nodes(data=True)
            if tag in d.get("affordances", []) or tag in d.get("affordances_confirmed", [])
        ]

    def confirm_affordance(self, node_key: str, tag: str) -> None:
        """Mark an affordance as confirmed (successful action) on a node."""
        if not self._graph.has_node(node_key):
            return
        node = self._graph.nodes[node_key]
        # Ensure inferred list also has it
        inferred = node.get("affordances", [])
        if tag not in inferred:
            node["affordances"] = inferred + [tag]
        confirmed = node.get("affordances_confirmed", [])
        if tag not in confirmed:
            node["affordances_confirmed"] = confirmed + [tag]
        self._save()
```

Also update `_save` to include affordances in node data — the current `_save` uses `**d` which already captures all node attributes, so no change needed there. Verify `_load` also uses `**node` which likewise works.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools_map.py -v
```
Expected: all existing + new affordance tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/boukensha/tools/map.py tests/test_tools_map.py
git commit -m "feat: tag rooms with affordances (can_drink/eat/rest/heal) on observe"
```

---

### Task 3: `map_find_capability` tool + improved `map_path_to` + loop detection

**Files:**
- Modify: `src/boukensha/tools/map.py`
- Modify: `tests/test_tools_map.py`

**Interfaces:**
- Consumes: `RoomGraph.rooms_with_affordance(tag)` from Task 2
- Produces:
  - `RoomGraph.map_find_capability(capability: str) -> str`
  - `RoomGraph.map_here()` — now includes loop warning
  - `RoomGraph.map_path_to()` — now falls back to capability search; title match is exact-first then substring
  - New tool registered: `map_find_capability`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_map.py`:

```python
# ---------------------------------------------------------------------------
# map_find_capability
# ---------------------------------------------------------------------------

def test_map_find_capability_no_current(graph: RoomGraph):
    result = graph.map_find_capability("can_drink")
    assert "unknown" in result.lower()


def test_map_find_capability_no_matching_rooms(graph: RoomGraph):
    graph.observe(LOOK_PLAIN_ROOM, "look")
    result = graph.map_find_capability("can_drink")
    assert "no known" in result.lower()


def test_map_find_capability_already_here(graph: RoomGraph):
    graph.observe(LOOK_FOUNTAIN_ROOM, "look")
    result = graph.map_find_capability("can_drink")
    assert "already" in result.lower()


def test_map_find_capability_finds_nearest(graph: RoomGraph):
    graph.observe(LOOK_PLAIN_ROOM, "look")          # start: plain
    graph.observe(LOOK_FOUNTAIN_ROOM, "north")      # north → fountain
    graph.observe(LOOK_PLAIN_ROOM, "south")         # back to plain
    result = graph.map_find_capability("can_drink")
    assert "north" in result
    assert "can_drink" in result or "fountain" in result.lower()


def test_map_find_capability_unreachable(graph: RoomGraph):
    graph.observe(LOOK_PLAIN_ROOM, "look")
    key_plain = graph._current
    graph._current = None
    graph.observe(LOOK_FOUNTAIN_ROOM, "look")   # island node
    graph._current = key_plain
    result = graph.map_find_capability("can_drink")
    assert "no navigable" in result.lower() or "no known" in result.lower()


# ---------------------------------------------------------------------------
# map_path_to — capability fallback
# ---------------------------------------------------------------------------

def test_map_path_to_falls_back_to_capability(graph: RoomGraph):
    graph.observe(LOOK_PLAIN_ROOM, "look")
    graph.observe(LOOK_FOUNTAIN_ROOM, "north")
    graph.observe(LOOK_PLAIN_ROOM, "south")
    # "fountain" matches no room title but IS a can_drink keyword
    result = graph.map_path_to("fountain")
    assert "north" in result


# ---------------------------------------------------------------------------
# Loop detection in map_here
# ---------------------------------------------------------------------------

def test_map_here_no_loop_warning_normally(graph: RoomGraph):
    graph.observe(LOOK_ROOM_A, "look")
    graph.observe(LOOK_ROOM_B, "north")
    result = graph.map_here()
    assert "loop" not in result.lower()


def test_map_here_warns_on_loop(graph: RoomGraph):
    # Visit same room 3 times in last 6 moves
    graph.observe(LOOK_ROOM_A, "look")
    graph.observe(LOOK_ROOM_B, "north")
    graph.observe(LOOK_ROOM_A, "south")
    graph.observe(LOOK_ROOM_B, "north")
    graph.observe(LOOK_ROOM_A, "south")
    result = graph.map_here()
    assert "loop" in result.lower()


# ---------------------------------------------------------------------------
# Map.register — now 4 tools
# ---------------------------------------------------------------------------

def test_map_register_registers_four_tools(tmp_save: Path):
    registry = MagicMock()
    Map.register(registry, save_path=tmp_save)
    assert registry.tool.call_count == 4
    names = {call.args[0] for call in registry.tool.call_args_list}
    assert "map_find_capability" in names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_map.py -v -k "capability or loop or four_tools"
```
Expected: FAIL — `map_find_capability` does not exist, loop detection not wired.

- [ ] **Step 3: Add loop detection to `RoomGraph.__init__`**

Add import at top of `map.py`:
```python
from collections import deque
```

Add to `RoomGraph.__init__` (after `self._load()`):
```python
        self._visit_history: deque[str] = deque(maxlen=6)
```

In `RoomGraph.observe()`, after `self._current = key`, add:
```python
        self._visit_history.append(key)
```

- [ ] **Step 4: Update `map_here` to include loop warning**

Replace the `map_here` method body in `src/boukensha/tools/map.py`:

```python
    def map_here(self) -> str:
        if self._current is None or not self._graph.has_node(self._current):
            return "No location recorded yet — try 'look' first."
        data = self._graph.nodes[self._current]
        title = data.get("title", self._current)
        all_exits = data.get("exits", [])
        mapped = {
            d["direction"]
            for _, _, d in self._graph.out_edges(self._current, data=True)
        }
        affordances = data.get("affordances", []) + data.get("affordances_confirmed", [])
        lines = [f"You are in: {title}"]
        if affordances:
            lines.append("Capabilities: " + ", ".join(dict.fromkeys(affordances)))
        if all_exits:
            exit_parts = []
            for e in all_exits:
                tag = " [mapped]" if e in mapped else " [unexplored]"
                exit_parts.append(e + tag)
            lines.append("Exits: " + ", ".join(exit_parts))
        else:
            lines.append("No obvious exits.")
        lines.append(f"Known rooms: {self._graph.number_of_nodes()}")
        # Loop detection: warn if current room appeared 3+ times in last 6 visits
        if self._visit_history.count(self._current) >= 3:
            lines.append(
                "[navigation warning] Possible loop detected — you have visited this room "
                f"{self._visit_history.count(self._current)} times recently."
            )
        return "\n".join(lines)
```

- [ ] **Step 5: Add `map_find_capability` method**

Add after `map_summary` in `RoomGraph`:

```python
    def map_find_capability(self, capability: str) -> str:
        """Return shortest path to nearest room tagged with capability."""
        if self._current is None:
            return "Current location unknown — try 'look' first."
        candidates = self.rooms_with_affordance(capability)
        if not candidates:
            return f"No known rooms with '{capability}' capability in the map."
        best_directions: list[str] | None = None
        best_title = ""
        for target in candidates:
            if target == self._current:
                data = self._graph.nodes[target]
                return f"You are already in a room with {capability}: '{data.get('title', target)}'."
            try:
                path = nx.shortest_path(self._graph, self._current, target)
            except nx.NetworkXNoPath:
                continue
            directions = [
                self._graph.edges[a, b].get("direction", "?")
                for a, b in zip(path, path[1:])
            ]
            if best_directions is None or len(directions) < len(best_directions):
                best_directions = directions
                best_title = self._graph.nodes[target].get("title", target)
        if best_directions is None:
            return f"No navigable path to any {capability} room from current location."
        hops = len(best_directions)
        return (
            f"Nearest {capability} room: '{best_title}' — "
            f"{' → '.join(best_directions)} ({hops} hop{'s' if hops != 1 else ''})"
        )
```

- [ ] **Step 6: Update `map_path_to` to fall back to capability search**

Replace `map_path_to` in `RoomGraph`:

```python
    def map_path_to(self, destination: str) -> str:
        if self._current is None:
            return "Current location unknown — try 'look' first."
        dest_lower = destination.lower()
        # Title match: exact first, then substring
        exact = [
            n for n, d in self._graph.nodes(data=True)
            if dest_lower == d.get("title", "").lower()
        ]
        substring = [
            n for n, d in self._graph.nodes(data=True)
            if dest_lower in d.get("title", "").lower()
        ]
        candidates = exact or substring
        # Capability fallback: if no title match, check if destination is a capability keyword
        if not candidates:
            # Check all affordance keyword lists for a match
            for tag, keywords in _AFFORDANCE_KEYWORDS.items():
                if dest_lower in keywords or dest_lower == tag:
                    return self.map_find_capability(tag)
            return f"No room matching '{destination}' in the map."
        best_directions: list[str] | None = None
        best_title = ""
        for target in candidates:
            if target == self._current:
                return f"You are already in '{self._graph.nodes[target]['title']}'."
            try:
                path = nx.shortest_path(self._graph, self._current, target)
            except nx.NetworkXNoPath:
                continue
            directions = [
                self._graph.edges[a, b].get("direction", "?")
                for a, b in zip(path, path[1:])
            ]
            if best_directions is None or len(directions) < len(best_directions):
                best_directions = directions
                best_title = self._graph.nodes[target].get("title", target)
        if best_directions is None:
            return f"No navigable path to '{destination}' from current location."
        return f"Path to '{best_title}': {' → '.join(best_directions)}"
```

- [ ] **Step 7: Register `map_find_capability` tool in `Map.register`**

In `Map.register`, after the `map_summary` tool registration block, add:

```python
        registry.tool(
            "map_find_capability",
            description=(
                "Find the nearest room where you can perform a specific action. "
                "Use capability='can_drink' when thirsty, 'can_eat' when hungry, "
                "'can_rest' to recover HP/mana, 'can_heal' for a healer. "
                "Returns the direction sequence to get there."
            ),
            parameters={
                "capability": {
                    "type": "string",
                    "description": "can_drink | can_eat | can_rest | can_heal",
                },
            },
            block=lambda capability, **_: graph.map_find_capability(capability),
        )
```

Also update the `test_map_register_registers_three_tools` test name — replace `three` with `four` and update the assertion to `== 4`. The new test `test_map_register_registers_four_tools` already covers this; update the old test too:

In `tests/test_tools_map.py`, change:
```python
def test_map_register_registers_three_tools(tmp_save: Path):
    registry = MagicMock()
    Map.register(registry, save_path=tmp_save)
    assert registry.tool.call_count == 3
    names = {call.args[0] for call in registry.tool.call_args_list}
    assert names == {"map_here", "map_path_to", "map_summary"}
```
to:
```python
def test_map_register_registers_four_tools_complete(tmp_save: Path):
    registry = MagicMock()
    Map.register(registry, save_path=tmp_save)
    assert registry.tool.call_count == 4
    names = {call.args[0] for call in registry.tool.call_args_list}
    assert names == {"map_here", "map_path_to", "map_summary", "map_find_capability"}
```

- [ ] **Step 8: Run all map tests**

```bash
uv run pytest tests/test_tools_map.py -v
```
Expected: all tests PASS (including the renamed one).

- [ ] **Step 9: Commit**

```bash
git add src/boukensha/tools/map.py tests/test_tools_map.py
git commit -m "feat: add map_find_capability, loop detection, and capability fallback in map_path_to"
```

---

### Task 4: Affordance confirmation on drink/eat actions in mud.py

**Files:**
- Modify: `src/boukensha/tools/mud.py`
- Modify: `tests/test_tools_mud.py`

**Interfaces:**
- Consumes: `RoomGraph.confirm_affordance(node_key, tag)` from Task 2; `RoomGraph._current` (existing)
- Produces: `_observe()` now accepts optional `confirm_tag: str | None` parameter and calls `confirm_affordance` on success

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools_mud.py`:

```python
# ---------------------------------------------------------------------------
# Affordance confirmation
# ---------------------------------------------------------------------------

def test_observe_confirms_can_drink_on_successful_drink(tmp_path):
    from boukensha.tools.map import RoomGraph
    from boukensha.tools.mud import _observe

    save_path = tmp_path / "map.json"
    graph = RoomGraph(save_path)

    look_response = (
        "The Town Square\n"
        "A fountain gurgles here.\n"
        "Obvious exits: north\n"
    )
    graph.observe(look_response, "look")
    key = graph._current

    drink_response = "You drink the water.  You don't feel thirsty anymore.\n> "
    _observe(graph, drink_response, "drink")

    node = graph._graph.nodes[key]
    assert "can_drink" in node.get("affordances_confirmed", [])


def test_observe_does_not_confirm_on_failed_drink(tmp_path):
    from boukensha.tools.map import RoomGraph
    from boukensha.tools.mud import _observe

    save_path = tmp_path / "map.json"
    graph = RoomGraph(save_path)

    look_response = (
        "A Dark Corridor\n"
        "Nothing here.\n"
        "Obvious exits: north\n"
    )
    graph.observe(look_response, "look")
    key = graph._current

    fail_response = "There is nothing to drink here.\n> "
    _observe(graph, fail_response, "drink")

    node = graph._graph.nodes[key]
    assert "can_drink" not in node.get("affordances_confirmed", [])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tools_mud.py -v -k "confirm"
```
Expected: FAIL — `_observe` does not call `confirm_affordance`.

- [ ] **Step 3: Update `_observe` in `mud.py`**

Replace the existing `_observe` function:

```python
# Commands that trigger affordance confirmation
_DRINK_CMDS = {"drink", "quaff"}
_EAT_CMDS   = {"eat"}
_DRINK_FAIL = re.compile(r"nothing to drink|can't drink|you can't", re.IGNORECASE)
_EAT_FAIL   = re.compile(r"nothing to eat|can't eat|you can't", re.IGNORECASE)


def _observe(graph: "RoomGraph | None", result: str, cmd: str | None) -> str:
    """Call graph.observe() if a graph is attached, then pass result through."""
    if graph is not None:
        graph.observe(result, cmd)
        if cmd is not None and graph._current is not None:
            cmd_lower = cmd.strip().lower()
            if cmd_lower in _DRINK_CMDS and not _DRINK_FAIL.search(result):
                graph.confirm_affordance(graph._current, "can_drink")
            elif cmd_lower in _EAT_CMDS and not _EAT_FAIL.search(result):
                graph.confirm_affordance(graph._current, "can_eat")
    return result
```

Also add `import re` to `mud.py` if not already present (check top of file — it likely is not since mud.py currently has no `re` import).

Check:
```bash
head -20 src/boukensha/tools/mud.py
```
If `import re` is missing, add it after the existing stdlib imports.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_mud.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/boukensha/tools/mud.py tests/test_tools_mud.py
git commit -m "feat: confirm affordances on successful drink/eat actions"
```

---

### Task 5: Vitals hint injection in Agent

**Files:**
- Modify: `src/boukensha/agent.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Consumes: `VitalsTracker` from Task 1 — `update(response: str)`, property `hint: str | None`
- Produces: `Agent.__init__` accepts `vitals: VitalsTracker | None = None`; after each tool batch, hint (if any) is appended as a `tool_result` message

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent.py`. First check the existing `make_agent` helper signature by reading the top of `tests/test_agent.py`:

The new test goes after existing tests:

```python
# ---------------------------------------------------------------------------
# Vitals hint injection
# ---------------------------------------------------------------------------

def test_agent_injects_vitals_hint_after_tool_call(make_agent, make_builder):
    from boukensha.tools.vitals import VitalsTracker
    from unittest.mock import patch

    vt = VitalsTracker()
    # Pre-load thirsty state
    vt.update("You are thirsty.\n> ")

    agent = make_agent(vitals=vt)

    # Make the fake client return one tool call then stop
    tool_response = fake_response(
        content=[{"type": "tool_use", "id": "t1", "name": "look", "input": {}}],
        stop_reason="tool_use",
    )
    text_response = fake_response(
        content=[{"type": "text", "text": "done"}],
        stop_reason="end_turn",
    )
    agent._client.call.side_effect = [tool_response, text_response]
    agent._registry.dispatch = lambda name, args: "You are in the square."

    agent.run()

    # Find tool_result messages — one for the look result, one for the vitals hint
    tool_results = [
        m for m in agent._context.messages
        if getattr(m, "role", None) == "tool_result"
    ]
    hint_results = [
        m for m in tool_results
        if "can_drink" in str(getattr(m, "content", ""))
    ]
    assert len(hint_results) == 1


def test_agent_no_hint_when_vitals_healthy(make_agent):
    from boukensha.tools.vitals import VitalsTracker

    vt = VitalsTracker()
    # No thirst, no hunger, no HP data → no hint
    agent = make_agent(vitals=vt)

    tool_response = fake_response(
        content=[{"type": "tool_use", "id": "t2", "name": "look", "input": {}}],
        stop_reason="tool_use",
    )
    text_response = fake_response(
        content=[{"type": "text", "text": "done"}],
        stop_reason="end_turn",
    )
    agent._client.call.side_effect = [tool_response, text_response]
    agent._registry.dispatch = lambda name, args: "You see nothing special."

    agent.run()

    tool_results = [
        m for m in agent._context.messages
        if getattr(m, "role", None) == "tool_result"
    ]
    hint_results = [
        m for m in tool_results
        if "[vitals]" in str(getattr(m, "content", ""))
    ]
    assert len(hint_results) == 0


def test_agent_no_vitals_tracker_is_noop(make_agent):
    agent = make_agent()   # no vitals kwarg → None
    tool_response = fake_response(
        content=[{"type": "tool_use", "id": "t3", "name": "look", "input": {}}],
        stop_reason="tool_use",
    )
    text_response = fake_response(
        content=[{"type": "text", "text": "done"}],
        stop_reason="end_turn",
    )
    agent._client.call.side_effect = [tool_response, text_response]
    agent._registry.dispatch = lambda name, args: "ok"
    result = agent.run()   # must not raise
    assert result == "done"
```

You will need to check what `make_agent` and `fake_response` look like in the existing test file to match the pattern exactly. Read `tests/test_agent.py` lines 1-60 first. The `make_agent` fixture must accept a `vitals` kwarg and pass it through to `Agent.__init__`.

- [ ] **Step 2: Read existing test helpers**

```bash
head -80 tests/test_agent.py
```

Update `make_agent` fixture (or helper function) to accept and pass `vitals`:

If the existing fixture is:
```python
def make_agent(**kwargs):
    return Agent(context=..., registry=..., builder=..., client=..., **kwargs)
```
it will already forward `vitals` once `Agent.__init__` accepts it. If it's a fixed-argument function, add `vitals=None` and pass it through.

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/test_agent.py -v -k "vitals"
```
Expected: FAIL — `Agent.__init__` does not accept `vitals`.

- [ ] **Step 4: Update `Agent.__init__` to accept `VitalsTracker`**

Add import at top of `src/boukensha/agent.py`:
```python
from typing import TYPE_CHECKING, Any
```
(already present — just add the TYPE_CHECKING import for VitalsTracker)

Add to the `if TYPE_CHECKING:` block:
```python
    from .tools.vitals import VitalsTracker
```

Add `vitals` parameter to `Agent.__init__`:
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
        vitals: "VitalsTracker | None" = None,
    ) -> None:
        # ... existing assignments ...
        self._vitals = vitals
```

- [ ] **Step 5: Inject hint after tool batch in `_handle_tool_calls`**

At the end of `_handle_tool_calls`, after the `for block in tool_calls:` loop, add:

```python
        # Vitals hint injection — append as a synthetic tool result so the model sees it
        if self._vitals is not None:
            # Update tracker with all tool results just processed
            for block in tool_calls:
                name = block["name"]
                # Find the tool_result message we just added for this call
                for msg in reversed(self._context.messages):
                    if getattr(msg, "tool_use_id", None) == block["id"]:
                        self._vitals.update(str(getattr(msg, "content", "")))
                        break
            hint = self._vitals.hint
            if hint:
                import uuid
                synthetic_id = f"vitals_{uuid.uuid4().hex[:8]}"
                self._context.add_message("tool_result", hint, tool_use_id=synthetic_id)
```

Note: `uuid` is stdlib, no new dependency.

- [ ] **Step 6: Run all agent tests**

```bash
uv run pytest tests/test_agent.py -v
```
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/boukensha/agent.py tests/test_agent.py
git commit -m "feat: inject vitals hints into agent context after each tool batch"
```

---

### Task 6: Update system prompt and run full test suite

**Files:**
- Modify: `prompts/system.md`

- [ ] **Step 1: Update `prompts/system.md`**

Replace the entire file content:

```markdown
You are Boukensha, an autonomous player exploring a CircleMUD world.

Use available tools to observe the world, act deliberately, and explain only what matters for the current turn.

Navigation memory: a persistent room map is maintained automatically as you move.
- map_here: show current room, exits (mapped/unexplored), room capabilities, and a loop warning if stuck
- map_path_to(dest): shortest path to a named room; also accepts capability keywords like "fountain" or "bakery"
- map_find_capability(capability): find the nearest room where you can drink / eat / rest / heal
- map_summary: full overview of all known rooms

Vitals: [vitals] hints appear automatically when HP is low or you are thirsty or hungry. When you see a [vitals] hint, act on it immediately — call map_find_capability with the suggested capability, navigate there, and address the need before doing anything else.

Room capabilities are inferred automatically. When you successfully drink or eat in a room, that capability is confirmed for future reference.
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest tests/ -v
```
Expected: all tests PASS, no regressions.

- [ ] **Step 3: Commit**

```bash
git add prompts/system.md
git commit -m "feat: update system prompt for smart navigation and vitals hints"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Passive vitals detection (phrase + score parsing) → Task 1
- ✅ Affordance inference from description on observe → Task 2
- ✅ Affordance confirmation on drink/eat → Task 4
- ✅ `map_find_capability` tool → Task 3
- ✅ Improved `map_path_to` (exact-first, capability fallback) → Task 3
- ✅ Loop detection in `map_here` → Task 3
- ✅ Vitals hint injection in Agent → Task 5
- ✅ Updated system prompt → Task 6

**Placeholder scan:** None found — all steps contain actual code.

**Type consistency check:**
- `VitalsTracker.hint` is a property returning `str | None` — used as `vt.hint` consistently in Tasks 1 and 5 ✅
- `RoomGraph.rooms_with_affordance(tag: str) -> list[str]` — called in Task 3 `map_find_capability` ✅
- `RoomGraph.confirm_affordance(node_key: str, tag: str) -> None` — called in Task 4 `_observe` ✅
- `Agent.__init__` gains `vitals: VitalsTracker | None = None` — used in Task 5 tests via `make_agent(vitals=vt)` ✅
- `_AFFORDANCE_KEYWORDS` defined in Task 2, referenced in Task 3 `map_path_to` capability fallback ✅
