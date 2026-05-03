from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.ui.components.flow_grid import FlowGrid
from src.music_player.ui.components.track_table import TrackTable
from src.music_player.ui.workers.album_tracks import LoadAlbumTracksWorker
from src.music_player.ui.workers.artist_detail import LoadArtistAlbumsWorker, LoadTopTracksWorker

logger = get_logger(__name__)


def _circle_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
    scaled = pixmap.scaled(size, size,
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
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return result

_HERO_SIZE = 140
_ALBUM_IMG = 120
_ALBUM_CARD_W = 140
_ALBUM_CARD_H = 170


class ArtistDetailPage(QWidget):
    back_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._album_worker: LoadArtistAlbumsWorker | None = None
        self._tracks_worker: LoadTopTracksWorker | None = None
        self._track_load_worker: LoadAlbumTracksWorker | None = None
        self._resolve_worker = None
        self._current_artist_name: str = ""
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────
    def load_artist(self, artist_data: dict) -> None:
        name = artist_data.get("name", "Unknown Artist")
        artist_id = artist_data.get("id", "")
        self._current_artist_name = name

        image_bytes = image_store.get(f"artist:{name.lower()}")
        if image_bytes:
            px = QPixmap()
            if px.loadFromData(image_bytes):
                self._hero_img.setPixmap(_circle_pixmap(px, _HERO_SIZE))
        else:
            self._hero_img.clear()
            self._hero_img.setStyleSheet(f"border-radius:{_HERO_SIZE//2}px; background:#2a2a2e;")
            from src.music_player.ui.workers.image_loader import ArtistImageLoader, _launch
            loader = ArtistImageLoader(name)
            loader.loaded.connect(self._on_hero_image_loaded)
            _launch(loader)

        self._hero_name.setText(name)
        self._clear_tracks()
        self._clear_albums()
        self._hide_track_table()
        self._tracks_status.setText("Loading top tracks…")
        self._albums_status.setText("Loading discography…")

        for w in (self._album_worker, self._tracks_worker, self._track_load_worker):
            if w and w.isRunning():
                w.quit(); w.wait()

        self._album_worker = LoadArtistAlbumsWorker(artist_id, parent=self)
        self._album_worker.albums_loaded.connect(self._on_albums_loaded)
        self._album_worker.error.connect(lambda e: self._albums_status.setText(f"Error: {e}"))
        self._album_worker.start()

        self._tracks_worker = LoadTopTracksWorker(name, parent=self)
        self._tracks_worker.tracks_loaded.connect(self._on_tracks_loaded)
        self._tracks_worker.error.connect(self._on_tracks_error)
        self._tracks_worker.start()

    # ── build UI (once) ───────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        back_row = QHBoxLayout()
        back_row.setContentsMargins(16, 12, 16, 0)
        back_btn = QPushButton("← Artists")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#1db954;"
            "font-size:14px;font-weight:600;border:none;padding:4px 0;}"
            "QPushButton:hover{color:#fff;}"
        )
        back_btn.clicked.connect(self.back_clicked)
        back_row.addWidget(back_btn)
        back_row.addStretch()
        root.addLayout(back_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:transparent;")
        root.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background:#111114;")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 24, 32, 32)
        layout.setSpacing(28)

        # ── hero ──────────────────────────────────────────────────────
        hero_row = QHBoxLayout()
        hero_row.setSpacing(24)
        self._hero_img = QLabel()
        self._hero_img.setFixedSize(_HERO_SIZE, _HERO_SIZE)
        self._hero_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hero_img.setStyleSheet(f"border-radius:{_HERO_SIZE//2}px; background:#2a2a2e;")
        hero_row.addWidget(self._hero_img)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(6)
        hero_text.addStretch()
        self._hero_name = QLabel()
        f = QFont(); f.setPointSize(32); f.setWeight(QFont.Weight.Bold)
        self._hero_name.setFont(f)
        self._hero_name.setStyleSheet("color:#fff; background:transparent;")
        self._hero_name.setWordWrap(True)
        hero_text.addWidget(self._hero_name)
        hero_text.addStretch()
        hero_row.addLayout(hero_text, stretch=1)
        layout.addLayout(hero_row)
        layout.addWidget(_divider())

        # ── top tracks (ListenBrainz) ─────────────────────────────────
        layout.addWidget(_section_heading("Top Tracks  ·  ListenBrainz"))
        self._tracks_status = QLabel("")
        self._tracks_status.setStyleSheet("color:#666; font-size:13px; background:transparent;")
        layout.addWidget(self._tracks_status)
        self._top_tracks_table = TrackTable()
        self._top_tracks_table.embed_in_scroll_area()
        self._top_tracks_table.setVisible(False)
        layout.addWidget(self._top_tracks_table)
        layout.addWidget(_divider())

        # ── discography ───────────────────────────────────────────────
        # Wrap everything in a tight inner widget so the main layout's 28px
        # spacing only applies once (above the section heading), not between
        # every heading/grid pair inside the section.
        disco_outer = QWidget()
        disco_outer.setStyleSheet("background:transparent;")
        disco_vbox = QVBoxLayout(disco_outer)
        disco_vbox.setContentsMargins(0, 0, 0, 0)
        disco_vbox.setSpacing(6)
        layout.addWidget(disco_outer)

        disco_vbox.addWidget(_section_heading("Discography"))
        self._albums_status = QLabel("")
        self._albums_status.setStyleSheet("color:#666; font-size:13px; background:transparent;")
        disco_vbox.addWidget(self._albums_status)

        # Sub-sections: Albums, EPs, Singles, Soundtracks & Compilations.
        # Each section is a tight container (heading + grid) hidden until populated.
        self._disco_sections: dict[str, tuple[QWidget, FlowGrid]] = {}
        for key, label in (
            ("album",  "Albums"),
            ("ep",     "EPs"),
            ("single", "Singles"),
            ("other",  "Soundtracks & Compilations"),
        ):
            sec = QWidget()
            sec.setStyleSheet("background:transparent;")
            sec_vbox = QVBoxLayout(sec)
            sec_vbox.setContentsMargins(0, 0, 0, 0)
            sec_vbox.setSpacing(4)
            sec_vbox.addWidget(_sub_heading(label))
            flow = FlowGrid(item_width=_ALBUM_CARD_W, spacing=12, margins=(0, 0, 0, 0))
            flow.setStyleSheet("background:transparent;")
            sec_vbox.addWidget(flow)
            sec.setVisible(False)
            disco_vbox.addWidget(sec)
            self._disco_sections[key] = (sec, flow)

        # ── album track panel (hidden until album clicked) ─────────────
        layout.addWidget(_divider())
        self._track_panel_heading = _section_heading("")
        self._track_panel_heading.setVisible(False)
        layout.addWidget(self._track_panel_heading)

        self._track_table = TrackTable()
        self._track_table.embed_in_scroll_area()
        self._track_table.setVisible(False)
        layout.addWidget(self._track_table)

        self._track_panel_status = QLabel("")
        self._track_panel_status.setStyleSheet("color:#666; font-size:13px; background:transparent;")
        layout.addWidget(self._track_panel_status)

        layout.addStretch()

    # ── slots ─────────────────────────────────────────────────────────
    @pyqtSlot(list)
    def _on_albums_loaded(self, albums: list) -> None:
        self._albums_status.setText("")
        if not albums:
            self._albums_status.setText("No albums found.")
            return

        buckets: dict[str, list] = {"album": [], "ep": [], "single": [], "other": []}
        for album in albums:
            buckets[_classify_album(album)].append(album)

        for key, (sec, flow) in self._disco_sections.items():
            album_list = buckets[key]
            if not album_list:
                sec.setVisible(False)
                continue
            sec.setVisible(True)
            for album in album_list:
                cover_id = album.get("coverArt", "")
                artist   = album.get("artist", "")
                name     = album.get("name", "")
                img_data = image_store.get(f"album:{cover_id}") if cover_id else None
                card = _AlbumCard(name, album.get("year"), img_data, album)
                card.clicked.connect(self._on_album_clicked)
                flow.add_widget(card)
                if not img_data:
                    from src.music_player.ui.workers.image_loader import AlbumCoverLoader, _launch
                    loader = AlbumCoverLoader(cover_id, artist, name)
                    loader.loaded.connect(card.set_cover)
                    _launch(loader)

    @pyqtSlot(dict)
    def _on_album_clicked(self, album: dict) -> None:
        album_id = album.get("id", "")
        album_name = album.get("name", "")
        if not album_id:
            return
        self._track_panel_heading.setText(album_name)
        self._track_panel_heading.setVisible(True)
        self._track_table.setVisible(False)
        self._track_panel_status.setText("Loading tracks…")

        if self._track_load_worker and self._track_load_worker.isRunning():
            self._track_load_worker.quit()
            self._track_load_worker.wait()

        extra_ids   = [i for i in album.get("_all_ids", []) if i != album_id]
        artist_name = album.get("artist", "")
        self._track_load_worker = LoadAlbumTracksWorker(
            album_id, extra_ids=extra_ids, artist=artist_name, album_name=album_name, parent=self
        )
        self._track_load_worker.tracks_loaded.connect(self._on_album_tracks_loaded)
        self._track_load_worker.error.connect(
            lambda e: self._track_panel_status.setText(f"Error: {e}")
        )
        self._track_load_worker.start()

    @pyqtSlot(list, dict)
    def _on_album_tracks_loaded(self, tracks: list, album: dict) -> None:
        self._track_panel_status.setText("")
        if not tracks:
            self._track_panel_status.setText("No tracks found.")
            return
        self._track_table.set_tracks(tracks)
        self._track_table._fit_to_content()
        self._track_table.setVisible(True)

    @pyqtSlot(list)
    def _on_tracks_loaded(self, tracks: list) -> None:
        from src.music_player.ui.workers.artist_detail import ResolveTopTracksWorker
        self._tracks_status.setText("")
        if not tracks:
            self._tracks_status.setText("No data available.")
            return
        artist = self._current_artist_name
        missing = [
            {"title": t["name"], "artist": artist, "album": "", "duration": 0, "_missing": True}
            for t in tracks
        ]
        self._top_tracks_table.set_tracks(missing)
        self._top_tracks_table._fit_to_content()
        self._top_tracks_table.setVisible(True)

        if self._resolve_worker and self._resolve_worker.isRunning():
            self._resolve_worker.quit()
            self._resolve_worker.wait()
        self._resolve_worker = ResolveTopTracksWorker(missing, artist, parent=self)
        self._resolve_worker.all_resolved.connect(self._on_tracks_resolved)
        self._resolve_worker.start()

    @pyqtSlot(list)
    def _on_tracks_resolved(self, tracks: list) -> None:
        self._top_tracks_table.set_tracks(tracks)
        self._top_tracks_table._fit_to_content()

    @pyqtSlot(bytes)
    def _on_hero_image_loaded(self, data: bytes) -> None:
        if data:
            px = QPixmap()
            if px.loadFromData(data):
                self._hero_img.setPixmap(_circle_pixmap(px, _HERO_SIZE))

    @pyqtSlot(str)
    def _on_tracks_error(self, message: str) -> None:
        self._tracks_status.setText(f"Unavailable — {message}")

    def _hide_track_table(self) -> None:
        self._track_panel_heading.setVisible(False)
        self._track_table.setVisible(False)
        self._track_panel_status.setText("")

    def _clear_tracks(self) -> None:
        self._top_tracks_table.set_tracks([])
        self._top_tracks_table.setVisible(False)

    def _clear_albums(self) -> None:
        for sec, flow in self._disco_sections.values():
            sec.setVisible(False)
            flow.clear()


# ── helper widgets ────────────────────────────────────────────────────

class _TrackRow(QWidget):
    def __init__(self, rank: int, name: str, listen_count: int) -> None:
        super().__init__()
        self.setStyleSheet("background:transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)
        rank_lbl = QLabel(str(rank))
        rank_lbl.setFixedWidth(24)
        rank_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rank_lbl.setStyleSheet("color:#555; font-size:13px; background:transparent;")
        layout.addWidget(rank_lbl)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color:#fff; font-size:14px; background:transparent;")
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name_lbl)
        if listen_count:
            count_lbl = QLabel(f"{listen_count:,} plays")
            count_lbl.setStyleSheet("color:#666; font-size:12px; background:transparent;")
            count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(count_lbl)


class _AlbumCard(QWidget):
    clicked = pyqtSignal(dict)

    def __init__(self, name: str, year: int | None, image_data: bytes | None, album_data: dict = None) -> None:
        super().__init__()
        self._album_data = album_data or {}
        self.setFixedSize(_ALBUM_CARD_W, _ALBUM_CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._img_lbl = QLabel()
        img_lbl = self._img_lbl
        img_lbl.setFixedSize(_ALBUM_IMG, _ALBUM_IMG)
        img_lbl.setStyleSheet("border-radius:6px; background:#2a2a2e;")
        if image_data:
            px = QPixmap()
            if px.loadFromData(image_data):
                img_lbl.setPixmap(
                    px.scaled(_ALBUM_IMG, _ALBUM_IMG,
                              Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
                    .copy(0, 0, _ALBUM_IMG, _ALBUM_IMG)
                )
        layout.addWidget(img_lbl)

        name_lbl = QLabel(name)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet("color:#ddd; font-size:12px; font-weight:600; background:transparent;")
        name_lbl.setFixedWidth(_ALBUM_CARD_W)
        layout.addWidget(name_lbl)
        if year:
            year_lbl = QLabel(str(year))
            year_lbl.setStyleSheet("color:#666; font-size:11px; background:transparent;")
            layout.addWidget(year_lbl)
        layout.addStretch()

    def set_cover(self, data: bytes) -> None:
        """Update the album art after an on-demand fetch completes."""
        if not data or not hasattr(self, '_img_lbl'):
            return
        px = QPixmap()
        if px.loadFromData(data):
            self._img_lbl.setPixmap(
                px.scaled(_ALBUM_IMG, _ALBUM_IMG,
                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
                .copy(0, 0, _ALBUM_IMG, _ALBUM_IMG)
            )

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._album_data)
        super().mousePressEvent(event)


def _classify_album(album: dict) -> str:
    """Return 'album', 'ep', 'single', or 'other' for a Subsonic album dict.

    Uses OpenSubsonic ``releaseTypes`` / ``isCompilation`` when present, then
    falls back to name-keyword heuristics and finally to songCount.
    """
    import re as _re

    release_types = album.get("releaseTypes") or []
    if isinstance(release_types, str):
        release_types = [release_types]
    types_lower = {t.lower() for t in release_types}

    name  = album.get("name", "").lower()
    genre = (album.get("genre") or "").lower()

    # Soundtrack / compilation (checked first — highest priority)
    if album.get("isCompilation") or "compilation" in types_lower or "compilation" in name:
        return "other"
    if "soundtrack" in types_lower or "soundtrack" in name or "soundtrack" in genre:
        return "other"

    # Single
    if "single" in types_lower:
        return "single"

    # EP — releaseTypes field or name ends with "EP" as a standalone word
    if "ep" in types_lower or _re.search(r'\bep\b', name):
        return "ep"

    # Explicit album via releaseTypes
    if "album" in types_lower:
        return "album"

    # Fallback: no releaseTypes present — use songCount heuristic
    song_count = album.get("songCount") or 0
    if song_count == 1:
        return "single"
    if 2 <= song_count <= 4:
        return "ep"
    return "album"


def _section_heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#fff; font-size:16px; font-weight:700; background:transparent;")
    return lbl


def _sub_heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color:#bbb; font-size:14px; font-weight:700; letter-spacing:0.04em;"
        "background:transparent;"
    )
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color:#2a2a2e; background:#2a2a2e;")
    line.setFixedHeight(1)
    return line
