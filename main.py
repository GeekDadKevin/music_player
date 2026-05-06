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

    # NOTE: QT_OPENGL=desktop is intentionally NOT set here.  Forcing WGL
    # (native desktop OpenGL) in Qt 6.11 triggers platform-plugin initialisation
    # code inside CreateWindowExW that causes an access violation on first
    # window.show().  projectM needs desktop GL, but milkdrop_widget is loaded
    # lazily (only when the user opens the visualizer), so by then Qt has
    # already created the main HWND without the forced WGL path.  The widget's
    # own setFormat(3.3 Core) call in MilkdropWidget.__init__() is sufficient.

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from src.music_player.dns_cache import install as install_dns_cache
    from src.music_player.ui.app import MusicPlayerWindow
    from src.music_player.ui.loading_screen import LoadingScreen

    # Establish the ONE shared httpx session (and its ssl context) before
    # any native DLLs are loaded.  After libmpv.dll enters the process,
    # creating new ssl contexts crashes on Python 3.13.9 / Windows 11
    # (code 0xe24c4a02).  All SubsonicHttp instances share this session
    # so no new ssl contexts are ever created post-DLL-load.
    from src.music_player.repository._http import _get_session as _warm_http
    _warm_http()
    del _warm_http
    # Also pre-import requests/urllib3 so their ssl init happens here too.
    import requests as _req; _req.Session(); del _req

    install_dns_cache()
    # Pre-create the shared OpenGL context before QApplication finishes init.
    # Without this, Qt creates it lazily when the first QOpenGLWidget (MilkdropWidget)
    # is first shown — which forces Qt to briefly reconstitute the window's native
    # compositing layer, causing a visible window flash/blink.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    # Fusion style + explicit dark palette forces dark rendering on all platforms
    # regardless of the OS light/dark mode setting.
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())

    # MusicPlayerWindow is created INSIDE on_ready() so it runs after the Qt
    # event loop starts.  libmpv (MpvAudioBackend) is deferred further still:
    # PlaybackBridge.init_audio() is called AFTER window.show() so libmpv's
    # internal C threads never race with Qt's HWND creation.
    loading = LoadingScreen()
    _window: list = []   # mutable cell so the closure can write to it

    def on_ready():
        from src.music_player.logging import get_logger as _get_logger
        _log = _get_logger("main.on_ready")
        try:
            window = MusicPlayerWindow()
            _window.append(window)
            loading.close()
            window._sidebar.refresh_playlist_thumbnails()
            window.show()
            # Initialize libmpv after Qt HWND is created so its C threads
            # don't race with Win32 window initialisation.
            from src.music_player.ui.components.playback_bridge import get_bridge
            get_bridge().init_audio()
        except Exception as exc:
            _log.error(f"on_ready: EXCEPTION: {exc}", exc_info=True)

    loading.ready.connect(on_ready)
    loading.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
