from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QLabel, QProgressBar, QVBoxLayout, QWidget
)

from src.music_player.logging import get_logger
from src.music_player.ui.workers.startup_cache import StartupCacheWorker

logger = get_logger(__name__)


class LoadingScreen(QWidget):
    """Full-window loading screen shown while the image cache is being warmed.

    Emits ready() when the cache worker finishes, at which point the caller
    should show the main window and close this screen.
    """

    ready = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(520, 320)
        self.setStyleSheet("background: #0d0d10;")

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setSpacing(16)
        root.setContentsMargins(60, 60, 60, 60)

        title = QLabel("Music Player")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        font = QFont()
        font.setPointSize(28)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        title.setStyleSheet("color: #ffffff; background: transparent;")
        root.addWidget(title)

        self._status = QLabel("Connecting…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._status.setStyleSheet("color: #888; font-size: 14px; background: transparent;")
        root.addWidget(self._status)

        root.addSpacing(12)

        self._bar = QProgressBar()
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setStyleSheet("""
            QProgressBar {
                background: #2a2a2e;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background: #1db954;
                border-radius: 3px;
            }
        """)
        root.addWidget(self._bar)

        self._detail = QLabel("")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._detail.setStyleSheet("color: #555; font-size: 12px; background: transparent;")
        root.addWidget(self._detail)

        self._worker = StartupCacheWorker(parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)

        # Small delay so the window has time to paint before heavy work starts
        QTimer.singleShot(150, self._worker.start)

        # Track overall progress across both phases
        self._phase_done = 0
        self._phase_total = 0

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self._detail.setText(label)
        if total > 0:
            self._bar.setValue(int(done / total * 100))
        elif done == 0 and total == 0:
            # phase was already cached — pulse bar briefly
            self._bar.setValue(100)

    def _on_finished(self) -> None:
        self._bar.setValue(100)
        self._status.setText("Ready")
        QTimer.singleShot(300, self.ready.emit)
