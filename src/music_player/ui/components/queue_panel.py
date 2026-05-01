"""Queue panel — collapsible right-side drawer showing the current play queue.

Toggled by the queue button in PlayerBar.
Uses the standard TrackTable so tracks look identical to every other view.
"""

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from src.music_player.logging import get_logger
from src.music_player.queue import get_queue
from src.music_player.ui.components.playback_bridge import get_bridge

logger = get_logger(__name__)

_W = 380   # drawer width — wide enough for a comfortable TrackTable


class QueuePanel(QWidget):
    """Right-side drawer: standard TrackTable of the current queue."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_W)
        self.setStyleSheet("background:#111114;")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._build_ui()

        from src.music_player.ui.components.playback_bridge import get_bridge
        get_bridge().track_changed.connect(self._on_track_changed)
        get_bridge().queue_changed.connect(self.refresh)

    def _build_ui(self) -> None:
        from src.music_player.ui.components.track_table import TrackTable

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet("background:#0d0d10; border-bottom:1px solid #1e1e22;")
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel("Queue")
        f = QFont(); f.setPointSize(13); f.setWeight(QFont.Weight.Bold)
        lbl.setFont(f)
        lbl.setStyleSheet("color:#fff; background:transparent;")
        h_row.addWidget(lbl)
        h_row.addStretch()
        self._status = QLabel("")
        self._status.setStyleSheet("color:#555; font-size:11px; background:transparent;")
        h_row.addWidget(self._status)
        root.addWidget(header)

        self._table = TrackTable()
        # Queue view: double-click jumps to that position — never adds duplicates.
        self._table.doubleClicked.disconnect(self._table._on_double_click)
        self._table.doubleClicked.connect(self._jump_to_row)
        root.addWidget(self._table, stretch=1)

        self.refresh()

    # ── public ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        q = get_queue()
        if not q.tracks:
            self._status.setText("empty")
            self._table.set_tracks([])
            return
        pos   = q.current_index
        count = len(q.tracks)
        self._status.setText(f"{count} track(s)")
        self._table.set_tracks(q.tracks)
        if 0 <= pos < count:
            tid = q.tracks[pos].get("id", "")
            if tid:
                self._table.highlight_track_id(tid)

    # ── slots ───────────────────────────────────────────────────────────

    def _jump_to_row(self, index) -> None:
        row = index.row()
        q = get_queue()
        if 0 <= row < len(q.tracks):
            q.current_index = row
            q._save()
            get_bridge().play_track(q.tracks[row])

    @pyqtSlot(dict)
    def _on_track_changed(self, _track: dict) -> None:
        self.refresh()
