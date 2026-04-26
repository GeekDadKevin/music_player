from PyQt6.QtCore import QObject, pyqtSignal
from src.music_player.controller.playback_controller import PlaybackController

class PlaybackBridge(QObject):
    # Signals for UI updates
    playback_started = pyqtSignal()
    playback_paused = pyqtSignal()
    playback_stopped = pyqtSignal()
    position_changed = pyqtSignal(float, float)  # time_pos, duration

    def __init__(self):
        super().__init__()
        self._controller = PlaybackController()

    def play(self, track_id: str):
        self._controller.play_track(track_id)
        self.playback_started.emit()

    def pause(self):
        self._controller.pause()
        self.playback_paused.emit()

    def stop(self):
        self._controller.stop()
        self.playback_stopped.emit()

    def set_volume(self, volume: int):
        self._controller.set_volume(volume)

    def seek(self, seconds: float):
        self._controller.seek(seconds)

    def poll_position(self):
        self.position_changed.emit(self._controller.time_pos, self._controller.duration)
