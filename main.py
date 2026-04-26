def main():
    from PyQt6.QtWidgets import QApplication
    import sys
    from src.music_player.ui.app import MusicPlayerWindow

    app = QApplication(sys.argv)
    window = MusicPlayerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
