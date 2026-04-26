from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSlider, QSizePolicy
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

class PlayerBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        from src.music_player.ui.components.playback_bridge import PlaybackBridge
        self._bridge = PlaybackBridge()
        self._init_ui()
        self._connect_signals()

    def _connect_signals(self):
        self.btn_play.clicked.connect(self._on_play_pause)
        self.slider_volume.valueChanged.connect(self._on_volume)
        # Add more connections as needed

    def _on_play_pause(self):
        self._bridge.pause() if self._bridge._controller.is_playing else self._bridge.play(self._bridge._controller._current_track_id or "1")

    def _on_volume(self, value):
        self._bridge.set_volume(value)

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(16)

        # Playback controls
        self.btn_shuffle = QPushButton()
        self.btn_shuffle.setIcon(QIcon.fromTheme("media-playlist-shuffle"))
        self.btn_shuffle.setToolTip("Shuffle")
        layout.addWidget(self.btn_shuffle)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(QIcon.fromTheme("media-skip-backward"))
        self.btn_prev.setToolTip("Previous")
        layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(QIcon.fromTheme("media-playback-start"))
        self.btn_play.setToolTip("Play/Pause")
        layout.addWidget(self.btn_play)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(QIcon.fromTheme("media-skip-forward"))
        self.btn_next.setToolTip("Next")
        layout.addWidget(self.btn_next)

        self.btn_repeat = QPushButton()
        self.btn_repeat.setIcon(QIcon.fromTheme("media-playlist-repeat"))
        self.btn_repeat.setToolTip("Repeat")
        layout.addWidget(self.btn_repeat)

        # Track info
        self.lbl_track = QLabel("Track Title - Artist")
        self.lbl_track.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl_track.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_track)

        # Progress slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(100)
        self.slider.setValue(0)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.slider)

        # Time labels
        self.lbl_time = QLabel("0:00")
        layout.addWidget(self.lbl_time)
        self.lbl_duration = QLabel("0:00")
        layout.addWidget(self.lbl_duration)

        # Volume slider
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setMinimum(0)
        self.slider_volume.setMaximum(100)
        self.slider_volume.setValue(80)
        self.slider_volume.setFixedWidth(100)
        layout.addWidget(self.slider_volume)
