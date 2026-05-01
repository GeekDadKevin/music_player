def _dark_palette():
    from PyQt6.QtGui import QColor, QPalette
    p = QPalette()
    # Base surfaces
    p.setColor(QPalette.ColorRole.Window,        QColor("#111114"))
    p.setColor(QPalette.ColorRole.Base,          QColor("#0a0a0d"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#1e1e22"))
    p.setColor(QPalette.ColorRole.Button,        QColor("#1e1e22"))
    p.setColor(QPalette.ColorRole.Mid,           QColor("#1a1a1e"))
    p.setColor(QPalette.ColorRole.Dark,          QColor("#0a0a0d"))
    # Text
    p.setColor(QPalette.ColorRole.WindowText,    QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.Text,          QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.ButtonText,    QColor("#cccccc"))
    p.setColor(QPalette.ColorRole.BrightText,    QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase,   QColor("#1e1e22"))
    p.setColor(QPalette.ColorRole.ToolTipText,   QColor("#cccccc"))
    # Accent
    p.setColor(QPalette.ColorRole.Highlight,        QColor("#2dd4bf"))
    p.setColor(QPalette.ColorRole.HighlightedText,  QColor("#000000"))
    p.setColor(QPalette.ColorRole.Link,             QColor("#2dd4bf"))
    # Disabled state
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#555555"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor("#18181b"))
    return p


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
    # Fusion style + explicit dark palette forces dark rendering on all platforms
    # regardless of the OS light/dark mode setting.
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())

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
