"""
VisualizerPanel — embedded MilkDrop panel shown between the content area and
the player bar.

Controls bar
------------
  [preset name ——— ]  [Prev <]  [Next >]  [Fullscreen]

Lyrics are drawn as a semi-transparent pill near the bottom of the panel.
"""

from __future__ import annotations

import bisect

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.music_player.logging import get_logger
# milkdrop_widget is imported lazily in showEvent() so that projectM, GLEW,
# PortAudio and their DLL dependencies are NOT loaded during app startup.
# Loading those DLLs before the main window HWND is created can crash the
# process via Win32 hooks registered in DllMain.
from src.music_player.ui.components.playback_bridge import get_bridge
from src.music_player.ui.glyphs import (
    CHEVRON_LEFT, CHEVRON_RIGHT, FULLSCREEN, MDL2_FAMILY_CSS, MDL2_FONT, SHUFFLE,
)

logger = get_logger(__name__)

_HEIGHT_MIN     = 160
_HEIGHT_MAX     = 900
_HEIGHT_DEFAULT = 300

_ACCENT = "#2dd4bf"


class VisualizerPanel(QWidget):
    fullscreen_requested = pyqtSignal()   # ask the parent window to go fullscreen

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(_HEIGHT_MIN)
        # Preset dir resolved lazily in showEvent() after milkdrop_widget imports.
        self._preset_dir = ""
        self._preset_idx = 0

        # Lyrics state
        self._synced      = False
        self._sync_lines: list[tuple[float, str]] = []
        self._plain_lines: list[str] = []
        self._lyrics_text = ""
        self._position    = 0.0
        self._duration    = 0.0
        self._lyrics_worker = None

        self._build_ui()
        self._connect_bridge()

    # ── layout ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet("background:#04040c;")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_controls())

        # Visualizer container (relative parent for lyrics overlay)
        self._viz_container = QWidget()
        self._viz_container.setStyleSheet("background:#04040c;")
        viz_lay = QVBoxLayout(self._viz_container)
        viz_lay.setContentsMargins(0, 0, 0, 0)

        # Plain dark widget — projectM/GLEW/PortAudio DLLs are not loaded yet.
        # showEvent() replaces this with MilkdropWidget on first show.
        self._viz = QWidget()
        self._viz.setStyleSheet("background:#04040c;")
        viz_lay.addWidget(self._viz)

        # Lyrics overlay — absolutely positioned child of viz_container
        self._lyrics_lbl = QLabel("", self._viz_container)
        self._lyrics_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lyrics_lbl.setWordWrap(True)
        self._lyrics_lbl.setStyleSheet(
            "color:rgba(255,255,255,235); font-size:14px; "
            "background:rgba(0,0,0,150); border-radius:20px; padding:4px 16px;"
        )
        self._lyrics_lbl.hide()
        self._lyrics_lbl.raise_()

        root.addWidget(self._viz_container, stretch=1)

    def _make_controls(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background:#0a0a14;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(2)

        # Preset name on the left (expanding)
        self._preset_lbl = QLabel("—")
        self._preset_lbl.setStyleSheet("color:#aaa; font-size:12px;")
        self._preset_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preset_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(self._preset_lbl, stretch=1)

        lay.addSpacing(8)

        # Preset nav + Random
        self._btn_random = _nav_btn(f"{SHUFFLE}", "Random preset")
        self._btn_prev   = _nav_btn(f"{CHEVRON_LEFT} Prev", "Previous preset")
        self._btn_next   = _nav_btn(f"Next {CHEVRON_RIGHT}", "Next preset")
        lay.addWidget(self._btn_random)
        lay.addWidget(self._btn_prev)
        lay.addWidget(self._btn_next)
        lay.addSpacing(8)

        self._btn_fs = _glyph_btn(FULLSCREEN, "Fullscreen", 11)
        lay.addWidget(self._btn_fs)

        self._btn_random.clicked.connect(self._random_preset)
        self._btn_prev.clicked.connect(lambda: self._cycle_preset(-1))
        self._btn_next.clicked.connect(lambda: self._cycle_preset(+1))
        self._btn_fs.clicked.connect(self.fullscreen_requested)

        return bar

    def ensure_milkdrop_loaded(self) -> None:
        """Load milkdrop_widget and swap in MilkdropWidget if available.

        Call this BEFORE making the panel visible so replaceWidget() operates
        on a hidden panel — inserting a QOpenGLWidget into an already-painted
        layout causes Qt to briefly reconstitute the native compositing layer,
        producing a visible window flash.
        """
        if getattr(self, "_milkdrop_loaded", False):
            return
        self._milkdrop_loaded = True
        from src.music_player.ui.components.milkdrop_widget import (
            AVAILABLE, MilkdropWidget, default_preset_dir,
        )
        if not self._preset_dir:
            self._preset_dir = default_preset_dir() or ""
        if AVAILABLE:
            real_viz = MilkdropWidget(self._preset_dir, self._preset_idx)
            real_viz.preset_changed.connect(self._on_preset_changed)
            lay = self._viz_container.layout()
            lay.replaceWidget(self._viz, real_viz)
            self._viz.deleteLater()
            self._viz = real_viz
            self._lyrics_lbl.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.ensure_milkdrop_loaded()

    def set_fullscreen_active(self, active: bool) -> None:
        """Called by MusicPlayerWindow when it enters/exits viz fullscreen."""
        self._btn_fs.setToolTip("Exit Fullscreen" if active else "Fullscreen")

    # ── lyrics overlay positioning ────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_lyrics()

    def _reposition_lyrics(self) -> None:
        if not hasattr(self, "_lyrics_lbl"):
            return
        w = self._viz.width() if hasattr(self, "_viz") else self.width()
        h = self._viz.height() if hasattr(self, "_viz") else (self.height() - 40)
        lw = min(w - 80, 700)
        lh = 44
        x = (w - lw) // 2
        y = h - lh - 24
        self._lyrics_lbl.setGeometry(x, y, lw, lh)

    # ── preset cycling ────────────────────────────────────────────────

    def _random_preset(self) -> None:
        if hasattr(self._viz, "random_preset"):
            self._viz.random_preset()

    def _cycle_preset(self, delta: int) -> None:
        if hasattr(self._viz, "next_preset"):
            if delta > 0:
                self._viz.next_preset()
            else:
                self._viz.prev_preset()

    @pyqtSlot(str)
    def _on_preset_changed(self, name: str) -> None:
        self._preset_lbl.setText(name)
        if hasattr(self._viz, "current_index"):
            self._preset_idx = self._viz.current_index()

    # ── bridge connections ────────────────────────────────────────────

    def _connect_bridge(self) -> None:
        bridge = get_bridge()
        bridge.track_changed.connect(self._on_track_changed)
        bridge.position_changed.connect(self._on_position_changed)

    @pyqtSlot(dict)
    def _on_track_changed(self, track: dict) -> None:
        self._synced      = False
        self._sync_lines  = []
        self._plain_lines = []
        self._lyrics_text = ""
        self._position    = 0.0
        self._duration    = float(track.get("duration") or 0)
        self._set_lyrics_display("")

        song_id = track.get("id") or ""
        artist  = track.get("artist") or ""
        title   = track.get("title") or ""
        if song_id and (artist or title):
            from src.music_player.ui.workers.lyrics import LyricsWorker
            w = LyricsWorker(song_id, artist, title)
            w.loaded.connect(self._on_lyrics_loaded)
            self._lyrics_worker = w
            w.start()

    @pyqtSlot(dict)
    def _on_lyrics_loaded(self, data: dict) -> None:
        self._synced = data.get("synced", False)
        if self._synced:
            self._sync_lines  = [(l["t"], l["text"]) for l in data.get("lines", [])]
            self._plain_lines = []
        else:
            self._sync_lines  = []
            self._plain_lines = data.get("lines", [])
        self._refresh_lyrics()

    @pyqtSlot(float, float)
    def _on_position_changed(self, pos: float, dur: float) -> None:
        self._position = pos
        if dur > 0:
            self._duration = dur
        self._refresh_lyrics()

    def _refresh_lyrics(self) -> None:
        if self._synced and self._sync_lines:
            times = [l[0] for l in self._sync_lines]
            idx   = max(0, bisect.bisect_right(times, self._position) - 1)
            text  = self._sync_lines[idx][1]
        elif self._plain_lines and self._duration > 0:
            idx  = int(self._position / self._duration * len(self._plain_lines))
            idx  = max(0, min(idx, len(self._plain_lines) - 1))
            text = self._plain_lines[idx]
        else:
            text = ""
        self._lyrics_text = text
        self._set_lyrics_display(text)

    def _set_lyrics_display(self, text: str) -> None:
        if not hasattr(self, "_lyrics_lbl"):
            return
        if text:
            self._lyrics_lbl.setText(text)
            self._lyrics_lbl.adjustSize()
            self._reposition_lyrics()
            self._lyrics_lbl.show()
            self._lyrics_lbl.raise_()
        else:
            self._lyrics_lbl.hide()


# ── helpers ───────────────────────────────────────────────────────────────

def _nav_btn(text: str, tip: str) -> QPushButton:
    """Text + chevron glyph navigation button, styled like browse-page back buttons."""
    btn = QPushButton(text)
    btn.setToolTip(tip)
    btn.setFixedHeight(28)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton{{background:transparent;color:#666;border:none;"
        f"font-family:{MDL2_FAMILY_CSS};font-size:12px;padding:0 6px;}}"
        f"QPushButton:hover{{color:#ccc;}}"
    )
    return btn


def _glyph_btn(glyph: str, tip: str, size: int = 11) -> QPushButton:
    btn = QPushButton(glyph)
    btn.setToolTip(tip)
    btn.setFixedSize(28, 28)
    btn.setFont(QFont(MDL2_FONT, size))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton{background:transparent;color:#666;border:none;}"
        "QPushButton:hover{color:#fff;}"
    )
    return btn


