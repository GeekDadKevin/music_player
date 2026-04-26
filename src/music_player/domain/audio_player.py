

import os
import sys
from typing import Optional

# Add the project root (where DLLs are) to PATH as an absolute path
dll_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

import mpv

class AudioPlayer:
    def __init__(self):
        self._player = mpv.MPV(ytdl=True, input_default_bindings=True, input_vo_keyboard=True)
        self._current_url: Optional[str] = None

    def play(self, url: str) -> None:
        self._current_url = url
        self._player.play(url)

    def pause(self) -> None:
        self._player.pause = not self._player.pause

    def stop(self) -> None:
        self._player.stop()
        self._current_url = None

    def set_volume(self, volume: int) -> None:
        self._player.volume = volume

    def seek(self, seconds: float) -> None:
        self._player.seek(seconds, reference='absolute')

    @property
    def time_pos(self) -> float:
        return self._player.time_pos or 0.0

    @property
    def duration(self) -> float:
        return self._player.duration or 0.0

    @property
    def is_playing(self) -> bool:
        return not self._player.pause
