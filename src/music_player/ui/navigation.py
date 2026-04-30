"""Process-wide navigation bus.

Any widget can call nav_bus().show_artist(name) or show_album(...) to request
navigation without needing to thread signals up through parent hierarchies.
LibraryPage connects to these signals and handles the actual stack switch.
"""

from PyQt6.QtCore import QObject, pyqtSignal


class _NavigationBus(QObject):
    show_artist = pyqtSignal(str)          # artist name
    show_album  = pyqtSignal(str, str, str)  # album_id, album_name, artist_name


_bus: _NavigationBus | None = None


def nav_bus() -> _NavigationBus:
    global _bus
    if _bus is None:
        _bus = _NavigationBus()
    return _bus
