"""Custom sidebar widget.

Structure
---------
[Browse]            nav button
[Queue]             nav button
─── PINNED ─────    section header (hidden until at least one pin)
[pin items …]       artist / album / playlist / track chips
─── PLAYLISTS ───   section header
[playlist items …]  loaded from Subsonic getPlaylists

Signals
-------
nav_changed(str)                 — "Browse" or "Queue"
playlist_clicked(str, str)       — server id (or __import__name), display name
pin_item_clicked(dict)           — pin dict {type, id, name, …}
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from src.music_player.logging import get_logger
from src.music_player.ui.glyphs import ADD, CLOUD, FOLDER, MDL2_FAMILY_CSS, MDL2_FONT, PLAY, SHUFFLE
from src.music_player.ui.pins import load_pins, pins_changed, remove_pin

logger = get_logger(__name__)

_BG       = "#111114"
_BG_HOV   = "#1a1a1e"
_BG_SEL   = "#1e1e22"
_TEXT     = "#ccc"
_TEXT_DIM = "#666"
_ACCENT   = "#2dd4bf"


def _fmt_subtitle(song_count: int, duration: int) -> str:
    parts: list[str] = []
    if song_count:
        parts.append(f"{song_count} {'song' if song_count == 1 else 'songs'}")
    if duration > 0:
        h, rem = divmod(duration, 3600)
        m, s   = divmod(rem, 60)
        parts.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
    return "  ·  ".join(parts)


_NAME_MAX_CHARS = 80
_FADE_PX        = 28   # gradient width in pixels


class _FadingLabel(QLabel):
    """QLabel that paints a right-edge fade gradient when text overflows."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._fade_color = QColor(_BG)

    def set_fade_color(self, css: str) -> None:
        self._fade_color = QColor(css)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        fm = self.fontMetrics()
        if fm.horizontalAdvance(self.text()) > self.contentsRect().width():
            from PyQt6.QtGui import QPainter
            p = QPainter(self)
            x = self.width() - _FADE_PX
            grad = QLinearGradient(x, 0, self.width(), 0)
            transparent = QColor(self._fade_color)
            transparent.setAlpha(0)
            grad.setColorAt(0.0, transparent)
            grad.setColorAt(1.0, self._fade_color)
            p.fillRect(x, 0, _FADE_PX, self.height(), grad)
            p.end()


class _PlaylistItem(QWidget):
    """Sidebar row: 44×44 thumbnail + playlist name + song-count/duration subtitle."""

    clicked                = pyqtSignal()
    context_menu_requested = pyqtSignal(object)   # QPoint (global)
    play_requested         = pyqtSignal()
    shuffle_requested      = pyqtSignal()
    append_requested       = pyqtSignal()

    _H = 56   # fixed row height

    def __init__(self, name: str, pl_id: str, source: str,
                 song_count: int = 0, duration: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._pl_name   = name
        self._pl_id     = pl_id
        self._pl_source = source
        self._active    = False
        self._hover     = False

        self.setFixedHeight(self._H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_bg()

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        # Thumbnail (44×44, rounded, shows glyph until image loads)
        self._thumb = QLabel()
        self._thumb.setFixedSize(44, 44)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setFont(QFont(MDL2_FONT, 16))
        self._thumb.setText(CLOUD if source == "server" else FOLDER)
        self._thumb.setStyleSheet(
            f"QLabel{{background:#1e1e22;border-radius:4px;color:#555;"
            f"font-family:{MDL2_FAMILY_CSS};}}"
        )
        row.addWidget(self._thumb)

        # Name + subtitle
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 2, 0, 2)

        display_name = name if len(name) <= _NAME_MAX_CHARS else name[:_NAME_MAX_CHARS]
        self._name_lbl = _FadingLabel(display_name)
        self._name_lbl.setStyleSheet("color:#ccc;font-size:13px;background:transparent;")
        self._name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._sub_lbl = QLabel(_fmt_subtitle(song_count, duration))
        self._sub_lbl.setStyleSheet("color:#555;font-size:11px;background:transparent;")
        self._sub_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        text_col.addStretch()
        text_col.addWidget(self._name_lbl)
        text_col.addWidget(self._sub_lbl)
        text_col.addStretch()

        row.addLayout(text_col, stretch=1)

        # Hover action buttons (hidden until mouse enters)
        _ab_btn = (
            f"QPushButton{{background:transparent;color:#999;border:none;"
            f"border-radius:3px;font-family:{MDL2_FAMILY_CSS};}}"
            "QPushButton:hover{background:#2a2a2e;color:#fff;}"
        )
        self._action_bar = QWidget()
        self._action_bar.setStyleSheet("background:transparent;")
        ab_row = QHBoxLayout(self._action_bar)
        ab_row.setContentsMargins(0, 0, 0, 0)
        ab_row.setSpacing(2)
        for icon, tip, sig in (
            (PLAY,    "Play now",       self.play_requested),
            (SHUFFLE, "Shuffle play",   self.shuffle_requested),
            (ADD,     "Add to queue",   self.append_requested),
        ):
            btn = QPushButton(icon)
            btn.setFixedSize(22, 22)
            btn.setFont(QFont(MDL2_FONT, 9))
            btn.setToolTip(tip)
            btn.setStyleSheet(_ab_btn)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(sig)
            ab_row.addWidget(btn)
        self._action_bar.setVisible(False)
        row.addWidget(self._action_bar)

    # ── public API ────────────────────────────────────────────────────

    def set_image(self, data: bytes) -> None:
        if not data:
            return
        px = QPixmap()
        if not px.loadFromData(data) or px.isNull():
            return
        scaled = px.scaled(
            44, 44,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ).copy(0, 0, 44, 44)
        self._thumb.setText("")
        self._thumb.setPixmap(scaled)
        self._thumb.setStyleSheet("QLabel{border-radius:4px;}")

    def update_subtitle(self, song_count: int, duration: int) -> None:
        self._sub_lbl.setText(_fmt_subtitle(song_count, duration))

    def refresh_image(self) -> None:
        """Re-check image_store and update thumbnail if data is now available."""
        import src.music_player.image_store as image_store
        key = (f"playlist:{self._pl_id}" if self._pl_id
               else f"playlist_import:{self._pl_name}")
        data = image_store.get(key)
        if data:
            self.set_image(data)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply_bg()
        self._name_lbl.setStyleSheet(
            f"color:{'#fff' if active else '#ccc'};font-size:13px;background:transparent;"
        )

    # ── internals ─────────────────────────────────────────────────────

    def _apply_bg(self) -> None:
        if self._active:
            bg = _BG_SEL
        elif self._hover:
            bg = _BG_HOV
        else:
            bg = _BG   # actual colour so fade gradient matches
        self.setStyleSheet(f"background:{bg}; border-radius:6px;")
        if hasattr(self, "_name_lbl"):
            self._name_lbl.set_fade_color(bg)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hover = True
        if not self._active:
            self._apply_bg()
        self._action_bar.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        if not self._active:
            self._apply_bg()
        self._action_bar.setVisible(False)
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.context_menu_requested.emit(event.globalPosition().toPoint())


class SidebarWidget(QWidget):
    nav_changed      = pyqtSignal(str)
    playlist_clicked = pyqtSignal(str, str)   # server_id, name
    pin_item_clicked = pyqtSignal(dict)
    playlist_play    = pyqtSignal(str, str)   # pl_id, name
    playlist_shuffle = pyqtSignal(str, str)
    playlist_append  = pyqtSignal(str, str)

    _NAV_ITEMS = ["Browse", "Queue"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(480)
        self.setStyleSheet(f"background:{_BG};")

        self._active_nav  = "Browse"
        self._nav_btns:   dict[str, QPushButton]  = {}
        self._pin_section: QWidget | None          = None
        self._pin_list:    QWidget | None          = None
        self._pl_list:     QWidget | None          = None
        self._pl_btns:     dict[str, _PlaylistItem] = {}   # name → item
        self._active_pl:   str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border:none; background:transparent;")

        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 12, 8, 12)
        self._layout.setSpacing(2)

        self._build_nav()
        self._build_pinned_section()
        self._build_playlists_section()
        self._layout.addStretch()

        scroll.setWidget(self._content)
        outer.addWidget(scroll)

        pins_changed().changed.connect(self._refresh_pins)

    # ── nav ───────────────────────────────────────────────────────────

    def _build_nav(self) -> None:
        for name in self._NAV_ITEMS:
            btn = self._nav_btn(name)
            self._nav_btns[name] = btn
            self._layout.addWidget(btn)
        self._set_active("Browse")

    def _nav_btn(self, name: str) -> QPushButton:
        btn = QPushButton(name)
        btn.setFixedHeight(36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(self._nav_style(False))
        btn.clicked.connect(lambda _, n=name: self._on_nav(n))
        return btn

    def _nav_style(self, active: bool) -> str:
        bg    = _BG_SEL if active else "transparent"
        color = "#fff" if active else _TEXT
        return (
            f"QPushButton{{background:{bg};color:{color};border:none;"
            "border-radius:6px;padding:0 12px;font-size:14px;"
            f"text-align:left;}}"
            f"QPushButton:hover{{background:{_BG_HOV};color:#fff;}}"
        )

    def _on_nav(self, name: str) -> None:
        self._set_active(name)
        self.nav_changed.emit(name)

    def _set_active(self, name: str) -> None:
        self._active_nav = name
        for n, btn in self._nav_btns.items():
            btn.setStyleSheet(self._nav_style(n == name))

    def set_active_nav(self, name: str) -> None:
        """Called externally to sync active state without emitting signal."""
        self._set_active(name)

    # ── pinned section ────────────────────────────────────────────────

    def _build_pinned_section(self) -> None:
        self._pin_section = QWidget()
        self._pin_section.setStyleSheet("background:transparent;")
        pl = QVBoxLayout(self._pin_section)
        pl.setContentsMargins(0, 8, 0, 0)
        pl.setSpacing(2)

        hdr = _section_label("PINNED")
        pl.addWidget(hdr)

        self._pin_list = QWidget()
        self._pin_list.setStyleSheet("background:transparent;")
        self._pin_list_layout = QVBoxLayout(self._pin_list)
        self._pin_list_layout.setContentsMargins(0, 0, 0, 0)
        self._pin_list_layout.setSpacing(2)
        pl.addWidget(self._pin_list)

        self._layout.addWidget(self._pin_section)
        self._refresh_pins()

    def _refresh_pins(self) -> None:
        while self._pin_list_layout.count():
            item = self._pin_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        pins = load_pins()
        self._pin_section.setVisible(bool(pins))

        for pin in pins:
            btn = self._pin_item_btn(pin)
            self._pin_list_layout.addWidget(btn)

    def _pin_item_btn(self, pin: dict) -> QPushButton:
        icon = {"artist": "", "album": "",
                "playlist": "", "track": ""}.get(pin.get("type", ""), "")
        btn = QPushButton(f"{icon}  {pin.get('name', '?')}")
        btn.setFixedHeight(32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{_TEXT};"
            f"font-family:{MDL2_FAMILY_CSS};border:none;border-radius:6px;"
            "padding:0 8px;font-size:13px;text-align:left;}"
            f"QPushButton:hover{{background:{_BG_HOV};color:#fff;}}"
        )
        btn.clicked.connect(lambda _, p=pin: self.pin_item_clicked.emit(p))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, p=pin: self._pin_context_menu(btn, p, pos)
        )
        return btn

    def _pin_context_menu(self, btn: QPushButton, pin: dict, pos) -> None:
        menu = QMenu(btn)
        menu.setStyleSheet(
            f"QMenu{{background:#1a1a1e;color:#ddd;border:1px solid #2a2a2e;"
            f"font-family:{MDL2_FAMILY_CSS};}}"
            "QMenu::item{padding:6px 18px;}"
            "QMenu::item:selected{background:#2dd4bf;color:#000;}"
        )
        unpin = menu.addAction("Unpin from sidebar")
        if menu.exec(btn.mapToGlobal(pos)) == unpin:
            remove_pin(pin.get("type", ""), pin.get("id", ""))

    # ── playlists section ─────────────────────────────────────────────

    def _build_playlists_section(self) -> None:
        self._pl_section = QWidget()
        self._pl_section.setStyleSheet("background:transparent;")
        sec_layout = QVBoxLayout(self._pl_section)
        sec_layout.setContentsMargins(0, 8, 0, 0)
        sec_layout.setSpacing(2)

        sec_layout.addWidget(_section_label("PLAYLISTS"))

        self._pl_list = QWidget()
        self._pl_list.setStyleSheet("background:transparent;")
        self._pl_list_layout = QVBoxLayout(self._pl_list)
        self._pl_list_layout.setContentsMargins(0, 0, 0, 0)
        self._pl_list_layout.setSpacing(2)
        sec_layout.addWidget(self._pl_list)

        self._layout.addWidget(self._pl_section)

        # Imported playlists — instant from local DB
        from src.music_player.repository.playlist_db import load_all as db_load_all
        for row in db_load_all():
            matched  = row.get("matched", [])
            raw      = row.get("raw", [])
            count    = len(matched)
            duration = sum(r.get("duration", 0) for r in raw if r)
            self._add_playlist_item(row["name"], "", source="import",
                                    song_count=count, duration=duration)

        # Server playlists — async
        from src.music_player.ui.workers.playlists import LoadPlaylistsWorker
        w = LoadPlaylistsWorker(parent=self)
        w.playlists_loaded.connect(self._on_playlists_loaded)
        w.start()

    def add_imported_playlist(self, name: str) -> None:
        """Called after a new import finishes."""
        self._add_playlist_item(name, "", source="import")

    def _on_playlists_loaded(self, playlists: list) -> None:
        for pl in playlists:
            self._add_playlist_item(
                pl.get("name", "?"),
                pl.get("id", ""),
                source     = "server",
                song_count = pl.get("songCount", 0),
                duration   = pl.get("duration", 0),
                cover_art  = pl.get("coverArt", ""),
            )

    def _add_playlist_item(self, name: str, pl_id: str, source: str = "server",
                            song_count: int = 0, duration: int = 0,
                            cover_art: str = "") -> None:
        item = _PlaylistItem(name, pl_id, source, song_count, duration, parent=self)
        item.clicked.connect(
            lambda n=name, pid=pl_id, s=source: self._on_playlist(pid, n, s)
        )
        item.context_menu_requested.connect(
            lambda gpos, pid=pl_id, n=name, it=item:
                self._playlist_context_menu(it, pid, n, gpos)
        )
        item.play_requested.connect(
            lambda pid=pl_id, n=name: self.playlist_play.emit(pid, n)
        )
        item.shuffle_requested.connect(
            lambda pid=pl_id, n=name: self.playlist_shuffle.emit(pid, n)
        )
        item.append_requested.connect(
            lambda pid=pl_id, n=name: self.playlist_append.emit(pid, n)
        )
        self._pl_list_layout.addWidget(item)
        self._pl_btns[name] = item

        # Populate thumbnail — check cache first, then fetch async
        import src.music_player.image_store as image_store
        cache_key = f"playlist:{pl_id}" if pl_id else f"playlist_import:{name}"
        cached = image_store.get(cache_key)
        if cached:
            item.set_image(cached)
        elif cover_art:
            from src.music_player.ui.workers.image_loader import AlbumCoverLoader, _launch
            loader = AlbumCoverLoader(cover_art)
            loader.loaded.connect(lambda data, it=item: it.set_image(data))
            _launch(loader)

    # ── selection ─────────────────────────────────────────────────────

    def set_active_playlist(self, name: str) -> None:
        """Highlight the named playlist row and deactivate the previous one."""
        if self._active_pl and self._active_pl in self._pl_btns:
            self._pl_btns[self._active_pl].set_active(False)
        self._active_pl = name
        if name and name in self._pl_btns:
            item = self._pl_btns[name]
            item.set_active(True)
            item.refresh_image()

    def refresh_playlist_thumbnails(self) -> None:
        """Refresh all playlist thumbnails from image_store (call after startup cache loads)."""
        for item in self._pl_btns.values():
            item.refresh_image()

    # ── mutation (create / rename / delete) ───────────────────────────

    def remove_playlist(self, name: str, source: str) -> None:
        item = self._pl_btns.pop(name, None)
        if item:
            self._pl_list_layout.removeWidget(item)
            item.deleteLater()
            return
        # Fallback sweep
        for i in range(self._pl_list_layout.count()):
            w = self._pl_list_layout.itemAt(i)
            w = w.widget() if w else None
            if w and getattr(w, "_pl_name", None) == name:
                self._pl_list_layout.removeWidget(w)
                w.deleteLater()
                break

    def add_server_playlist(self, name: str, pl_id: str) -> None:
        self._add_playlist_item(name, pl_id, source="server")

    def rename_playlist(self, old_name: str, new_name: str, source: str, pl_id: str = "") -> None:
        to_remove = []
        for i in range(self._pl_list_layout.count()):
            w = self._pl_list_layout.itemAt(i)
            w = w.widget() if w else None
            if w and getattr(w, "_pl_name", None) == old_name:
                to_remove.append(w)
        for w in to_remove:
            self._pl_list_layout.removeWidget(w)
            w.deleteLater()
            self._pl_btns.pop(old_name, None)
        self._add_playlist_item(new_name, pl_id, source)

    # ── internal slot ─────────────────────────────────────────────────

    def _on_playlist(self, pl_id: str, name: str, source: str = "server") -> None:
        self._set_active("")          # deselect Browse / Queue nav
        self.set_active_playlist(name)
        self.playlist_clicked.emit(
            pl_id if source == "server" else f"__import__{name}", name
        )

    def _playlist_context_menu(
        self, item: _PlaylistItem, pl_id: str, name: str, global_pos
    ) -> None:
        from src.music_player.ui.pins import add_pin
        menu = QMenu(item)
        menu.setStyleSheet(
            f"QMenu{{background:#1a1a1e;color:#ddd;border:1px solid #2a2a2e;"
            f"font-family:{MDL2_FAMILY_CSS};}}"
            "QMenu::item{padding:6px 18px;}"
            "QMenu::item:selected{background:#2dd4bf;color:#000;}"
        )
        pin_act = menu.addAction("Pin to sidebar")
        if menu.exec(global_pos) == pin_act:
            add_pin({"type": "playlist", "id": pl_id, "name": name})


# ── helpers ───────────────────────────────────────────────────────────

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{_TEXT_DIM};font-size:11px;font-weight:700;"
        "letter-spacing:0.06em;padding:4px 8px 2px 8px;background:transparent;"
    )
    return lbl
