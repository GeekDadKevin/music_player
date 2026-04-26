from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QStackedWidget, QLineEdit, QFrame
from PyQt6.QtCore import Qt

class MusicPlayerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Player")
        self.setMinimumSize(1200, 800)
        self._init_ui()

    def _init_ui(self):
        # Central widget
        central = QWidget()
        root_layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        # Main area (sidebar + content)
        main_area = QHBoxLayout()
        root_layout.addLayout(main_area)

        # Sidebar (left)
        sidebar = QListWidget()
        sidebar.addItems([
            "Browse", "Activity", "Radio", "Songs", "Albums", "Artists", "Playlists", "Local Files"
        ])
        sidebar.setMaximumWidth(200)
        main_area.addWidget(sidebar)

        # Main content area (right)
        content = QVBoxLayout()
        main_area.addLayout(content)

        # Top: Search bar
        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search")
        search_bar.setMaximumWidth(400)
        content.addWidget(search_bar, alignment=Qt.AlignmentFlag.AlignLeft)

        # Artist header placeholder
        artist_header = QFrame()
        artist_header.setFrameShape(QFrame.Shape.StyledPanel)
        artist_header.setFixedHeight(200)
        artist_layout = QHBoxLayout(artist_header)
        artist_pic = QLabel("[Artist Image]")
        artist_pic.setFixedSize(120, 120)
        artist_name = QLabel("Artist Name")
        artist_name.setStyleSheet("font-size: 32px; font-weight: bold;")
        artist_layout.addWidget(artist_pic)
        artist_layout.addWidget(artist_name)
        artist_layout.addStretch()
        content.addWidget(artist_header)

        # Tabs (Overview, Related Artists, Biography)
        tabs = QHBoxLayout()
        for tab in ["Overview", "Related Artists", "Biography"]:
            btn = QPushButton(tab)
            btn.setEnabled(False)  # Placeholder
            tabs.addWidget(btn)
        tabs.addStretch()
        content.addLayout(tabs)

        # Main stacked content (Latest Release, Popular, Related Artists)
        stacked = QHBoxLayout()
        # Left: Latest Release & Popular
        left = QVBoxLayout()
        left.addWidget(QLabel("Latest Release [Placeholder]"))
        left.addWidget(QLabel("Popular [Placeholder]"))
        stacked.addLayout(left)
        # Center: Related Artists
        center = QVBoxLayout()
        center.addWidget(QLabel("Related Artists [Placeholder]"))
        stacked.addLayout(center)
        # Right: Friends/More
        right = QVBoxLayout()
        right.addWidget(QLabel("Friends [Placeholder]"))
        stacked.addLayout(right)
        content.addLayout(stacked)

        # Bottom: Player bar (modern controls)
        from src.music_player.ui.components.player_bar import PlayerBar
        player_bar = PlayerBar()
        player_bar.setFixedHeight(60)
        root_layout.addWidget(player_bar)
