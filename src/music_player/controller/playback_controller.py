from src.music_player.repository.subsonic_client import SubsonicClient
from src.music_player.domain.audio_player import AudioPlayer

class PlaybackController:
    def __init__(self):
        self._client = SubsonicClient()
        self._player = AudioPlayer()
        self._current_track_id = None

    def play_track(self, track_id: str) -> None:
        url = self._client.get_song_stream_url(track_id)
        self._player.play(url)
        self._current_track_id = track_id

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def set_volume(self, volume: int) -> None:
        self._player.set_volume(volume)

    def seek(self, seconds: float) -> None:
        self._player.seek(seconds)

    @property
    def is_playing(self) -> bool:
        return self._player.is_playing

    @property
    def time_pos(self) -> float:
        return self._player.time_pos

    @property
    def duration(self) -> float:
        return self._player.duration
