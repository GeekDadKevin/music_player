"""Sidebar pin persistence — ~/.music-player/pins.json.

A pin is a dict with at minimum: type, id, name.
  type: "artist" | "album" | "playlist" | "track"
  id:   Subsonic entity ID
  name: display label

Callers should use add_pin(), remove_pin(), and load_pins().
pins_changed() returns a QObject whose .changed signal fires after mutations.
"""

import json
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_PINS_FILE = Path.home() / ".music-player" / "pins.json"


# ── persistence ───────────────────────────────────────────────────────

def load_pins() -> list[dict]:
    try:
        if _PINS_FILE.exists():
            return json.loads(_PINS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not load pins: {exc}")
    return []


def _save(pins: list[dict]) -> None:
    try:
        _PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PINS_FILE.write_text(json.dumps(pins, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Could not save pins: {exc}")


def add_pin(pin: dict) -> None:
    """Add a pin if not already present (matched by type + id)."""
    pins = load_pins()
    key = (pin.get("type"), pin.get("id"))
    if any((p.get("type"), p.get("id")) == key for p in pins):
        return
    pins.append(pin)
    _save(pins)
    _bus.changed.emit()


def remove_pin(pin_type: str, pin_id: str) -> None:
    pins = [p for p in load_pins()
            if not (p.get("type") == pin_type and p.get("id") == pin_id)]
    _save(pins)
    _bus.changed.emit()


# ── signal bus ────────────────────────────────────────────────────────

class _PinSignals(QObject):
    changed = pyqtSignal()


_bus = _PinSignals()


def pins_changed() -> _PinSignals:
    return _bus
