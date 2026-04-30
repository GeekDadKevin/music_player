"""Browse page (sidebar: Browse) — tabbed library view.

Tabs
----
Highlights       working — last 5 played artists or 5 random
Favorite Tracks  stub (hearted tracks — wired when heart toggle is implemented)
Most Played      working — top songs from play_counts table
Albums           stub
Artists          stub — shows ArtistCard grid; clicking navigates to ArtistDetailPage
Listening History stub

Clicking any ArtistCard from any tab pushes an ArtistDetailPage onto the
internal stack; the back button returns to the tab view.
"""

import random

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.repository.play_history_db import (
    get_play_history, get_recent_artists, get_top_artist_for_genre,
    get_top_artists, get_top_genres, get_top_songs,
)
from src.music_player.ui.app_settings import load_settings, settings_signals
from src.music_player.ui.components.artist_detail_page import ArtistDetailPage
from src.music_player.ui.glyphs import (
    CHEVRON_LEFT, CHEVRON_RIGHT, MDL2_FAMILY_CSS, MDL2_FONT, SHUFFLE,
)

logger = get_logger(__name__)

_TABS = [
    "Highlights",
    "Favorite Tracks",
    "Most Played",
    "Artists",
    "Genres",
    "Listening History",
]

_HERO_D    = 130   # artist card image diameter in Highlights row
_CARD_W    = 160   # artist card widget width
_PAGE_SIZE = 25    # rows per page for track/history lists


# ── shared pagination bar ─────────────────────────────────────────────

class _PaginationBar(QWidget):
    """Prev/Next chevron bar — same visual style as the album/artist grids."""

    page_changed = pyqtSignal(int)   # emits the new 0-based page index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page  = 0
        self._total = 1
        self.setStyleSheet("background:transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 8)
        row.setSpacing(8)
        row.addStretch()

        _btn_style = (
            "QPushButton{background:transparent;color:#555;border:none;}"
            "QPushButton:hover{color:#fff;}"
            "QPushButton:disabled{color:#2a2a2e;}"
        )

        self._prev = QPushButton(CHEVRON_LEFT)
        self._prev.setFont(QFont(MDL2_FONT, 11))
        self._prev.setFixedSize(28, 28)
        self._prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev.setStyleSheet(_btn_style)
        self._prev.clicked.connect(self._go_prev)

        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#555; font-size:12px; background:transparent;")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setFixedWidth(56)

        self._next = QPushButton(CHEVRON_RIGHT)
        self._next.setFont(QFont(MDL2_FONT, 11))
        self._next.setFixedSize(28, 28)
        self._next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next.setStyleSheet(_btn_style)
        self._next.clicked.connect(self._go_next)

        row.addWidget(self._prev)
        row.addWidget(self._lbl)
        row.addWidget(self._next)

    def set_state(self, total_pages: int, page: int = 0) -> None:
        self._page  = page
        self._total = total_pages
        self._lbl.setText(f"{page + 1} / {total_pages}")
        self._prev.setEnabled(page > 0)
        self._next.setEnabled(page < total_pages - 1)
        visible = total_pages > 1
        for w in (self._prev, self._lbl, self._next):
            w.setVisible(visible)

    def reset(self) -> None:
        self._page = 0
        self.set_state(1, 0)

    def _go_prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self.set_state(self._total, self._page)
            self.page_changed.emit(self._page)

    def _go_next(self) -> None:
        if self._page < self._total - 1:
            self._page += 1
            self.set_state(self._total, self._page)
            self.page_changed.emit(self._page)


# ── main page ─────────────────────────────────────────────────────────

class LibraryPage(QWidget):
    """Browse page with internal stack: [tab view | artist detail | genre detail]."""

    playlist_selected = pyqtSignal(str, str)   # pl_id, name — forwarded to app.py

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tab_btns: list[QPushButton] = []
        self.setStyleSheet("background:#0d0d10;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Internal navigation stack
        self._nav = QStackedWidget()

        # Page 0 — tab view
        self._main = self._build_main()
        self._nav.addWidget(self._main)

        # Page 1 — artist detail
        self._detail = ArtistDetailPage()
        self._detail.back_clicked.connect(lambda: self._nav.setCurrentIndex(0))
        self._nav.addWidget(self._detail)

        # Page 2 — genre detail
        self._genre_detail = GenreDetailPage()
        self._genre_detail.back_clicked.connect(lambda: self._nav.setCurrentIndex(0))
        self._nav.addWidget(self._genre_detail)

        # Page 3 — album detail (reached via nav bus from any track table)
        self._album_detail = AlbumDetailPage()
        self._album_detail.back_clicked.connect(lambda: self._nav.setCurrentIndex(0))
        self._nav.addWidget(self._album_detail)

        outer.addWidget(self._nav)
        settings_signals().changed.connect(self._on_settings_changed)

        # Wire nav bus — any TrackTable or player bar can trigger navigation
        from src.music_player.ui.navigation import nav_bus
        nav_bus().show_artist.connect(self._on_nav_artist)
        nav_bus().show_album.connect(self._on_nav_album)

    # ── build main view ───────────────────────────────────────────────

    def _build_main(self) -> QWidget:
        main = QWidget()
        main.setStyleSheet("background:transparent;")
        root = QVBoxLayout(main)
        root.setContentsMargins(24, 20, 24, 0)
        root.setSpacing(0)

        # Heading + search + shuffle
        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        heading = QLabel("Browse")
        f = QFont(); f.setPointSize(26); f.setWeight(QFont.Weight.Bold)
        heading.setFont(f)
        heading.setStyleSheet("color:#fff; background:transparent;")
        top_row.addWidget(heading)

        from PyQt6.QtWidgets import QLineEdit
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Search library…")
        self._search_bar.setFixedHeight(32)
        self._search_bar.setMaximumWidth(340)
        self._search_bar.setStyleSheet(
            "QLineEdit{background:#1a1a1e;color:#ddd;font-size:13px;"
            "padding:4px 14px;border-radius:16px;border:1px solid #2a2a2e;}"
            "QLineEdit:focus{border:1px solid #2dd4bf;}"
        )
        self._search_bar.returnPressed.connect(self._on_search)
        top_row.addWidget(self._search_bar)

        top_row.addStretch()
        self._shuffle_btn = self._make_shuffle_btn()
        top_row.addWidget(self._shuffle_btn)
        root.addLayout(top_row)
        root.addSpacing(16)

        # Tab bar
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)
        tab_row.setContentsMargins(0, 0, 0, 0)
        for i, name in enumerate(_TABS):
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, idx=i: self._select_tab(idx))
            btn.setStyleSheet(self._tab_style(i == 0))
            self._tab_btns.append(btn)
            tab_row.addWidget(btn)
        tab_row.addStretch()
        root.addLayout(tab_row)

        # Thin separator
        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#1e1e22;")
        root.addWidget(sep)
        root.addSpacing(4)

        # Content stack — order must match _TABS
        self._content = QStackedWidget()
        self._highlights = HighlightsTab()
        self._highlights.artist_selected.connect(self._show_artist)
        self._highlights.playlist_selected.connect(self.playlist_selected)
        self._highlights.genre_selected.connect(self._show_genre)
        self._content.addWidget(self._highlights)                  # Highlights
        self._fav_tab = FavoriteTracksTab()
        self._content.addWidget(self._fav_tab)                     # Favorite Tracks
        self._content.addWidget(MostPlayedTab())                   # Most Played
        self._artists_tab = ArtistsTab()
        self._artists_tab.artist_selected.connect(self._show_artist)
        self._content.addWidget(self._artists_tab)                 # Artists
        self._genres_tab = GenreTab()
        self._genres_tab.genre_selected.connect(self._show_genre)
        self._content.addWidget(self._genres_tab)                  # Genres
        self._content.addWidget(ListeningHistoryTab())             # Listening History
        root.addWidget(self._content, stretch=1)

        return main

    # ── navigation ────────────────────────────────────────────────────

    def _select_tab(self, idx: int) -> None:
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(self._tab_style(i == idx))
        self._content.setCurrentIndex(idx)

    def _show_artist(self, artist_data: dict) -> None:
        self._detail.load_artist(artist_data)
        self._nav.setCurrentIndex(1)

    def _show_genre(self, genre: str) -> None:
        self._genre_detail.load_genre(genre)
        self._nav.setCurrentIndex(2)

    @pyqtSlot(str)
    def _on_nav_artist(self, name: str) -> None:
        by_name = {a.get("name", ""): a for a in image_store.get_artists()}
        artist_data = by_name.get(name, {"name": name})
        self._show_artist(artist_data)
        # Switch to Browse if we're on a different top-level page
        from src.music_player.ui.navigation import nav_bus as _nb
        _ensure_browse_visible(self)

    @pyqtSlot(str, str, str)
    def _on_nav_album(self, album_id: str, album_name: str, artist: str) -> None:
        self._album_detail.load_album({"id": album_id, "name": album_name, "artist": artist})
        self._nav.setCurrentIndex(3)
        _ensure_browse_visible(self)

    # ── shuffle ───────────────────────────────────────────────────────

    def _make_shuffle_btn(self) -> QPushButton:
        color = load_settings().highlight_color
        btn = QPushButton(f"{SHUFFLE}  Shuffle my music")
        btn.setFont(QFont(MDL2_FONT, 11))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_shuffle_style(btn, color)
        btn.clicked.connect(self._on_shuffle)
        return btn

    def _apply_shuffle_style(self, btn: QPushButton, color: str) -> None:
        btn.setStyleSheet(
            f"QPushButton{{background:{color};color:#000;font-size:13px;"
            f"font-family:{MDL2_FAMILY_CSS};border:none;border-radius:20px;"
            "font-weight:700;padding:8px 20px;}"
            f"QPushButton:hover{{background:{color}cc;}}"
        )

    def _on_shuffle(self) -> None:
        self._shuffle_btn.setEnabled(False)
        from src.music_player.ui.workers.shuffle import ShuffleWorker
        self._shuffle_worker = ShuffleWorker(parent=self)
        self._shuffle_worker.done.connect(self._on_shuffle_done)
        self._shuffle_worker.start()

    @pyqtSlot(list)
    def _on_shuffle_done(self, tracks: list) -> None:
        self._shuffle_btn.setEnabled(True)
        if not tracks:
            logger.warning("Shuffle returned no tracks")
            return
        from src.music_player.queue import get_queue
        from src.music_player.ui.components.playback_bridge import get_bridge
        get_queue().set_queue(tracks, start=0)
        get_bridge().play_track(tracks[0])
        get_bridge().queue_changed.emit()

    def _on_search(self) -> None:
        text = self._search_bar.text().strip()
        if not text:
            return
        from src.music_player.ui.components.search_dialog import SearchResultsDialog
        dlg = SearchResultsDialog(text, parent=self)
        dlg.exec()
        self._search_bar.clear()

    def _on_settings_changed(self) -> None:
        color = load_settings().highlight_color
        self._apply_shuffle_style(self._shuffle_btn, color)
        for i, btn in enumerate(self._tab_btns):
            btn.setStyleSheet(self._tab_style(btn.isChecked()))

    def _tab_style(self, active: bool) -> str:
        color = load_settings().highlight_color
        border = f"border-bottom:2px solid {color};" if active else "border-bottom:2px solid transparent;"
        text   = "#fff" if active else "#666"
        return (
            f"QPushButton{{background:transparent;color:{text};font-size:13px;"
            f"border:none;{border}padding:8px 16px 6px 16px;}}"
            "QPushButton:hover{color:#fff;}"
        )


# ── Highlights tab ────────────────────────────────────────────────────

_GENRE_PALETTE = [
    "#1db954", "#2dd4bf", "#7c3aed", "#db2777", "#ea580c",
    "#0284c7", "#65a30d", "#d97706", "#9333ea", "#0891b2",
]


class HighlightsTab(QWidget):
    artist_selected   = pyqtSignal(dict)
    playlist_selected = pyqtSignal(str, str)   # pl_id, name
    genre_selected    = pyqtSignal(str)         # genre name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._built = False
        self.setStyleSheet("background:transparent;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._built:
            self._built = True
            self._initial_build()
        else:
            self._refresh()

    def _initial_build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:transparent;")
        outer.addWidget(scroll)

        self._content_w = QWidget()
        self._content_w.setStyleSheet("background:transparent;")
        self._root = QVBoxLayout(self._content_w)
        self._root.setContentsMargins(0, 0, 0, 8)
        self._root.setSpacing(8)
        scroll.setWidget(self._content_w)

        # Placeholder containers — filled by _refresh()
        self._artist_row_layout  = None
        self._playlist_row_layout = None
        self._genre_row_layout   = None

        self._refresh()
        self._root.addStretch()   # pins sections to the top regardless of window height

        # Live update when a new track starts playing
        from src.music_player.ui.components.playback_bridge import get_bridge
        get_bridge().track_changed.connect(self._on_track_changed)

    def _on_track_changed(self, _track: dict) -> None:
        if self.isVisible():
            self._refresh()

    def _refresh(self) -> None:
        self._rebuild_section("_artist_section",  self._build_artist_section)
        self._rebuild_section("_playlist_section", self._build_playlist_section)
        self._rebuild_section("_genre_section",   self._build_genre_section)

    # Each section is a QWidget stored as an attribute; we replace it on refresh.
    def _rebuild_section(self, attr: str, builder) -> None:
        old = getattr(self, attr, None)
        new = builder()
        setattr(self, attr, new)
        if old is not None:
            idx = self._root.indexOf(old)
            self._root.takeAt(idx)
            old.deleteLater()
            self._root.insertWidget(idx, new)
        else:
            self._root.addWidget(new)

    # ── section builders ──────────────────────────────────────────────

    def _build_artist_section(self) -> QWidget:
        top_artists = get_top_artists(limit=10)
        if top_artists:
            by_name = {a.get("name", ""): a for a in image_store.get_artists()}
            artists = [by_name.get(r["artist"], {"name": r["artist"]}) for r in top_artists]
            counts  = {r["artist"]: r["play_count"] for r in top_artists}
        else:
            all_a   = image_store.get_artists()
            artists = random.sample(all_a, min(10, len(all_a)))
            counts  = {}

        def factory(a: dict) -> QWidget:
            card = _ArtistCard(a, size=_HERO_D, play_count=counts.get(a.get("name", ""), 0))
            card.clicked.connect(self.artist_selected)
            return card

        return self._paged_section("Top Artists", artists, factory, item_width=_HERO_D + 30)

    def _build_playlist_section(self) -> QWidget:
        playlists = sorted(
            image_store.get_playlists(),
            key=lambda p: p.get("songCount", 0), reverse=True,
        )[:10]

        def factory(pl: dict) -> QWidget:
            card = _PlaylistCard(pl)
            card.clicked.connect(self.playlist_selected)
            return card

        return self._paged_section("Top Playlists", playlists, factory, item_width=160)

    def _build_genre_section(self) -> QWidget:
        genres = get_top_genres(limit=10)

        def factory(item: tuple) -> QWidget:
            idx, g = item
            color  = _GENRE_PALETTE[idx % len(_GENRE_PALETTE)]
            artist = get_top_artist_for_genre(g["genre"])
            img    = image_store.get(f"artist:{artist.lower()}") if artist else None
            card   = _GenreCard(g["genre"], g["play_count"], color, img, count_label="plays")
            card.clicked.connect(self.genre_selected)
            return card

        indexed = list(enumerate(genres))
        return self._paged_section("Top Genres", indexed, factory, item_width=160)

    # ── layout helper ─────────────────────────────────────────────────

    def _paged_section(self, title: str, data: list, factory, item_width: int) -> QWidget:
        """Build a titled section backed by PaginatedGrid(rows=1) for uniform nav."""
        from src.music_player.ui.components.flow_grid import PaginatedGrid

        section = QWidget()
        section.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(0)

        lbl = QLabel(title)
        f = QFont(); f.setPointSize(14); f.setWeight(QFont.Weight.Bold)
        lbl.setFont(f)
        lbl.setStyleSheet("color:#fff; background:transparent;")
        layout.addWidget(lbl)

        if not data:
            empty = QLabel("Nothing here yet — play some music to populate this section.")
            empty.setStyleSheet("color:#444; font-size:12px; background:transparent;")
            layout.addWidget(empty)
            return section

        grid = PaginatedGrid(
            item_width=item_width, rows=1, spacing=16, margins=(0, 0, 0, 0),
        )
        grid.setStyleSheet("background:transparent;")
        grid.set_data(data, factory)
        layout.addWidget(grid)
        return section


# ── Favorite Tracks tab ───────────────────────────────────────────────

class FavoriteTracksTab(QWidget):
    """Hearted (starred) tracks from the server, sorted by play count desc."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._worker  = None
        self._all:    list[dict] = []
        self._page    = 0
        self._build_shell()

    def _build_shell(self) -> None:
        from src.music_player.ui.components.track_table import TrackTable
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        self._status = QLabel("Loading…")
        self._status.setStyleSheet("color:#888; font-size:13px; background:transparent;")
        root.addWidget(self._status)

        self._table = TrackTable()
        root.addWidget(self._table, stretch=1)

        self._pager = _PaginationBar()
        self._pager.page_changed.connect(self._go_page)
        root.addWidget(self._pager)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        from src.music_player.ui.workers.starred import LoadStarredWorker
        self._status.setText("Loading…")
        self._table.set_tracks([])
        self._pager.reset()
        self._worker = LoadStarredWorker(parent=self)
        self._worker.songs_loaded.connect(self._on_loaded)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    def _on_loaded(self, songs: list) -> None:
        if not songs:
            self._status.setText(
                "No hearted tracks yet — tap the heart in the player bar or star songs on your server."
            )
            return
        from src.music_player.repository.play_history_db import get_play_count
        for s in songs:
            s["_plays"] = get_play_count(s.get("id", ""))
        songs.sort(key=lambda s: s["_plays"], reverse=True)
        self._all  = songs
        self._page = 0
        self._render()

    def _render(self) -> None:
        import math
        total = max(1, math.ceil(len(self._all) / _PAGE_SIZE))
        start = self._page * _PAGE_SIZE
        self._table.set_tracks(self._all[start:start + _PAGE_SIZE])
        self._status.setText(f"{len(self._all)} track(s)")
        self._pager.set_state(total, self._page)

    @pyqtSlot(int)
    def _go_page(self, page: int) -> None:
        self._page = page
        self._render()


# ── Most Played tab ───────────────────────────────────────────────────

class MostPlayedTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._built = False
        self._all:  list[dict] = []
        self._page  = 0
        self.setStyleSheet("background:transparent;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._built:
            self._built = True
            self._build()
        else:
            self._reload()

    def _build(self) -> None:
        from src.music_player.ui.components.track_table import TrackTable
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:13px; background:transparent;")
        root.addWidget(self._status)

        self._table = TrackTable()
        root.addWidget(self._table, stretch=1)

        self._pager = _PaginationBar()
        self._pager.page_changed.connect(self._go_page)
        root.addWidget(self._pager)

        self._reload()

    def _reload(self) -> None:
        songs = get_top_songs(limit=500)
        if not songs:
            self._status.setText("Play some music first — tracks will appear here.")
            self._table.set_tracks([])
            self._pager.reset()
            return
        self._all  = songs
        self._page = 0
        self._render()

    def _render(self) -> None:
        import math
        total = max(1, math.ceil(len(self._all) / _PAGE_SIZE))
        start = self._page * _PAGE_SIZE
        self._table.set_tracks(self._all[start:start + _PAGE_SIZE])
        self._status.setText(f"{len(self._all)} track(s)")
        self._pager.set_state(total, self._page)

    @pyqtSlot(int)
    def _go_page(self, page: int) -> None:
        self._page = page
        self._render()


# ── Artists tab ───────────────────────────────────────────────────────

class ArtistsTab(QWidget):
    """Paginated 3-row grid of all artists."""

    artist_selected = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loaded = False
        self.setStyleSheet("background:transparent;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._build()

    def _build(self) -> None:
        from src.music_player.ui.components.artist_card import _CARD_W
        from src.music_player.ui.components.flow_grid import PaginatedGrid

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._grid = PaginatedGrid(
            item_width=_CARD_W, rows=3, spacing=8, margins=(0, 16, 0, 8)
        )
        self._grid.setStyleSheet("background:transparent;")
        root.addWidget(self._grid, stretch=1)

        artists = image_store.get_artists()
        self._grid.set_data(artists, self._make_card)

    def _make_card(self, artist: dict) -> QWidget:
        from src.music_player.ui.components.artist_card import ArtistCard
        name = artist.get("name", "")
        card = ArtistCard(name, artist_data=artist)
        data = image_store.get(f"artist:{name.lower()}")
        if data:
            card.set_image(data)
        else:
            from src.music_player.ui.workers.image_loader import ArtistImageLoader, _launch
            loader = ArtistImageLoader(name)
            loader.loaded.connect(card.set_image)
            _launch(loader)
        card.clicked.connect(self.artist_selected)
        return card


# ── shared artist card widget (used in Highlights) ────────────────────

def _hex_rgba(hex_color: str, alpha: float) -> str:
    """Convert '#RRGGBB' + float alpha [0-1] to 'rgba(r,g,b,a)' for Qt stylesheets."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.2f})"


class _GenreCard(QWidget):
    """Genre card: artist image background with dark gradient overlay and text."""

    clicked = pyqtSignal(str)   # genre name

    def __init__(self, genre: str, play_count: int, color: str,
                 image_data: bytes | None, count_label: str = "plays", parent=None) -> None:
        super().__init__(parent)
        self._genre  = genre
        self._plays  = f"{play_count:,} {count_label}"
        self._color  = color
        self._pixmap = None
        if image_data:
            from PyQt6.QtGui import QPixmap
            px = QPixmap()
            if px.loadFromData(image_data):
                self._pixmap = px
        self.setFixedSize(160, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._genre)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import (
            QColor, QLinearGradient, QPainter, QPainterPath, QPixmap,
        )
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # Rounded clip
        path = QPainterPath()
        path.addRoundedRect(0, 0, rect.width(), rect.height(), 8, 8)
        p.setClipPath(path)

        # Background: artist image or solid color
        if self._pixmap:
            scaled = self._pixmap.scaled(
                rect.width(), rect.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (scaled.width()  - rect.width())  // 2
            oy = (scaled.height() - rect.height()) // 2
            p.drawPixmap(0, 0, scaled, ox, oy, rect.width(), rect.height())
        else:
            h = self._color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            p.fillRect(rect, QColor(r, g, b, 60))

        # Dark gradient overlay so text is always readable
        grad = QLinearGradient(0, 0, 0, rect.height())
        grad.setColorAt(0.0, QColor(0, 0, 0, 60))
        grad.setColorAt(1.0, QColor(0, 0, 0, 200))
        p.fillRect(rect, grad)

        # Genre name
        h = self._color.lstrip("#")
        accent = QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        from PyQt6.QtGui import QFont
        f = QFont(); f.setPointSize(12); f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(accent)
        p.drawText(rect.adjusted(10, 0, -10, -28), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, self._genre)

        # Play count
        f2 = QFont(); f2.setPointSize(9)
        p.setFont(f2)
        p.setPen(QColor(180, 180, 180))
        p.drawText(rect.adjusted(10, 0, -10, -8), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, self._plays)

        p.end()


class _PlaylistCard(QWidget):
    """Clickable playlist card with cover art for the Highlights section."""

    clicked = pyqtSignal(str, str)   # pl_id, name

    def __init__(self, pl: dict, parent=None) -> None:
        super().__init__(parent)
        self._pl_id  = pl.get("id", "")
        self._name   = pl.get("name", "Playlist")
        cover_id     = pl.get("coverArt", "")
        self.setFixedSize(160, 220)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:#1a1a1e; border-radius:8px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Cover art
        self._art = QLabel()
        self._art.setFixedSize(144, 150)
        self._art.setStyleSheet("border-radius:4px; background:#2a2a2e;")
        lay.addWidget(self._art)

        n = QLabel(self._name)
        n.setWordWrap(True)
        n.setStyleSheet("color:#ddd; font-size:12px; font-weight:600; background:transparent;")
        lay.addWidget(n)

        # Load cover art — prefer uploaded/composite, then server coverArt
        uploaded = image_store.get(f"playlist:{self._pl_id}") if self._pl_id else None
        if uploaded:
            self._set_art(uploaded)
        elif cover_id:
            cached = image_store.get(f"album:{cover_id}")
            if cached:
                self._set_art(cached)
            else:
                from src.music_player.ui.workers.image_loader import AlbumCoverLoader, _launch
                loader = AlbumCoverLoader(cover_id)
                loader.loaded.connect(self._set_art)
                _launch(loader)

    def _set_art(self, data: bytes) -> None:
        if not data:
            return
        from PyQt6.QtGui import QPixmap
        px = QPixmap()
        if px.loadFromData(data):
            self._art.setPixmap(
                px.scaled(144, 150, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation).copy(0, 0, 144, 150)
            )
            self._art.setStyleSheet("border-radius:4px;")

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._pl_id, self._name)
        super().mousePressEvent(event)


class _ArtistCard(QWidget):
    """Circular artist card that emits clicked(artist_data)."""

    clicked = pyqtSignal(dict)

    def __init__(self, artist: dict, size: int = 130, play_count: int = -1, parent=None) -> None:
        super().__init__(parent)
        self._data = artist
        name = artist.get("name", "Unknown")
        self.setFixedWidth(size + 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        img = QLabel()
        img.setFixedSize(size, size)
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet(f"border-radius:{size//2}px; background:#2a2a2e;")

        data = image_store.get(f"artist:{name.lower()}")
        if data:
            _set_circle_image(img, data, size)
        else:
            from src.music_player.ui.workers.image_loader import ArtistImageLoader, _launch
            loader = ArtistImageLoader(name)
            loader.loaded.connect(lambda d, i=img, s=size: _set_circle_image(i, d, s))
            _launch(loader)
        layout.addWidget(img, alignment=Qt.AlignmentFlag.AlignHCenter)

        name_lbl = QLabel(name)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet(
            "color:#fff; font-size:13px; font-weight:600; background:transparent;"
        )
        layout.addWidget(name_lbl)

        # Use supplied play_count; fall back to DB only if not provided
        count = play_count if play_count >= 0 else _artist_play_count(name)
        if count > 0:
            cl = QLabel(f"{count:,} plays")
            cl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            cl.setStyleSheet("color:#666; font-size:11px; background:transparent;")
            layout.addWidget(cl)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._data)
        super().mousePressEvent(event)


def _artist_play_count(name: str) -> int:
    try:
        import sqlite3
        from pathlib import Path
        db = Path.home() / ".music-player" / "plays.db"
        if not db.exists():
            return 0
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT COALESCE(SUM(play_count),0) FROM play_counts WHERE artist=?", (name,)
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ── Listening History tab ─────────────────────────────────────────────

class ListeningHistoryTab(QWidget):
    """All recorded play events, newest first, with a relative timestamp."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._built = False
        self._all:  list[dict] = []
        self._page  = 0

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._built:
            self._built = True
            self._build()
        else:
            self._refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:13px; background:transparent;")
        root.addWidget(self._status)

        self._table = _HistoryTable()
        root.addWidget(self._table, stretch=1)

        self._pager = _PaginationBar()
        self._pager.page_changed.connect(self._go_page)
        root.addWidget(self._pager)

        self._refresh()

    def _refresh(self) -> None:
        entries = get_play_history(limit=5000)
        if not entries:
            self._status.setText(
                "Nothing here yet — plays are recorded after the minimum play time set in Settings."
            )
            self._table.set_entries([])
            self._pager.reset()
            return
        self._all  = entries
        self._page = 0
        self._render()

    def _render(self) -> None:
        import math
        total = max(1, math.ceil(len(self._all) / _PAGE_SIZE))
        start = self._page * _PAGE_SIZE
        self._table.set_entries(self._all[start:start + _PAGE_SIZE])
        self._status.setText(f"{len(self._all)} play event(s)")
        self._pager.set_state(total, self._page)

    @pyqtSlot(int)
    def _go_page(self, page: int) -> None:
        self._page = page
        self._render()


class _HistoryTable(QTableWidget):
    """Track listing for listening history — adds a Played column."""

    _HEADERS = ["#", "Title", "Artist", "Album", "Played"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[dict] = []

        self.setColumnCount(len(self._HEADERS))
        self.setHorizontalHeaderLabels(self._HEADERS)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setStyleSheet("""
            QTableWidget {
                background: #0d0d10;
                alternate-background-color: #111114;
                color: #ccc;
                border: none;
                font-size: 13px;
            }
            QTableWidget::item { padding: 0 8px; }
            QTableWidget::item:selected { background: #1db954; color: #fff; }
            QHeaderView::section {
                background: #0d0d10;
                color: #555;
                border: none;
                border-bottom: 1px solid #1e1e22;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.05em;
            }
        """)
        self.doubleClicked.connect(self._on_double_click)

    def set_entries(self, entries: list[dict]) -> None:
        self._entries = entries
        self.setRowCount(len(entries))
        for i, e in enumerate(entries):
            cells = [
                (str(i + 1),                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                (e.get("title", ""),                Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                (e.get("artist", ""),               Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                (e.get("album", ""),                Qt.AlignmentFlag.AlignLeft  | Qt.AlignmentFlag.AlignVCenter),
                (_relative_time(e.get("played_at","")), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            ]
            for col, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.setItem(i, col, item)
        self.resizeRowsToContents()

    def _on_double_click(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._entries):
            from src.music_player.ui.components.playback_bridge import get_bridge
            from src.music_player.queue import get_queue
            entry = self._entries[row]
            # Build a playable track list from the full history for prev/next
            get_queue().set_queue(self._entries, start=row)
            get_bridge().play_track(entry)


def _relative_time(played_at: str) -> str:
    """Format a stored datetime string as a human-readable relative time."""
    if not played_at:
        return ""
    try:
        from datetime import datetime
        dt  = datetime.fromisoformat(played_at)
        now = datetime.now()
        s   = (now - dt).total_seconds()
        if s < 60:      return "Just now"
        if s < 3600:    return f"{int(s / 60)}m ago"
        if s < 86400:   return f"{int(s / 3600)}h ago"
        days = int(s / 86400)
        if days == 1:   return "Yesterday"
        if days < 7:    return f"{days}d ago"
        if dt.year == now.year:
            return dt.strftime("%b %d").lstrip("0").replace(" 0", " ")
        return dt.strftime("%b %d %Y")
    except Exception:
        return played_at[:10] if len(played_at) >= 10 else played_at


# ── Albums tab ────────────────────────────────────────────────────────

# ── Queue tab ─────────────────────────────────────────────────────────

class QueueTab(QWidget):
    """Queue as a standard TrackTable — double-click any row to jump to that track."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._build_ui()
        from src.music_player.ui.components.playback_bridge import get_bridge
        get_bridge().track_changed.connect(self._on_track_changed)
        get_bridge().queue_changed.connect(self.refresh)

    def _build_ui(self) -> None:
        from src.music_player.ui.components.track_table import TrackTable
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(4)
        self._status = QLabel("")
        self._status.setStyleSheet("color:#555; font-size:12px; background:transparent;")
        root.addWidget(self._status)
        self._table = TrackTable()
        root.addWidget(self._table, stretch=1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    @pyqtSlot(dict)
    def _on_track_changed(self, track: dict) -> None:
        self.refresh()

    def refresh(self) -> None:
        from src.music_player.queue import get_queue
        q = get_queue()
        if not q.tracks:
            self._status.setText("Queue is empty")
            self._table.set_tracks([])
            return
        pos = q.current_index
        count = len(q.tracks)
        self._status.setText(
            f"{count} track(s)  ·  playing #{pos + 1}" if 0 <= pos < count else f"{count} track(s)"
        )
        self._table.set_tracks(q.tracks)
        if 0 <= pos < count:
            tid = q.tracks[pos].get("id", "")
            if tid:
                self._table.highlight_track_id(tid)


# ── Genre tab ──────────────────────────────────────────────────────────

class GenreTab(QWidget):
    """Paginated grid of all library genres — clicking opens GenreDetailPage."""

    genre_selected = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loaded = False
        self.setStyleSheet("background:transparent;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._build()

    def _build(self) -> None:
        from src.music_player.ui.components.flow_grid import PaginatedGrid
        from src.music_player.repository.play_history_db import get_top_artist_for_genre
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        genres = image_store.get_genres()
        if not genres:
            lbl = QLabel("No genres found.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#333; font-size:14px; background:transparent;")
            root.addWidget(lbl)
            return
        sorted_genres = sorted(genres, key=lambda g: g.get("songCount", 0), reverse=True)

        def factory(item: tuple) -> QWidget:
            idx, g = item
            name  = g.get("value", "")
            color = _GENRE_PALETTE[idx % len(_GENRE_PALETTE)]
            artist = get_top_artist_for_genre(name)
            img    = image_store.get(f"artist:{artist.lower()}") if artist else None
            card   = _GenreCard(name, g.get("songCount", 0), color, img, count_label="songs")
            card.clicked.connect(self.genre_selected)
            return card

        grid = PaginatedGrid(item_width=160, rows=3, spacing=16, margins=(0, 16, 0, 8))
        grid.setStyleSheet("background:transparent;")
        grid.set_data(list(enumerate(sorted_genres)), factory)
        root.addWidget(grid, stretch=1)


# ── Genre detail page ──────────────────────────────────────────────────

class GenreDetailPage(QWidget):
    """Full-page genre view: heading + all tracks tagged with that genre."""

    back_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = None
        self.setStyleSheet("background:#0d0d10;")
        self._build_ui()

    def load_genre(self, genre: str) -> None:
        self._lbl_genre.setText(genre)
        self._status.setText("Loading tracks…")
        self._table.set_tracks([])
        if self._worker and self._worker.isRunning():
            self._worker.quit(); self._worker.wait()
        from src.music_player.ui.workers.artist_detail import LoadGenreTracksWorker
        self._worker = LoadGenreTracksWorker(genre, parent=self)
        self._worker.tracks_loaded.connect(self._on_tracks)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    def _build_ui(self) -> None:
        from src.music_player.ui.components.track_table import TrackTable
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        back_row = QHBoxLayout()
        back_row.setContentsMargins(16, 12, 16, 0)
        back_btn = QPushButton("← Genres")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#2dd4bf;"
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
        content.setStyleSheet("background:#0d0d10;")
        scroll.setWidget(content)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 20, 32, 32)
        cl.setSpacing(12)

        self._lbl_genre = QLabel()
        f = QFont(); f.setPointSize(26); f.setWeight(QFont.Weight.Bold)
        self._lbl_genre.setFont(f)
        self._lbl_genre.setStyleSheet("color:#fff; background:transparent;")
        cl.addWidget(self._lbl_genre)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#666; font-size:13px; background:transparent;")
        cl.addWidget(self._status)

        self._table = TrackTable()
        cl.addWidget(self._table, stretch=1)

    @pyqtSlot(list)
    def _on_tracks(self, tracks: list) -> None:
        self._status.setText(f"{len(tracks)} track(s)" if tracks else "No tracks found.")
        self._table.set_tracks(tracks)


_ALBUM_CARD_W = 170
_ALBUM_ART    = 150


class AlbumsTab(QWidget):
    """Paginated 3-row grid of all albums, sorted by artist then year."""

    album_selected = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loaded = False
        self.setStyleSheet("background:transparent;")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._build()

    def _build(self) -> None:
        from src.music_player.ui.components.flow_grid import PaginatedGrid

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._grid = PaginatedGrid(
            item_width=_ALBUM_CARD_W, rows=3, spacing=12, margins=(0, 16, 0, 8)
        )
        self._grid.setStyleSheet("background:transparent;")
        root.addWidget(self._grid, stretch=1)

        albums = sorted(
            image_store.get_albums(),
            key=lambda a: (a.get("artist", "").lower(), -(a.get("year") or 0))
        )
        self._grid.set_data(albums, self._make_card)

    def _make_card(self, album: dict) -> QWidget:
        card = _AlbumGridCard(album)
        card.clicked.connect(self.album_selected)
        return card


class _AlbumGridCard(QWidget):
    """Album card for the Albums grid — square art + name + artist + year."""

    clicked = pyqtSignal(dict)

    def __init__(self, album: dict, parent=None) -> None:
        super().__init__(parent)
        self._data = album
        name       = album.get("name", "Unknown Album")
        artist     = album.get("artist", "")
        year       = album.get("year")
        cover_id   = album.get("coverArt", "")

        self.setFixedWidth(_ALBUM_CARD_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Cover art
        self._img = QLabel()
        self._img.setFixedSize(_ALBUM_ART, _ALBUM_ART)
        self._img.setStyleSheet("border-radius:6px; background:#2a2a2e;")
        layout.addWidget(self._img)

        # Try cache immediately
        data = image_store.get(f"album:{cover_id}") if cover_id else None
        if data:
            self._set_art(data)
        elif cover_id:
            from src.music_player.ui.workers.image_loader import AlbumCoverLoader
            loader = AlbumCoverLoader(cover_id, artist, name, parent=self)
            loader.loaded.connect(self._set_art)
            loader.start()

        name_lbl = QLabel(name)
        name_lbl.setWordWrap(True)
        name_lbl.setStyleSheet("color:#ddd; font-size:12px; font-weight:600; background:transparent;")
        name_lbl.setFixedWidth(_ALBUM_CARD_W)
        layout.addWidget(name_lbl)

        if artist:
            art_lbl = QLabel(artist)
            art_lbl.setWordWrap(True)
            art_lbl.setStyleSheet("color:#666; font-size:11px; background:transparent;")
            art_lbl.setFixedWidth(_ALBUM_CARD_W)
            layout.addWidget(art_lbl)

        if year:
            yr_lbl = QLabel(str(year))
            yr_lbl.setStyleSheet("color:#555; font-size:11px; background:transparent;")
            layout.addWidget(yr_lbl)

        layout.addStretch()

    @pyqtSlot(bytes)
    def _set_art(self, data: bytes) -> None:
        if not data:
            return
        px = QPixmap()
        if px.loadFromData(data):
            self._img.setPixmap(
                px.scaled(_ALBUM_ART, _ALBUM_ART,
                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
                .copy(0, 0, _ALBUM_ART, _ALBUM_ART)
            )
            self._img.setStyleSheet("border-radius:6px;")

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._data)
        super().mousePressEvent(event)


# ── Album detail page ─────────────────────────────────────────────────

_DETAIL_ART = 180


class AlbumDetailPage(QWidget):
    """Full-page album view: large cover + metadata + track table."""

    back_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = None
        self.setStyleSheet("background:#0d0d10;")
        self._build_ui()

    def load_album(self, album: dict) -> None:
        album_id = album.get("id", "")
        name     = album.get("name", "Unknown Album")
        artist   = album.get("artist", "")
        year     = album.get("year")
        cover_id = album.get("coverArt", "")

        self._lbl_name.setText(name)
        self._lbl_artist.setText(artist)
        self._lbl_year.setText(str(year) if year else "")

        # Cover art
        data = image_store.get(f"album:{cover_id}") if cover_id else None
        if data:
            self._set_cover(data)
        else:
            self._cover.setStyleSheet("border-radius:8px; background:#2a2a2e;")
            if cover_id:
                from src.music_player.ui.workers.image_loader import AlbumCoverLoader
                loader = AlbumCoverLoader(cover_id, artist, name, parent=self)
                loader.loaded.connect(self._set_cover)
                loader.start()

        # Load tracks (pass all Navidrome IDs + metadata for MB tracklist lookup)
        self._status.setText("Loading tracks…")
        self._table.set_tracks([])
        if self._worker and self._worker.isRunning():
            self._worker.quit(); self._worker.wait()
        from src.music_player.ui.workers.album_tracks import LoadAlbumTracksWorker
        extra_ids = [i for i in album.get("_all_ids", []) if i != album_id]
        self._worker = LoadAlbumTracksWorker(
            album_id, extra_ids=extra_ids, artist=artist, album_name=name, parent=self
        )
        self._worker.tracks_loaded.connect(self._on_tracks)
        self._worker.error.connect(lambda e: self._status.setText(f"Error: {e}"))
        self._worker.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Back button
        back_row = QHBoxLayout()
        back_row.setContentsMargins(16, 12, 16, 0)
        back_btn = QPushButton("← Albums")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#2dd4bf;"
            "font-size:14px;font-weight:600;border:none;padding:4px 0;}"
            "QPushButton:hover{color:#fff;}"
        )
        back_btn.clicked.connect(self.back_clicked)
        back_row.addWidget(back_btn)
        back_row.addStretch()
        root.addLayout(back_row)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:transparent;")
        root.addWidget(scroll)

        content = QWidget(); content.setStyleSheet("background:#0d0d10;")
        scroll.setWidget(content)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 24, 32, 32)
        cl.setSpacing(20)

        # Hero: cover + metadata side by side
        hero = QHBoxLayout()
        hero.setSpacing(28)

        self._cover = QLabel()
        self._cover.setFixedSize(_DETAIL_ART, _DETAIL_ART)
        self._cover.setStyleSheet("border-radius:8px; background:#2a2a2e;")
        hero.addWidget(self._cover)

        meta = QVBoxLayout()
        meta.setSpacing(6)
        meta.addStretch()

        self._lbl_name = QLabel()
        f = QFont(); f.setPointSize(26); f.setWeight(QFont.Weight.Bold)
        self._lbl_name.setFont(f)
        self._lbl_name.setStyleSheet("color:#fff; background:transparent;")
        self._lbl_name.setWordWrap(True)
        meta.addWidget(self._lbl_name)

        self._lbl_artist = QLabel()
        self._lbl_artist.setStyleSheet("color:#aaa; font-size:16px; background:transparent;")
        meta.addWidget(self._lbl_artist)

        self._lbl_year = QLabel()
        self._lbl_year.setStyleSheet("color:#666; font-size:13px; background:transparent;")
        meta.addWidget(self._lbl_year)

        meta.addStretch()
        hero.addLayout(meta, stretch=1)
        cl.addLayout(hero)

        from src.music_player.ui.components.track_table import TrackTable
        self._status = QLabel("")
        self._status.setStyleSheet("color:#666; font-size:13px; background:transparent;")
        cl.addWidget(self._status)

        self._table = TrackTable()
        self._table.embed_in_scroll_area()
        cl.addWidget(self._table)
        cl.addStretch()

    @pyqtSlot(bytes)
    def _set_cover(self, data: bytes) -> None:
        if not data:
            return
        px = QPixmap()
        if px.loadFromData(data):
            self._cover.setPixmap(
                px.scaled(_DETAIL_ART, _DETAIL_ART,
                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
                .copy(0, 0, _DETAIL_ART, _DETAIL_ART)
            )
            self._cover.setStyleSheet("border-radius:8px;")

    @pyqtSlot(list, dict)
    def _on_tracks(self, tracks: list, album: dict) -> None:
        self._status.setText("")
        self._table.set_tracks(tracks)
        self._table._fit_to_content()


def _ensure_browse_visible(library_page) -> None:
    """If a top-level page other than Browse is shown, switch back to Browse."""
    try:
        top = library_page.window()
        stack = top._stack          # MusicPlayerWindow._stack
        if stack.currentIndex() != 0:
            stack.setCurrentIndex(0)
            sidebar = top._sidebar
            sidebar.set_active_nav("Browse")
    except Exception:
        pass   # silently skip if widget hierarchy doesn't match


def _set_circle_image(label: QLabel, data: bytes, size: int) -> None:
    """Decode raw bytes and apply a circular clip to a QLabel."""
    if not data:
        return
    from PyQt6.QtGui import QPainter, QPainterPath, QPixmap
    px = QPixmap()
    if not px.loadFromData(data):
        return
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
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    label.setPixmap(result)


def _coming_soon() -> QWidget:
    w = QWidget(); w.setStyleSheet("background:transparent;")
    lbl = QLabel("Coming soon")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("color:#333; font-size:20px;")
    QVBoxLayout(w).addWidget(lbl)
    return w
