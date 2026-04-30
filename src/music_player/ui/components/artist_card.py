from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_IMG_SIZE = 150
_CARD_W = 190
_CARD_H = 220


class ArtistCard(QWidget):
    clicked = pyqtSignal(object)

    def __init__(self, name: str, artist_data: dict = None, parent=None) -> None:
        super().__init__(parent)
        self._artist_data = artist_data

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 8)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.image_label = QLabel()
        self.image_label.setFixedSize(_IMG_SIZE, _IMG_SIZE)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            f"border-radius: {_IMG_SIZE // 2}px; background: #2a2a2e;"
        )
        layout.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._name_label = QLabel(name)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._name_label.setWordWrap(True)
        self._name_label.setStyleSheet(
            "color: #ffffff; font-size: 14px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(self._name_label)

        role_label = QLabel("Artist")
        role_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        role_label.setStyleSheet(
            "color: #a0a0a8; font-size: 12px; background: transparent;"
        )
        layout.addWidget(role_label)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Set a pre-decoded pixmap directly — no decode, instant."""
        self.image_label.setPixmap(pixmap)

    def set_image(self, data: bytes) -> None:
        if not data:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self.image_label.setPixmap(_make_circle_pixmap(pixmap, _IMG_SIZE))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        else:
            self.clicked.emit(self._artist_data)
        super().mousePressEvent(event)

    def _show_context_menu(self, global_pos) -> None:
        from PyQt6.QtWidgets import QMenu
        from src.music_player.ui.glyphs import MDL2_FAMILY_CSS
        from src.music_player.ui.pins import add_pin
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:#1a1a1e;color:#ddd;border:1px solid #2a2a2e;"
            f"font-family:{MDL2_FAMILY_CSS};}}"
            "QMenu::item{padding:6px 18px;}"
            "QMenu::item:selected{background:#2dd4bf;color:#000;}"
        )
        pin_act = menu.addAction("Pin to sidebar")
        if menu.exec(global_pos) == pin_act:
            data = self._artist_data or {}
            add_pin({
                "type": "artist",
                "id": data.get("id", ""),
                "name": data.get("name", "Unknown"),
            })


def _make_circle_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
    """Crop and clip a pixmap into a circle."""
    scaled = pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    # centre-crop to exact size
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
