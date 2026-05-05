"""
MilkdropWidget — QOpenGLWidget that renders projectM MilkDrop visualizations.

Uses ctypes to load libprojectM-4 (C API, projectM 4.x).
Presets are managed in Python by scanning a directory for *.milk files.
Audio is captured via sounddevice WASAPI loopback (Windows) or the default
input device as a fallback; samples are forwarded to projectM every frame.

If libprojectM is not found the widget shows installation instructions
instead of raising an exception.

Install projectM from:
  https://github.com/projectM-visualizer/projectm/releases
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QOpenGLContext, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.music_player.logging import get_logger

logger = get_logger(__name__)

_STEREO = 2


# ── project-local lib directory ───────────────────────────────────────────

from src.music_player._paths import app_root as _app_root
_PROJECT_LIB_DIR = _app_root() / "lib" / "projectm"

# Prepend lib/projectm/ to PATH so Windows can find delay-loaded dependencies
# (glew32.dll, PocoFoundation.dll, freetype.dll, etc.) when projectm_create()
# triggers their load at runtime.
os.environ["PATH"] = str(_PROJECT_LIB_DIR) + os.pathsep + os.environ.get("PATH", "")


# ── libprojectM loading ───────────────────────────────────────────────────

def _load_lib(candidates: list[str]) -> ctypes.CDLL | None:
    """Search for libprojectM, checking the project lib/ directory first."""
    # 1. Project-local lib/projectm/ — checked before anything else so the
    #    bundled DLL always wins over whatever is installed system-wide.
    for name in candidates:
        for ext in (".dll", ".so", ".so.4", ".dylib"):
            local = _PROJECT_LIB_DIR / (name + ext)
            if local.is_file():
                try:
                    lib = ctypes.CDLL(str(local))
                    logger.info(f"Loaded projectM from project lib: {local}")
                    return lib
                except OSError:
                    pass

    # 2. System PATH / standard library locations
    for name in candidates:
        found = ctypes.util.find_library(name)
        if found:
            try:
                return ctypes.CDLL(found)
            except OSError:
                pass

    # 3. Common Windows install directories
    if platform.system() == "Windows":
        pf   = os.environ.get("ProgramFiles",      r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for name in candidates:
            for base in (pf, pf86):
                for suffix in ("", "-Visualizer"):
                    path = os.path.join(base, f"projectM{suffix}", f"{name}.dll")
                    if os.path.isfile(path):
                        try:
                            return ctypes.CDLL(path)
                        except OSError:
                            pass
    return None


_lib = _load_lib(["projectM-4", "libprojectM-4", "projectM", "libprojectM"])

# projectM 4.1.x removed projectm_create_with_opengl_load_proc (GLAD variant)
# and uses projectm_create() exclusively.  Earlier builds had both.
# We require only projectm_create — the minimum needed to instantiate the engine.
def _has_symbol(lib, name: str) -> bool:
    if lib is None:
        return False
    try:
        getattr(lib, name)
        return True
    except AttributeError:
        return False

AVAILABLE = _lib is not None and _has_symbol(_lib, "projectm_create")
if _lib is not None and not AVAILABLE:
    logger.warning("projectM DLL loaded but projectm_create is missing — visualizer disabled")
elif _lib is not None:
    logger.info("projectM DLL ready (projectm_create found)")

ERROR_MSG = (
    "" if AVAILABLE else
    f"libprojectM-4 not found.\n\n"
    f"Drop projectM-4.dll into:\n"
    f"  {_PROJECT_LIB_DIR}\n\n"
    f"Download from:\n"
    f"https://github.com/projectM-visualizer/projectm/releases"
)


# ── ctypes function table ─────────────────────────────────────────────────

def _fn(name: str, restype, *argtypes):
    if not _lib:
        return None
    try:
        f = getattr(_lib, name)
        f.restype  = restype
        f.argtypes = list(argtypes)
        return f
    except AttributeError:
        return None


_vp   = ctypes.c_void_p
_sz   = ctypes.c_size_t
_uint = ctypes.c_uint
_int  = ctypes.c_int
_fp   = ctypes.POINTER(ctypes.c_float)
_cp   = ctypes.c_char_p
_bool = ctypes.c_bool
_dbl  = ctypes.c_double
_i32  = ctypes.c_int32

_pm_create          = _fn("projectm_create",                         _vp)
_pm_create_with_proc= _fn("projectm_create_with_opengl_load_proc",   _vp,
                           ctypes.c_void_p, ctypes.c_void_p)
_pm_destroy         = _fn("projectm_destroy",                        None, _vp)
_pm_set_win_size    = _fn("projectm_set_window_size",                None, _vp, _sz, _sz)
_pm_render          = _fn("projectm_opengl_render_frame",            None, _vp)
_pm_render_fbo      = _fn("projectm_opengl_render_frame_fbo",        None, _vp, _uint)
_pm_pcm_add_float   = _fn("projectm_pcm_add_float",                  None, _vp, _fp, _uint, _int)
_pm_load_preset     = _fn("projectm_load_preset_file",               None, _vp, _cp, _bool)
_pm_set_dur         = _fn("projectm_set_preset_duration",            None, _vp, _dbl)
_pm_set_hard_cut    = _fn("projectm_set_hard_cut_enabled",           None, _vp, _bool)
_pm_set_beat_sens   = _fn("projectm_set_beat_sensitivity",           None, _vp, ctypes.c_float)
_pm_set_fps         = _fn("projectm_set_fps",                        None, _vp, _i32)
_pm_set_switch_cb     = _fn(
    "projectm_set_preset_switch_requested_event_callback",
    None, _vp, ctypes.c_void_p, ctypes.c_void_p,
)
_pm_set_tex_paths     = _fn(
    "projectm_set_texture_search_paths",
    None, _vp, ctypes.POINTER(ctypes.c_char_p), _sz,
)

# ctypes function type for the GL proc-address loader callback
_LOAD_PROC_CB = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p)

# ctypes callback type (must survive GC, stored on instance)
_SWITCH_CB = ctypes.CFUNCTYPE(None, ctypes.c_bool, ctypes.c_void_p)


# ── GLEW initialisation ───────────────────────────────────────────────────

def _init_glew() -> None:
    """Call glewInit() from glew32.dll with the current OpenGL context active.

    projectM-4.dll links against GLEW for OpenGL function loading.  GLEW is a
    global-state library that must be initialised exactly once per process while
    a valid GL context is current.  Without this call every GLEW function pointer
    stays NULL, and projectM's first GL call crashes with a write-to-0x0 AV.

    glewExperimental is set to GL_TRUE so GLEW queries wglGetProcAddress for
    *all* functions rather than filtering by the extension string — required for
    OpenGL 3.3 core profile contexts which don't expose the old extension strings.
    """
    glew_path = _PROJECT_LIB_DIR / "glew32.dll"
    if not glew_path.exists():
        logger.debug("glew32.dll not found in lib/projectm — skipping glewInit")
        return
    try:
        glew = ctypes.CDLL(str(glew_path))

        # glewExperimental = GL_TRUE  (must be set before glewInit)
        try:
            exp = ctypes.c_ubyte.in_dll(glew, "glewExperimental")
            exp.value = 1
        except Exception:
            pass

        glew_init = glew.glewInit
        glew_init.restype = ctypes.c_uint
        glew_init.argtypes = []
        result = glew_init()
        # GLEW_OK == 0; GLEW_ERROR_NO_GL_VERSION == 1 means no context
        logger.info(f"glewInit() = {result} ({'OK' if result == 0 else 'error — no GL context?'})")
    except Exception as exc:
        logger.warning(f"glewInit() failed: {exc}")


# ── preset discovery ──────────────────────────────────────────────────────

_WIN_PRESET_DIRS = [
    r"C:\Program Files\projectM\presets",
    r"C:\Program Files\projectM-Visualizer\presets",
    r"C:\Program Files (x86)\projectM\presets",
]
_UNIX_PRESET_DIRS = [
    "/usr/share/projectM/presets",
    "/usr/local/share/projectM/presets",
    os.path.expanduser("~/.config/projectM/presets"),
]


def default_preset_dir() -> str | None:
    # Project-local presets always win
    local = _PROJECT_LIB_DIR / "presets"
    if local.is_dir() and any(local.rglob("*.milk")):
        return str(local)
    # Fall back to system install locations
    dirs = _WIN_PRESET_DIRS if platform.system() == "Windows" else _UNIX_PRESET_DIRS
    for d in dirs:
        if os.path.isdir(d):
            return d
    return None


def scan_presets(directory: str) -> list[Path]:
    """Return sorted list of .milk preset paths found recursively."""
    d = Path(directory)
    return sorted(d.rglob("*.milk")) if d.is_dir() else []


# ── process-wide audio capture ────────────────────────────────────────────

_audio_listeners: list[MilkdropWidget] = []
_audio_mutex = threading.Lock()
_audio_stream: sd.InputStream | None = None


def _audio_cb(indata: np.ndarray, frames: int, time_info, status) -> None:
    data = indata.copy()
    with _audio_mutex:
        targets = list(_audio_listeners)
    for w in targets:
        w._push_audio(data)


def _start_capture() -> None:
    global _audio_stream
    if _audio_stream is not None:
        return
    try:
        try:
            _audio_stream = sd.InputStream(
                channels=2, samplerate=44100, dtype="float32",
                blocksize=512, callback=_audio_cb,
                extra_settings=sd.WasapiSettings(loopback=True),
            )
        except Exception:
            _audio_stream = sd.InputStream(
                channels=2, samplerate=44100, dtype="float32",
                blocksize=512, callback=_audio_cb,
            )
        _audio_stream.start()
        logger.info("MilkDrop: audio capture started")
    except Exception as exc:
        logger.warning(f"MilkDrop: audio capture unavailable — {exc}")


def _stop_capture() -> None:
    global _audio_stream
    if _audio_stream:
        try:
            _audio_stream.stop()
            _audio_stream.close()
        except Exception:
            pass
        _audio_stream = None


def _register(w: MilkdropWidget) -> None:
    with _audio_mutex:
        if w not in _audio_listeners:
            _audio_listeners.append(w)
    _start_capture()


def _unregister(w: MilkdropWidget) -> None:
    with _audio_mutex:
        try:
            _audio_listeners.remove(w)
        except ValueError:
            pass
        remaining = len(_audio_listeners)
    if remaining == 0:
        _stop_capture()


# ── widget ────────────────────────────────────────────────────────────────

class MilkdropWidget(QOpenGLWidget):
    """Renders projectM MilkDrop presets in a Qt OpenGL surface."""

    preset_changed = pyqtSignal(str)   # emits stem of the current preset file

    def __init__(
        self,
        preset_dir: str | None = None,
        start_index: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Request 3.3 Core Profile on this widget specifically.  The global
        # QSurfaceFormat.setDefaultFormat() is NOT called at startup because
        # it forces Qt to create a Core Profile context for the main window's
        # backing store, which crashes on some Windows/driver configurations.
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        self.setFormat(fmt)
        self._preset_dir   = preset_dir or default_preset_dir() or ""
        self._start_index  = start_index
        self._pm: int      = 0
        self._presets: list[Path] = []
        self._idx: int     = start_index
        self._current_name = ""
        self._pending: np.ndarray | None = None
        self._pending_load: tuple[int, bool] | None = None
        self._audio_lock   = threading.Lock()
        self._cb_ref       = None   # keep ctypes callback alive
        self._gl_load_cb   = None   # keep GL loader callback alive

        self._timer = QTimer(self)
        self._timer.setInterval(16)    # 60 fps target
        self._timer.timeout.connect(self.update)

    # ── lifecycle ──────────────────────────────────────────────────────

    def initializeGL(self) -> None:
        if not AVAILABLE:
            return
        # GL context may be recreated (e.g. after showFullScreen on Windows).
        # Destroy any existing projectM instance so we start clean.
        if self._pm:
            try:
                if _pm_destroy:
                    _pm_destroy(self._pm)
            except Exception:
                pass
            self._pm = 0
        self._pending_load = None
        try:
            # Log the actual context Qt created so we can diagnose failures.
            ctx = QOpenGLContext.currentContext()
            if ctx:
                fmt = ctx.format()
                logger.info(
                    f"GL context: v{fmt.majorVersion()}.{fmt.minorVersion()} "
                    f"{'ES' if ctx.isOpenGLES() else 'desktop'} "
                    f"{'core' if fmt.profile() == QSurfaceFormat.OpenGLContextProfile.CoreProfile else 'compat'}"
                )
                if ctx.isOpenGLES():
                    raise RuntimeError(
                        "Qt created an OpenGL ES (ANGLE) context — projectM requires "
                        "native desktop OpenGL. Set QT_OPENGL=desktop and restart."
                    )
            else:
                logger.warning("No current GL context in initializeGL")

            # projectM-4.dll uses GLEW for GL function loading.
            # GLEW must be explicitly initialised with a valid context current
            # before any projectM call — the SDL2 frontend does this; we do it here.
            _init_glew()

            # Prefer proc-address loader variant (not in this build, but future-proof).
            if _pm_create_with_proc is not None:
                def _gl_load(name: bytes, _ud) -> int:
                    c = QOpenGLContext.currentContext()
                    return c.getProcAddress(name) if c else 0
                self._gl_load_cb = _LOAD_PROC_CB(_gl_load)
                handle = _pm_create_with_proc(self._gl_load_cb, None)
            elif _pm_create is not None:
                handle = _pm_create()
            else:
                raise RuntimeError("no projectm_create symbol found")
            if not handle:
                raise RuntimeError("projectm_create returned null")
            self._pm = handle

            w, h = max(1, self.width()), max(1, self.height())
            if _pm_set_win_size:
                _pm_set_win_size(self._pm, w, h)

            # Tell projectM where to find the bundled textures.
            tex_dir = _PROJECT_LIB_DIR / "textures"
            if tex_dir.is_dir() and _pm_set_tex_paths:
                paths = (ctypes.c_char_p * 1)(str(tex_dir).encode())
                _pm_set_tex_paths(self._pm, paths, 1)
                logger.info(f"Texture path: {tex_dir}")

            if _pm_set_dur:
                _pm_set_dur(self._pm, 20.0)        # 20 s per preset
            if _pm_set_hard_cut:
                _pm_set_hard_cut(self._pm, True)   # beat-driven hard cuts
            if _pm_set_beat_sens:
                _pm_set_beat_sens(self._pm, 1.0)
            if _pm_set_fps:
                _pm_set_fps(self._pm, 60)

            # Let projectM call us back when it wants a new preset
            if _pm_set_switch_cb:
                def _on_switch(hard_cut: bool, _ud) -> None:
                    # Defer: this fires inside the C render stack.
                    # Calling _pm_load_preset re-entrantly crashes the DLL.
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: self._do_next(hard_cut))
                self._cb_ref = _SWITCH_CB(_on_switch)
                _pm_set_switch_cb(self._pm, self._cb_ref, None)

            # Load the first preset directly — GL context is current here, so
            # projectM can compile shaders immediately and be render-ready before
            # the first paintGL call.  Using _pending_load here was the cause of
            # the "access violation on first render" crash: projectM needs at least
            # one frame of separation between load and render, which loading inside
            # initializeGL (one call before paintGL) naturally provides.
            self._current_name = ""
            if self._preset_dir:
                self._presets = scan_presets(self._preset_dir)
                logger.info(f"MilkDrop: {len(self._presets)} presets in {self._preset_dir!r}")
                if self._presets and _pm_load_preset:
                    path = self._presets[self._idx % len(self._presets)]
                    try:
                        _pm_load_preset(self._pm, os.fsencode(str(path)), False)
                        self._current_name = path.stem
                        self.preset_changed.emit(self._current_name)
                    except Exception as exc:
                        logger.warning(f"initializeGL: load_preset failed: {exc}")

            _register(self)
            self._timer.start()
            logger.info("MilkdropWidget ready")
        except Exception as exc:
            logger.error(f"MilkdropWidget.initializeGL: {exc}")
            self._pm = 0

    def resizeGL(self, w: int, h: int) -> None:
        if self._pm and _pm_set_win_size:
            _pm_set_win_size(self._pm, max(1, w), max(1, h))

    def paintGL(self) -> None:
        if not self._pm:
            return

        self._apply_pending_load()

        with self._audio_lock:
            data, self._pending = self._pending, None

        if data is not None and _pm_pcm_add_float is not None:
            try:
                flat = np.ascontiguousarray(data, dtype=np.float32).flatten()
                ptr  = flat.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                _pm_pcm_add_float(self._pm, ptr, len(flat) // 2, _STEREO)
            except Exception:
                pass

        # Render into Qt's widget FBO. QOpenGLWidget always has its own FBO
        # bound when paintGL() is called; passing its ID explicitly ensures
        # projectM writes to the right surface.
        try:
            fbo = self.defaultFramebufferObject()
            if _pm_render_fbo:
                _pm_render_fbo(self._pm, fbo)
            elif _pm_render:
                _pm_render(self._pm)
        except Exception as exc:
            self._render_errors = getattr(self, "_render_errors", 0) + 1
            if self._render_errors <= 3:
                logger.debug(f"render_frame: {exc}")

    def closeEvent(self, event) -> None:
        self._teardown()
        super().closeEvent(event)

    def _teardown(self) -> None:
        self._timer.stop()
        _unregister(self)
        if self._pm:
            try:
                if _pm_destroy:
                    _pm_destroy(self._pm)
            except Exception:
                pass
            self._pm = 0

    # ── audio ──────────────────────────────────────────────────────────

    def _push_audio(self, data: np.ndarray) -> None:
        """Called from the audio thread."""
        with self._audio_lock:
            self._pending = data

    # ── preset management ──────────────────────────────────────────────

    def next_preset(self, hard_cut: bool = False) -> None:
        if self._presets:
            self._do_next(hard_cut)

    def prev_preset(self, hard_cut: bool = False) -> None:
        if self._presets:
            self._idx = (self._idx - 1) % len(self._presets)
            self._load(self._idx, smooth=not hard_cut)

    def preset_count(self) -> int:
        return len(self._presets)

    def current_index(self) -> int:
        return self._idx

    def current_name(self) -> str:
        return self._current_name

    def _do_next(self, hard_cut: bool) -> None:
        self._idx = (self._idx + 1) % max(1, len(self._presets))
        self._load(self._idx, smooth=not hard_cut)

    def _load(self, idx: int, smooth: bool = True) -> None:
        """Queue a preset load; applied inside paintGL where GL context is current."""
        if not self._pm or not self._presets or _pm_load_preset is None:
            return
        self._pending_load = (idx % len(self._presets), smooth)
        self.update()

    def _apply_pending_load(self) -> None:
        """Called from paintGL — GL context is guaranteed current."""
        if self._pending_load is None:
            return
        idx, smooth = self._pending_load
        self._pending_load = None
        path = self._presets[idx % len(self._presets)]
        try:
            _pm_load_preset(self._pm, os.fsencode(str(path)), smooth)
            name = path.stem
            if name != self._current_name:
                self._current_name = name
                self._render_errors = 0
                self.preset_changed.emit(name)
        except Exception as exc:
            logger.warning(f"load_preset({path.name}): {exc}")


# ── fallback placeholder ──────────────────────────────────────────────────

class MilkdropPlaceholder(QWidget):
    """Shown in place of MilkdropWidget when libprojectM is not installed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:#04040c;")
        lbl = QLabel(ERROR_MSG)
        lbl.setStyleSheet(
            "color:#888; font-size:13px; background:transparent; font-family:'Consolas','Courier New',monospace;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()
