"""Tracks the most recently touched server playlist so tracks can be added to it."""

_state: dict = {}   # {name: str, pl_id: str}


def set_last(name: str, pl_id: str) -> None:
    _state.clear()
    _state.update({"name": name, "pl_id": pl_id})


def get_last() -> dict | None:
    """Return {name, pl_id} of the last-touched playlist, or None."""
    return dict(_state) if _state else None
