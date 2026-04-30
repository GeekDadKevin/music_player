def main():
    import sys
    from PyQt6.QtWidgets import QApplication
    from src.music_player.dns_cache import install as install_dns_cache
    from src.music_player.ui.app import MusicPlayerWindow
    from src.music_player.ui.loading_screen import LoadingScreen

    install_dns_cache()
    app = QApplication(sys.argv)

    window = MusicPlayerWindow()
    loading = LoadingScreen()

    def on_ready():
        loading.close()
        window._sidebar.refresh_playlist_thumbnails()
        window.show()

    loading.ready.connect(on_ready)
    loading.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
