import os
import httpx
from typing import Optional

class SubsonicClient:
    def __init__(self):
        self.server_url = os.getenv("SUBSONIC_SERVER_URL")
        self.username = os.getenv("SUBSONIC_USERNAME")
        self.password = os.getenv("SUBSONIC_PASSWORD")
        if not all([self.server_url, self.username, self.password]):
            raise ValueError("Missing Subsonic connection details in environment variables.")
        self.session = httpx.Client()

    def ping(self) -> bool:
        url = f"{self.server_url}/rest/ping.view"
        params = self._auth_params()
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json().get("subsonic-response", {}).get("status") == "ok"
        except Exception:
            return False

    def get_song_stream_url(self, song_id: str) -> str:
        url = f"{self.server_url}/rest/stream.view"
        params = self._auth_params()
        params["id"] = song_id
        return self.session.build_request("GET", url, params=params).url.__str__()

    def _auth_params(self) -> dict:
        # OpenSubsonic/Octo-Fiesta: use username/password directly for now
        return {
            "u": self.username,
            "p": self.password,
            "v": "1.16.1",
            "c": "music-player",
            "f": "json"
        }

    def get_song(self, song_id: str) -> Optional[dict]:
        url = f"{self.server_url}/rest/getSong.view"
        params = self._auth_params()
        params["id"] = song_id
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("subsonic-response", {}).get("song")
