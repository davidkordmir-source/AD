"""Startup logging before importing Qt or native GIS bindings."""

import faulthandler
import logging
import os
from pathlib import Path
import sys
import tempfile
import traceback


# Set this before native GIS imports in the standalone entry point.
os.environ["PROJ_NETWORK"] = "OFF"

_fast_log_stream = None
_fast_log_path = None


def enable_fast_logging():
    global _fast_log_stream, _fast_log_path
    if _fast_log_stream is not None:
        return _fast_log_path
    folder = Path(tempfile.gettempdir())/"FastViewshed_logs"
    folder.mkdir(exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="fast_", suffix=".log", dir=str(folder))
    _fast_log_path = Path(name)
    _fast_log_stream = os.fdopen(descriptor, "a", encoding="utf-8", buffering=1)
    _fast_log_stream.write(f"Python: {sys.version}\nExecutable: {sys.executable}\n")
    faulthandler.enable(file=_fast_log_stream, all_threads=True)
    logger = logging.getLogger("fast_viewshed")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(_fast_log_stream))
    if sys.stderr is None:
        sys.stderr = _fast_log_stream
    if sys.stdout is None:
        sys.stdout = _fast_log_stream
    return _fast_log_path


def fast_startup_error(exc):
    path = enable_fast_logging()
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logging.getLogger("fast_viewshed").error(detail)
    if sys.stderr is not None:
        sys.stderr.write(detail+"\nLog: "+str(path)+"\n")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"{exc}\n\nLog: {path}", "Fast Viewshed startup error", 0x10)
        except Exception:
            pass
