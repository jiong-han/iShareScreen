"""Opt-in Pi resolution shortcuts; network work never runs in GLFW callbacks."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

# GLFW's stable key/action/modifier values. Keeping this module independent of
# GLFW lets its asynchronous input behaviour be exercised without a GPU/window.
_PROFILES = {49: (1920, 1080), 50: (2560, 1440)}  # top-row 1 / 2
_CHORD = 0x0001 | 0x0002 | 0x0004  # Shift + Ctrl + Alt; no VT keys
_SUPER = 0x0008
_PRESS, _RELEASE = 1, 0


def _label(dims: tuple[int, int]) -> str:
    return {(1920, 1080): "1080p", (2560, 1440): "1440p"}.get(
        dims, f"{dims[0]}x{dims[1]}")


class ResolutionShortcuts:
    """Keep one live session and serialize/coalesce explicit resize requests.

    The v2 opt-in waits for both layout and a newly presented matching frame.
    No lock-state guessing, automatic resolution change, or reconnect is done.
    """

    def __init__(self, session, release_modifiers: Callable[[], None], *,
                 min_interval: float = 2.5, confirmation_timeout: float = 10.0,
                 wait_for_video: bool = False):
        self._session = session
        self._release_modifiers = release_modifiers
        self._min_interval = min_interval
        self._confirmation_timeout = confirmation_timeout
        self._wait_for_video = wait_for_video
        self._presented_serial = 0
        self._presented_dims = None
        self._ready_dims = None
        self._awaiting = False
        self._captured: set[int] = set()
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._pending: tuple[int, int] | None = None
        self._status = _label(tuple(session.canvas_dims))
        self._worker = threading.Thread(
            target=self._run, name="iss-pi-resolution", daemon=True)
        self._worker.start()

    @property
    def status(self) -> str:
        with self._cv:
            return self._status

    @property
    def suppress_chars(self) -> bool:
        return bool(self._captured)

    @property
    def wait_for_video(self) -> bool:
        return self._wait_for_video

    def note_presented(self, width: int, height: int) -> None:
        """Called by the UI after submitting a fresh, full-canvas video frame."""
        dims = (width, height)
        canvas = tuple(self._session.canvas_dims)
        with self._cv:
            self._presented_serial += 1
            self._presented_dims = dims
            if not self._awaiting and dims == canvas:
                self._ready_dims = dims
            self._cv.notify()

    def handle_key(self, key: int, action: int, mods: int) -> bool:
        # Capture repeats AND release even if the user releases modifiers first.
        if key in self._captured:
            if action == _RELEASE:
                self._captured.discard(key)
            return True
        if (action != _PRESS or key not in _PROFILES
                or mods & _CHORD != _CHORD or mods & _SUPER):
            return False
        self._captured.add(key)
        # Modifier presses preceded the digit and may already be on the Mac.
        # Release them before consuming the chord so the host cannot stay stuck
        # with Ctrl/Alt/Shift held during a layout transition.
        self._release_modifiers()
        dims = _PROFILES[key]
        with self._cv:
            if not self._stop.is_set():
                self._pending = dims
                self._status = f"Queued {_label(dims)}"
                self._cv.notify()
        return True

    def close(self) -> None:
        self._stop.set()
        with self._cv:
            self._pending = None
            self._cv.notify()
        self._worker.join(timeout=0.5)

    def _set_status(self, text: str) -> None:
        with self._cv:
            self._status = text

    def _run(self) -> None:
        last_send = float("-inf")
        while not self._stop.is_set():
            with self._cv:
                self._cv.wait_for(
                    lambda: self._pending is not None or self._stop.is_set())
                if self._stop.is_set():
                    return
            # Space requests as the existing automatic-resize frontend does.
            # Keep only the latest pending choice while waiting, never a FIFO
            # of repeated resize commands behind a slow TCP operation.
            if self._stop.wait(max(0.0, last_send + self._min_interval
                                   - time.monotonic())):
                return
            with self._cv:
                if self._stop.is_set():
                    return
                dims, self._pending = self._pending, None
            if dims is None:
                continue
            if not self._session.is_connected:
                self._set_status("Disconnected; resize not sent")
                continue
            name = _label(dims)
            with self._cv:
                if (self._wait_for_video and self._ready_dims == dims
                        and tuple(self._session.canvas_dims) == dims):
                    self._status = f"{name} video ready"
                    log.info("Pi shortcut: already at %s with video; no resize sent", name)
                    continue
                self._awaiting = True
                self._ready_dims = None
                presented_before = self._presented_serial
            self._set_status(f"Switching to {name}")
            try:
                # Explicit 1x is essential: 1440p here means 2560x1440 pixels,
                # not a 2x request that exceeds the host's 4K canvas limit.
                last_send = time.monotonic()
                self._session.send_dynamic_resolution(*dims, hidpi_scale=1.0)
            except Exception:
                log.exception("Pi shortcut: %s resize request failed", name)
                self._set_status(f"{name} request failed; use Ctrl+Alt+Shift+1")
                with self._cv:
                    self._awaiting = False
                continue
            log.info("Pi shortcut: requested %s on existing session, scale=1", name)
            deadline = time.monotonic() + self._confirmation_timeout
            layout_logged = ready = False
            while not self._stop.is_set():
                layout_matches = tuple(self._session.canvas_dims) == dims
                with self._cv:
                    video_matches = (self._presented_dims == dims
                                     and self._presented_serial > presented_before)
                if layout_matches:
                    if not layout_logged:
                        log.info("Pi shortcut: canvas confirmed %s (%dx%d)", name, *dims)
                        layout_logged = True
                    if not self._wait_for_video or video_matches:
                        ready = True
                        self._set_status(f"{name} video ready" if self._wait_for_video else name)
                        if self._wait_for_video:
                            log.info("Pi shortcut: video ready %s after %.3fs", name,
                                     time.monotonic() - last_send)
                        break
                    self._set_status(f"{name} layout ready; waiting for video")
                if not self._session.is_connected:
                    self._set_status("Disconnected during resize")
                    break
                with self._cv:
                    superseded = self._pending is not None and self._pending != dims
                if (superseded and not self._wait_for_video
                        and time.monotonic() >= last_send + self._min_interval):
                    break
                if time.monotonic() >= deadline:
                    kind = "video not ready" if self._wait_for_video else "not confirmed"
                    self._set_status(f"{name} {kind}; Ctrl+Alt+Shift+1 to return")
                    log.warning("Pi shortcut: %s %s after %.1fs", name, kind,
                                self._confirmation_timeout)
                    break
                self._stop.wait(0.05)
            with self._cv:
                self._awaiting = False
                if ready:
                    self._ready_dims = dims
