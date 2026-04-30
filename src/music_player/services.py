"""Composition root — the only module allowed to import both sides of a port.

All other modules obey the dependency rule:
  domain      → nothing outside stdlib
  repository  → domain.ports only
  controller  → domain.ports only
  ui          → controller, domain.ports (never repository directly)

This module breaks that rule deliberately, exactly once, to wire concrete
implementations to their abstractions.  Import get_* functions; never import
MpvAudioBackend or SubsonicMusicRepository anywhere else.

Assumption: functions are called after QApplication is running (because
MpvAudioBackend references mpv which may touch display handles on init).
All instances are process-wide singletons created on first access (lazy).
"""

from __future__ import annotations

from src.music_player.logging import get_logger

logger = get_logger(__name__)

# Defer concrete imports so module load is cheap and circular-import-safe.
# Types are declared as strings to avoid importing at module level.
_repository = None   # SubsonicMusicRepository
_audio = None        # MpvAudioBackend
_controller = None   # PlaybackController


def get_repository():
    """Return the shared SubsonicMusicRepository (MusicLibraryPort + StreamPort)."""
    global _repository
    if _repository is None:
        from src.music_player.repository.music_repository import SubsonicMusicRepository
        _repository = SubsonicMusicRepository()
        logger.info("services: SubsonicMusicRepository created")
    return _repository


def get_audio_backend():
    """Return the shared MpvAudioBackend (AudioPort)."""
    global _audio
    if _audio is None:
        from src.music_player.domain.audio_player import MpvAudioBackend
        _audio = MpvAudioBackend()
        logger.info("services: MpvAudioBackend created")
    return _audio


def get_playback_controller():
    """Return the shared PlaybackController with injected ports.

    PlaybackController never sees the concrete classes; it receives only
    AudioPort and StreamPort references.
    """
    global _controller
    if _controller is None:
        from src.music_player.controller.playback_controller import PlaybackController
        _controller = PlaybackController(
            audio=get_audio_backend(),
            stream=get_repository(),
        )
        logger.info("services: PlaybackController created")
    return _controller
