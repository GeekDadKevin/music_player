"""Application settings — persisted to ~/.music-player/settings.json.

Usage:
    from src.music_player.ui.app_settings import load_settings, save_settings

Settings are loaded once and cached; call save_settings() after any mutation.
The module also holds a PyQt signal bus so UI components can react to changes.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_SETTINGS_FILE = Path.home() / ".music-player" / "settings.json"

_DEFAULTS = {
    "highlight_color":     "#2dd4bf",
    "min_play_seconds":    30,
    "scrobble_enabled":    True,
    "double_click_action": "play_now",
}


@dataclass
class AppSettings:
    highlight_color:     str  = "#2dd4bf"   # accent / highlight colour used throughout UI
    min_play_seconds:    int  = 30          # seconds before a play is recorded
    scrobble_enabled:    bool = True        # whether to scrobble plays to the server
    double_click_action: str  = "play_now"  # "play_now" | "play_now_keep" | "add_to_queue" | "play_next"


# ── persistence ───────────────────────────────────────────────────────

_cache: AppSettings | None = None


def load_settings() -> AppSettings:
    global _cache
    if _cache is not None:
        return _cache
    try:
        if _SETTINGS_FILE.exists():
            raw = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            merged = {**_DEFAULTS, **raw}
            _cache = AppSettings(
                highlight_color     = str(merged["highlight_color"]),
                min_play_seconds    = int(merged["min_play_seconds"]),
                scrobble_enabled    = bool(merged["scrobble_enabled"]),
                double_click_action = str(merged.get("double_click_action", "play_now")),
            )
        else:
            _cache = AppSettings()
    except Exception as exc:
        logger.warning(f"Could not load settings: {exc} — using defaults")
        _cache = AppSettings()
    return _cache


def save_settings(settings: AppSettings) -> None:
    global _cache
    _cache = settings
    try:
        _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(
            json.dumps(asdict(settings), indent=2), encoding="utf-8"
        )
        _signals.changed.emit()
        logger.info(f"Settings saved: {asdict(settings)}")
    except Exception as exc:
        logger.error(f"Could not save settings: {exc}")


# ── signal bus ────────────────────────────────────────────────────────

class _SettingsSignals(QObject):
    changed = pyqtSignal()   # emitted after every save_settings() call


_signals = _SettingsSignals()


def settings_signals() -> _SettingsSignals:
    """Return the singleton signal bus — connect to .changed for live updates."""
    return _signals
