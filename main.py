def main():
    import os
    import sys

    # Force native desktop OpenGL (not ANGLE/D3D translation).
    # Must happen before ANY PyQt6 import; Qt reads this at library load time.
    # Without this, Qt may select ANGLE on Windows, whose EGL context does not
    # expose wglGetProcAddress — so projectM's glad loader gets null pointers
    # for every GL function and crashes with a null-write access violation.
    os.environ.setdefault("QT_OPENGL", "desktop")

    from PyQt6.QtGui import QSurfaceFormat
    from PyQt6.QtWidgets import QApplication
    from src.music_player.dns_cache import install as install_dns_cache
    from src.music_player.ui.app import MusicPlayerWindow
    from src.music_player.ui.loading_screen import LoadingScreen

    # projectM 4.x requires OpenGL 3.3 core.  Must be set as the global
    # default BEFORE QApplication so every GL context inherits this format.
    _fmt = QSurfaceFormat()
    _fmt.setVersion(3, 3)
    _fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    _fmt.setDepthBufferSize(24)
    _fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(_fmt)

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
