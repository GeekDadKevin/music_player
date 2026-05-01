from PyQt6.QtCore import Qt, QPoint, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QSlider, QVBoxLayout, QWidget,
)

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.ui.app_settings import load_settings, settings_signals
from src.music_player.ui.components.playback_bridge import get_bridge
from src.music_player.ui.glyphs import (
    ADD, FULLSCREEN, HEART, HEART_FILLED,
    MDL2_FONT, NEXT, PAUSE, PLAY, PREV, QUEUE, REPEAT, SHUFFLE, VISUALIZER, VOLUME,
)

logger = get_logger(__name__)

_ART_SZ = 40   # album art thumbnail size


def _fmt(s: float) -> str:
    s = int(s or 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def _accent() -> str:
    return load_settings().highlight_color


class PlayerBar(QWidget):
    queue_toggled      = pyqtSignal()   # emitted when the queue button is clicked
    visualizer_toggled = pyqtSignal()   # emitted when the visualizer button is clicked

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._seeking     = False
        self._duration    = 0.0
        self._last_artist = ""
        self._vol_popup: _VolumePopup | None = None
        self._build_ui()
        self._connect()
        settings_signals().changed.connect(self._on_settings_changed)

    # ── layout ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setStyleSheet("background:#111114;")
        color = _accent()

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 0, 12, 0)
        root.setSpacing(0)

        # ── LEFT: art + track info + ♡ + + ───────────────────────────
        left = QHBoxLayout()
        left.setSpacing(10)
        left.setContentsMargins(0, 0, 0, 0)

        self._art = QLabel()
        self._art.setFixedSize(_ART_SZ, _ART_SZ)
        self._art.setStyleSheet("border-radius:4px; background:#2a2a2e;")
        left.addWidget(self._art)

        info = QVBoxLayout()
        info.setSpacing(2)
        info.setContentsMargins(0, 0, 0, 0)
        self._lbl_title = QLabel("—")
        self._lbl_title.setStyleSheet(
            "color:#fff; font-size:13px; font-weight:600; background:transparent;"
        )
        self._lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._lbl_artist = QPushButton("")
        self._lbl_artist.setFlat(True)
        self._lbl_artist.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lbl_artist.setStyleSheet(
            "QPushButton{background:transparent;color:#888;font-size:11px;"
            "border:none;padding:0;text-align:left;}"
            "QPushButton:hover{color:#5eead4;}"
        )
        self._lbl_artist.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._lbl_artist.clicked.connect(self._on_artist_clicked)
        info.addWidget(self._lbl_title)
        info.addWidget(self._lbl_artist)
        left.addLayout(info, stretch=1)

        self._btn_heart = _small_btn(HEART, "Favourite", 13)
        self._btn_heart.setStyleSheet(
            "QPushButton{background:transparent;color:#555;"
            f"font-family:\"{MDL2_FONT}\";font-size:14px;border:none;}}"
            "QPushButton:hover{color:#fff;}"
        )
        left.addWidget(self._btn_heart)

        self._btn_add = _small_btn(ADD, "Add", 11)
        left.addWidget(self._btn_add)

        left_w = QWidget()
        left_w.setStyleSheet("background:transparent;")
        left_w.setLayout(left)
        # Give left section stretch=1 so it shares space equally with the right
        # section — center transport stays pinned to the middle of the bar.
        root.addWidget(left_w, stretch=1)

        # ── CENTER: transport + progress ──────────────────────────────
        center = QVBoxLayout()
        center.setSpacing(4)
        center.setContentsMargins(0, 8, 0, 8)

        # Transport row
        transport = QHBoxLayout()
        transport.setSpacing(10)
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.btn_shuffle = _small_btn(SHUFFLE, "Shuffle", 11)
        self.btn_prev    = _small_btn(PREV,    "Previous", 11)
        self.btn_play    = _play_btn(color)
        self.btn_next    = _small_btn(NEXT,    "Next",     11)
        self.btn_repeat  = _small_btn(REPEAT,  "Repeat",   11)

        for b in (self.btn_shuffle, self.btn_prev, self.btn_play,
                  self.btn_next, self.btn_repeat):
            transport.addWidget(b)

        center.addLayout(transport)

        # Progress row
        progress = QHBoxLayout()
        progress.setSpacing(8)
        progress.setContentsMargins(0, 0, 0, 0)

        self.lbl_time = QLabel("00:00")
        self.lbl_time.setFixedWidth(40)
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_time.setStyleSheet("color:#555; font-size:11px; background:transparent;")
        progress.addWidget(self.lbl_time)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(1000)
        self.slider.setValue(0)
        self.slider.setFixedWidth(360)
        self.slider.setStyleSheet(self._progress_style(color))
        progress.addWidget(self.slider)

        self.lbl_duration = QLabel("00:00")
        self.lbl_duration.setFixedWidth(40)
        self.lbl_duration.setStyleSheet("color:#555; font-size:11px; background:transparent;")
        progress.addWidget(self.lbl_duration)

        center.addLayout(progress)

        center_w = QWidget()
        center_w.setStyleSheet("background:transparent;")
        center_w.setLayout(center)
        root.addWidget(center_w)

        # ── RIGHT: queue + volume + placeholder ───────────────────────
        right = QHBoxLayout()
        right.setSpacing(4)
        right.setContentsMargins(0, 0, 0, 0)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._btn_queue = _small_btn(QUEUE,      "Queue",        12)
        self._btn_viz   = _small_btn(VISUALIZER, "Visualizer",   12)
        self._btn_vol   = _small_btn(VOLUME,     "Volume",       12)
        self._btn_extra = _small_btn(FULLSCREEN, "Cast",         11)

        for b in (self._btn_queue, self._btn_viz, self._btn_vol, self._btn_extra):
            right.addWidget(b)

        right_w = QWidget()
        right_w.setStyleSheet("background:transparent;")
        right_w.setLayout(right)
        # Same stretch=1 as left so center stays exactly in the middle
        root.addWidget(right_w, stretch=1)

    # ── signal wiring ─────────────────────────────────────────────────

    def _connect(self) -> None:
        bridge = get_bridge()
        bridge.track_changed.connect(self._on_track_changed)
        bridge.position_changed.connect(self._on_position_changed)
        bridge.playback_state_changed.connect(self._on_state_changed)
        bridge.status_message.connect(self._on_status_message)
        bridge.star_state_changed.connect(self._on_star_changed)

        self.btn_play.clicked.connect(lambda _: bridge.play_pause())
        self.btn_next.clicked.connect(bridge.next_track)
        self.btn_prev.clicked.connect(bridge.previous_track)
        self._btn_heart.clicked.connect(lambda _: bridge.toggle_star_current())
        self._btn_vol.clicked.connect(self._toggle_volume_popup)

        self.slider.sliderPressed.connect(self._on_seek_start)
        self.slider.sliderReleased.connect(self._on_seek_end)
        self._btn_queue.clicked.connect(self.queue_toggled)
        self._btn_viz.clicked.connect(self.visualizer_toggled)

        bridge.set_volume(80)

    # ── slots ─────────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def _on_track_changed(self, track: dict) -> None:
        self._lbl_title.setText(track.get("title") or "—")
        self._last_artist = track.get("artist") or ""
        self._lbl_artist.setText(self._last_artist)
        self._lbl_artist.setStyleSheet(
            "QPushButton{background:transparent;color:#888;font-size:11px;"
            "border:none;padding:0;text-align:left;}"
            "QPushButton:hover{color:#5eead4;}"
        )
        self._duration = float(track.get("duration") or 0)
        self.lbl_duration.setText(_fmt(self._duration))
        self.slider.setValue(0)
        self.lbl_time.setText("00:00")
        self.btn_play.setText(PAUSE)
        self._load_art(track.get("coverArt") or "")

    @pyqtSlot(float, float)
    def _on_position_changed(self, time_pos: float, duration: float) -> None:
        if self._seeking:
            return
        if duration > 0:
            self._duration = duration
            self.lbl_duration.setText(_fmt(duration))
            self.slider.setValue(int(time_pos / duration * 1000))
        self.lbl_time.setText(_fmt(time_pos))

    @pyqtSlot(bool)
    def _on_state_changed(self, is_playing: bool) -> None:
        self.btn_play.setText(PAUSE if is_playing else PLAY)

    @pyqtSlot(str)
    def _on_status_message(self, msg: str) -> None:
        self._lbl_artist.setText(msg if msg else self._last_artist)
        color = _accent() if msg else "#888"
        self._lbl_artist.setStyleSheet(
            f"QPushButton{{background:transparent;color:{color};font-size:11px;"
            "border:none;padding:0;text-align:left;}"
            "QPushButton:hover{color:#5eead4;}"
        )

    def _on_artist_clicked(self) -> None:
        if self._last_artist:
            from src.music_player.ui.navigation import nav_bus
            nav_bus().show_artist.emit(self._last_artist)

    @pyqtSlot(bool)
    def _on_star_changed(self, starred: bool) -> None:
        self._btn_heart.setText(HEART_FILLED if starred else HEART)
        color = _accent() if starred else "#555"
        self._btn_heart.setStyleSheet(
            f"QPushButton{{background:transparent;color:{color};"
            f"font-family:\"{MDL2_FONT}\";font-size:14px;border:none;}}"
            "QPushButton:hover{color:#fff;}"
        )

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek_end(self) -> None:
        self._seeking = False
        if self._duration > 0:
            get_bridge().seek(self.slider.value() / 1000 * self._duration)

    def _load_art(self, cover_art_id: str) -> None:
        data = image_store.get(f"album:{cover_art_id}") if cover_art_id else None
        if not data:
            self._art.clear()
            self._art.setStyleSheet("border-radius:4px; background:#2a2a2e;")
            if cover_art_id:
                from src.music_player.ui.workers.image_loader import AlbumCoverLoader, _launch
                loader = AlbumCoverLoader(cover_art_id)
                loader.loaded.connect(self._on_art_loaded)
                _launch(loader)
            return
        self._on_art_loaded(data)

    @pyqtSlot(bytes)
    def _on_art_loaded(self, data: bytes) -> None:
        px = QPixmap()
        if data and px.loadFromData(data):
            self._art.setPixmap(_rounded_pixmap(px, _ART_SZ, 4))
            self._art.setStyleSheet("")
        else:
            self._art.setStyleSheet("border-radius:4px; background:#2a2a2e;")

    # ── volume popup ──────────────────────────────────────────────────

    def _toggle_volume_popup(self) -> None:
        if self._vol_popup is None:
            self._vol_popup = _VolumePopup(self)
            self._vol_popup.slider.valueChanged.connect(get_bridge().set_volume)
            self._vol_popup.slider.setValue(80)

        if self._vol_popup.isVisible():
            self._vol_popup.hide()
            return

        # Position above the volume button
        btn_pos = self._btn_vol.mapToGlobal(QPoint(0, 0))
        px = btn_pos.x() + self._btn_vol.width() // 2 - self._vol_popup.width() // 2
        py = btn_pos.y() - self._vol_popup.height() - 4
        self._vol_popup.move(px, py)
        self._vol_popup.show()

    # ── settings refresh ──────────────────────────────────────────────

    def _on_settings_changed(self) -> None:
        color = _accent()
        self.btn_play.setStyleSheet(_play_btn_style(color))
        self.slider.setStyleSheet(self._progress_style(color))

    @staticmethod
    def _progress_style(color: str) -> str:
        return (
            f"QSlider::groove:horizontal{{height:4px;background:#252528;border-radius:2px;}}"
            f"QSlider::handle:horizontal{{background:{color};border:none;"
            "width:10px;margin:-3px 0;border-radius:5px;}"
            f"QSlider::sub-page:horizontal{{background:{color};border-radius:2px;}}"
        )


# ── volume popup ──────────────────────────────────────────────────────

class _VolumePopup(QWidget):
    """Vertical volume slider that floats above the volume button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFixedSize(44, 130)
        self.setStyleSheet(
            "background:#1a1a1e; border:1px solid #2a2a2e; border-radius:8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setValue(80)
        self.slider.setStyleSheet("""
            QSlider::groove:vertical {
                width: 4px; background: #333; border-radius: 2px;
            }
            QSlider::handle:vertical {
                background: #fff; border: none;
                height: 10px; margin: 0 -3px; border-radius: 5px;
            }
            QSlider::sub-page:vertical {
                background: #2dd4bf; border-radius: 2px;
            }
        """)
        layout.addWidget(self.slider)


# ── helpers ───────────────────────────────────────────────────────────

def _small_btn(glyph: str, tip: str, size: int = 11) -> QPushButton:
    btn = QPushButton(glyph)
    btn.setToolTip(tip)
    btn.setFixedSize(30, 30)
    btn.setFont(QFont(MDL2_FONT, size))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton{background:transparent;color:#777;border:none;}"
        "QPushButton:hover{color:#fff;}"
    )
    return btn


def _play_btn(color: str) -> QPushButton:
    btn = QPushButton(PLAY)
    btn.setToolTip("Play / Pause")
    btn.setFixedSize(36, 36)
    btn.setFont(QFont(MDL2_FONT, 12))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_play_btn_style(color))
    return btn


def _play_btn_style(color: str) -> str:
    return (
        f"QPushButton{{background:{color};color:#000;border:none;border-radius:18px;}}"
        f"QPushButton:hover{{background:{color}cc;}}"
    )


def _rounded_pixmap(px: QPixmap, size: int, radius: int) -> QPixmap:
    scaled = px.scaled(size, size,
                       Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - size) // 2
    y = (scaled.height() - size) // 2
    scaled = scaled.copy(x, y, size, size)
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return result
