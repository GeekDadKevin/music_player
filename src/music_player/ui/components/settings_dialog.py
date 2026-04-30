"""Settings dialog — opened via the gear icon in the app header."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from src.music_player.logging import get_logger
from src.music_player.ui.app_settings import AppSettings, load_settings, save_settings

logger = get_logger(__name__)

_DARK  = "#0d0d10"
_PANEL = "#111114"
_BORD  = "#1e1e22"


class SettingsDialog(QDialog):
    """Modal settings dialog.

    Changes are only committed on OK/Apply; Cancel discards them.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"background:{_DARK}; color:#ddd;")

        self._s = load_settings()
        self._build_ui()

    # ── build ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(_section("Appearance"))
        root.addWidget(self._appearance_panel())
        root.addWidget(_section("Playback"))
        root.addWidget(self._playback_panel())
        root.addWidget(_section("Queue"))
        root.addWidget(self._queue_panel())
        root.addWidget(_section("Scrobbling"))
        root.addWidget(self._scrobble_panel())

        root.addSpacing(8)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(
            "QDialogButtonBox QPushButton{"
            "background:#1e1e22;color:#ddd;border:1px solid #2a2a2e;"
            "border-radius:6px;padding:6px 18px;min-width:70px;}"
            "QDialogButtonBox QPushButton:hover{background:#2a2a2e;color:#fff;}"
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)
        root.addSpacing(12)

    # ── panels ────────────────────────────────────────────────────────

    def _appearance_panel(self) -> QWidget:
        panel = _panel()
        layout = panel.layout()

        row = QHBoxLayout()
        row.addWidget(_label("Highlight / accent colour"))
        row.addStretch()

        self._color_swatch = QPushButton()
        self._color_swatch.setFixedSize(32, 32)
        self._color_swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_swatch.setToolTip("Click to pick colour")
        self._color_swatch.clicked.connect(self._pick_color)
        self._apply_swatch(self._s.highlight_color)
        row.addWidget(self._color_swatch)

        self._color_label = QLabel(self._s.highlight_color)
        self._color_label.setStyleSheet("color:#888; font-size:12px; background:transparent;")
        row.addWidget(self._color_label)

        layout.addLayout(row)
        layout.addWidget(_hint("Used for the progress bar, active tabs, and shuffle button."))
        return panel

    def _playback_panel(self) -> QWidget:
        panel = _panel()
        layout = panel.layout()

        row = QHBoxLayout()
        row.addWidget(_label("Minimum play time before counting"))
        row.addStretch()

        self._spin = QSpinBox()
        self._spin.setRange(5, 600)
        self._spin.setValue(self._s.min_play_seconds)
        self._spin.setSuffix(" s")
        self._spin.setStyleSheet(
            "QSpinBox{background:#1e1e22;color:#ddd;border:1px solid #2a2a2e;"
            "border-radius:4px;padding:4px 8px;min-width:70px;}"
            "QSpinBox::up-button,QSpinBox::down-button{width:16px;}"
        )
        row.addWidget(self._spin)
        layout.addLayout(row)
        layout.addWidget(_hint(
            "A track must play at least this many seconds for it to count toward "
            "Most Played, Listening History, and Highlights."
        ))
        return panel

    def _queue_panel(self) -> QWidget:
        panel = _panel()
        layout = panel.layout()

        row = QHBoxLayout()
        row.addWidget(_label("Double-click track action"))
        row.addStretch()

        self._dbl_click = QComboBox()
        self._dbl_click.addItem("Play now (replace queue)", "play_now")
        self._dbl_click.addItem("Play now (keep queue)",   "play_now_keep")
        self._dbl_click.addItem("Add to end of queue",     "add_to_queue")
        self._dbl_click.addItem("Play next",               "play_next")
        self._dbl_click.setStyleSheet(
            "QComboBox{background:#1e1e22;color:#ddd;border:1px solid #2a2a2e;"
            "border-radius:4px;padding:4px 8px;min-width:180px;}"
            "QComboBox::drop-down{border:none;}"
            "QComboBox QAbstractItemView{background:#1e1e22;color:#ddd;"
            "border:1px solid #2a2a2e;selection-background-color:#2dd4bf;}"
        )
        current = self._s.double_click_action
        for i in range(self._dbl_click.count()):
            if self._dbl_click.itemData(i) == current:
                self._dbl_click.setCurrentIndex(i)
                break
        row.addWidget(self._dbl_click)
        layout.addLayout(row)
        layout.addWidget(_hint(
            "Play now replaces the current queue immediately. "
            "Add to queue appends without interrupting. "
            "Play next inserts after the current track."
        ))
        return panel

    def _scrobble_panel(self) -> QWidget:
        panel = _panel()
        layout = panel.layout()

        row = QHBoxLayout()
        row.addWidget(_label("Scrobble plays to server"))
        row.addStretch()

        self._scrobble_chk = QCheckBox()
        self._scrobble_chk.setChecked(self._s.scrobble_enabled)
        self._scrobble_chk.setStyleSheet(
            "QCheckBox::indicator{width:18px;height:18px;border-radius:4px;"
            "border:1px solid #2a2a2e;background:#1e1e22;}"
            "QCheckBox::indicator:checked{background:#2dd4bf;border-color:#2dd4bf;}"
        )
        row.addWidget(self._scrobble_chk)
        layout.addLayout(row)
        layout.addWidget(_hint(
            "When enabled, each counted play is submitted to your Subsonic server "
            "via the scrobble API endpoint."
        ))
        return panel

    # ── actions ───────────────────────────────────────────────────────

    def _pick_color(self) -> None:
        initial = QColor(self._s.highlight_color)
        color = QColorDialog.getColor(initial, self, "Pick accent colour")
        if color.isValid():
            hex_color = color.name()
            self._s = AppSettings(
                highlight_color     = hex_color,
                min_play_seconds    = self._s.min_play_seconds,
                scrobble_enabled    = self._s.scrobble_enabled,
                double_click_action = self._s.double_click_action,
            )
            self._apply_swatch(hex_color)
            self._color_label.setText(hex_color)

    def _apply_swatch(self, color: str) -> None:
        self._color_swatch.setStyleSheet(
            f"QPushButton{{background:{color};border:none;border-radius:4px;}}"
        )

    def _on_ok(self) -> None:
        updated = AppSettings(
            highlight_color     = self._s.highlight_color,
            min_play_seconds    = self._spin.value(),
            scrobble_enabled    = self._scrobble_chk.isChecked(),
            double_click_action = self._dbl_click.currentData(),
        )
        save_settings(updated)
        self.accept()


# ── helpers ───────────────────────────────────────────────────────────

def _section(title: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(16, 16, 16, 4)
    lbl = QLabel(title)
    f = QFont(); f.setPointSize(11); f.setWeight(QFont.Weight.Bold)
    lbl.setFont(f)
    lbl.setStyleSheet("color:#fff; background:transparent;")
    layout.addWidget(lbl)
    return w


def _panel() -> QWidget:
    w = QWidget()
    w.setStyleSheet(f"background:{_PANEL}; border-radius:8px;")
    w.setContentsMargins(0, 0, 0, 0)
    layout = QVBoxLayout(w)
    layout.setContentsMargins(16, 12, 16, 12)
    layout.setSpacing(8)
    return w


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#ddd; font-size:13px; background:transparent;")
    return lbl


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color:#555; font-size:11px; background:transparent;")
    return lbl
