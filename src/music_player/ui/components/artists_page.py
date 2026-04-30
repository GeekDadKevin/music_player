from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

import src.music_player.image_store as image_store
from src.music_player.logging import get_logger
from src.music_player.ui.components.artist_card import ArtistCard
from src.music_player.ui.components.artist_detail_page import ArtistDetailPage
from src.music_player.ui.components.flow_grid import FlowGrid
from src.music_player.ui.workers.image_loader import ImageQueueWorker

logger = get_logger(__name__)

_BATCH    = 50
_GRID_IDX = 0
_DETAIL_IDX = 1


class ArtistsPage(QWidget):
    """Artists section — internal stack: [grid | detail].

    Grid renders from image_store on first show.  Images not yet in the cache
    are fetched on demand by ImageQueueWorker after the grid is fully built.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._grid_page = _ArtistGridPage()
        self._grid_page.artist_selected.connect(self._show_detail)
        self._stack.addWidget(self._grid_page)

        self._detail_page = ArtistDetailPage()
        self._detail_page.back_clicked.connect(lambda: self._stack.setCurrentIndex(_GRID_IDX))
        self._stack.addWidget(self._detail_page)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._grid_page.ensure_loaded()

    def _show_detail(self, artist_data: dict) -> None:
        self._detail_page.load_artist(artist_data)
        self._stack.setCurrentIndex(_DETAIL_IDX)


class _ArtistGridPage(QWidget):
    artist_selected = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loaded      = False
        self._render_idx  = 0
        self._all_artists: list[dict] = []
        self._cards:       dict[str, ArtistCard] = {}
        self._image_worker: ImageQueueWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border:none; background:transparent;")

        self._flow = FlowGrid(item_width=190, spacing=8, margins=(24, 24, 24, 24))
        self._scroll.setWidget(self._flow)
        layout.addWidget(self._scroll)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:16px;")
        layout.addWidget(self._status)

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._all_artists = image_store.get_artists()
        if not self._all_artists:
            self._status.setText("No artists found.")
            return
        QTimer.singleShot(0, self._render_batch)

    def _render_batch(self) -> None:
        end = min(self._render_idx + _BATCH, len(self._all_artists))
        for i in range(self._render_idx, end):
            artist = self._all_artists[i]
            name   = artist.get("name", "Unknown Artist")
            card   = ArtistCard(name, artist_data=artist)

            # Use cached bytes if available (instant), else leave as placeholder
            data = image_store.get(f"artist:{name.lower()}")
            if data:
                card.set_image(data)

            card.clicked.connect(self.artist_selected)
            self._flow.add_widget(card)
            self._cards[name] = card

        self._render_idx = end
        if self._render_idx < len(self._all_artists):
            QTimer.singleShot(0, self._render_batch)
        else:
            self._fetch_missing_images()

    def _fetch_missing_images(self) -> None:
        """Start a pooled worker to fetch any artist images not yet cached."""
        needed = [
            (a.get("name", ""), a.get("coverArt", ""))
            for a in self._all_artists
            if a.get("name") and not image_store.has(f"artist:{a['name'].lower()}")
        ]
        if not needed:
            return
        self._image_worker = ImageQueueWorker(needed, parent=self)
        self._image_worker.image_ready.connect(self._on_image_ready)
        self._image_worker.start()

    def _on_image_ready(self, name: str, data: bytes) -> None:
        card = self._cards.get(name)
        if card and data:
            card.set_image(data)
