"""Internal OpenSubsonic HTTP transport.

Not part of the public repository interface.  Use SubsonicMusicRepository
for all library access; use the module only from within the repository layer.

Assumptions:
- Credentials are read from environment variables once at construction time.
- Token-based auth: t = md5(password + salt), s = new random hex salt per
  request.  This is required by OpenSubsonic spec §3; plaintext password
  auth ('p' param) is intentionally not supported.
- All JSON endpoints wrap their payload in a 'subsonic-response' root key.
  A status of 'ok' is required; anything else raises RuntimeError.
- The httpx.Client session is reused across requests (keep-alive).

Raises:
- ValueError at construction if any credential env var is missing.
- httpx.HTTPStatusError on 4xx/5xx responses.
- httpx.RequestError on network-level failures.
- RuntimeError when the server returns status != 'ok'.
"""

from __future__ import annotations

import hashlib
import os
import secrets

import httpx
from dotenv import load_dotenv

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_API_VERSION = "1.16.1"
_CLIENT_NAME = "music-player"


class SubsonicHttp:
    """Low-level HTTP client for OpenSubsonic.

    Responsibilities:
    - Building per-request auth params (token, salt).
    - Issuing GET requests and unwrapping JSON envelopes.
    - Fetching binary responses (cover art).

    This class knows nothing about domain objects; it deals only in
    raw dicts and bytes.
    """

    def __init__(self) -> None:
        load_dotenv()
        self.server_url = os.getenv("SUBSONIC_SERVER_URL", "").rstrip("/")
        self.username = os.getenv("SUBSONIC_USERNAME", "")
        self._password = os.getenv("SUBSONIC_PASSWORD", "")

        if not all([self.server_url, self.username, self._password]):
            raise ValueError(
                "SUBSONIC_SERVER_URL, SUBSONIC_USERNAME, and SUBSONIC_PASSWORD "
                "must all be set in the environment or .env file."
            )
        self._session = httpx.Client()

    # ── public helpers ────────────────────────────────────────────────

    def auth_params(self) -> dict[str, str]:
        """Build per-request token auth params.

        Contract: generate a fresh salt on every call; never reuse params.
        """
        salt = secrets.token_hex(8)
        token = hashlib.md5((self._password + salt).encode()).hexdigest()
        return {
            "u": self.username,
            "t": token,
            "s": salt,
            "v": _API_VERSION,
            "c": _CLIENT_NAME,
            "f": "json",
        }

    def get(
        self,
        endpoint: str,
        extra: dict | None = None,
        timeout: float = 15.0,
    ) -> dict:
        """GET an OpenSubsonic JSON endpoint.

        Returns the 'subsonic-response' dict.
        Raises RuntimeError if status != 'ok'.
        """
        # Build params as a list of (key, value) pairs so that list values
        # (e.g. multiple songId entries for createPlaylist) expand correctly.
        auth = self.auth_params()
        param_list = list(auth.items())
        if extra:
            for k, v in extra.items():
                if isinstance(v, list):
                    param_list.extend((k, item) for item in v)
                else:
                    param_list.append((k, v))
        url = f"{self.server_url}/rest/{endpoint}"
        resp = self._session.get(url, params=param_list, timeout=timeout)
        resp.raise_for_status()
        data = resp.json().get("subsonic-response", {})
        if data.get("status") != "ok":
            raise RuntimeError(f"Subsonic error [{endpoint}]: {data}")
        return data

    def get_bytes(
        self,
        endpoint: str,
        extra: dict | None = None,
        timeout: float = 15.0,
    ) -> bytes:
        """GET a binary endpoint (e.g. getCoverArt).

        Returns raw response bytes.
        """
        auth = self.auth_params()
        param_list = list(auth.items())
        if extra:
            for k, v in extra.items():
                if isinstance(v, list):
                    param_list.extend((k, item) for item in v)
                else:
                    param_list.append((k, v))
        url = f"{self.server_url}/rest/{endpoint}"
        resp = self._session.get(url, params=param_list, timeout=timeout)
        resp.raise_for_status()
        return resp.content

    def stream_url(self, track_id: str) -> str:
        """Return a fully-formed stream URL for a Subsonic song ID.

        The URL embeds auth tokens; treat it as a short-lived secret.
        Valid for the current session only (new salt each call).
        """
        params = self.auth_params()
        params["id"] = track_id
        url = f"{self.server_url}/rest/stream.view"
        return str(self._session.build_request("GET", url, params=params).url)
