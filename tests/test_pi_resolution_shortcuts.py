"""Replay actual desktop key callbacks and asynchronous in-session requests.

No host connection, credentials, GLFW window or GPU is needed. Callback ASTs
are extracted from app.run so the tests exercise its actual forwarding path.
"""
from __future__ import annotations

import ast
from pathlib import Path
import threading
import time
import types

import glfw
import pytest

from isharescreen.frontend.desktop.keymap import GLFW_KEY_TO_X11
from isharescreen.frontend.desktop.resolution_shortcuts import ResolutionShortcuts
from isharescreen.proxy.protocol.rfb import build_virtual_display
from isharescreen.proxy.session import Session

CHORD = glfw.MOD_CONTROL | glfw.MOD_ALT | glfw.MOD_SHIFT


class FakeInput:
    def __init__(self):
        self.events = []
        self.held = set()

    def key_event(self, down, keysym):
        self.events.append((down, keysym))
        (self.held.add if down else self.held.discard)(keysym)


class FakeSession:
    def __init__(self, *, acknowledge=True):
        self.canvas_dims = (1920, 1080)
        self.is_connected = True
        self.input = FakeInput()
        self.calls = []
        self.acknowledge = acknowledge
        self.entered = threading.Event()
        self.release = None
        self.fail = False

    def send_dynamic_resolution(self, width, height, *, hidpi_scale):
        self.calls.append((width, height, hidpi_scale))
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(2), "test did not release blocked network call"
        if self.fail:
            raise OSError("synthetic disconnected transport")
        if self.acknowledge:
            self.canvas_dims = (width, height)


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("worker condition not reached")


def tap(switcher, digit):
    assert switcher.handle_key(ord(digit), glfw.PRESS, CHORD)
    assert switcher.handle_key(ord(digit), glfw.RELEASE, 0)


def callbacks(session, *, enabled=True):
    src = Path(__file__).parents[1] / "src/isharescreen/frontend/desktop/app.py"
    tree = ast.parse(src.read_text())
    names = {"on_key", "on_char", "on_key2", "on_char2", "release_switch_modifiers"}
    functions = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(functions) == len(names)
    ns = dict(glfw=glfw, session=session, ctrl_as_cmd=False,
              GLFW_KEY_TO_X11=GLFW_KEY_TO_X11,
              _KEYSYM_SUPER_L=0xffeb, _KEYSYM_SUPER_R=0xffec)
    exec(compile(ast.fix_missing_locations(ast.Module(functions, [])), str(src), "exec"), ns)
    switcher = (ResolutionShortcuts(session, ns["release_switch_modifiers"],
                                   min_interval=0, confirmation_timeout=0.2)
                if enabled else None)
    ns["resolution_shortcuts"] = switcher
    return ns, switcher


@pytest.mark.parametrize("key_name,char_name", [("on_key", "on_char"),
                                              ("on_key2", "on_char2")])
def test_actual_callbacks_capture_chord_and_release_remote_modifiers(key_name, char_name):
    session = FakeSession()
    ns, switcher = callbacks(session)
    key, char = ns[key_name], ns[char_name]
    try:
        modifiers = [glfw.KEY_LEFT_CONTROL, glfw.KEY_LEFT_ALT, glfw.KEY_LEFT_SHIFT]
        for k in modifiers:
            key(None, k, 0, glfw.PRESS, CHORD)
        assert session.input.held
        key(None, glfw.KEY_2, 0, glfw.PRESS, CHORD)
        char(None, ord("@"))  # some layouts also emit a printable callback
        key(None, glfw.KEY_2, 0, glfw.REPEAT, CHORD)
        for k in modifiers:  # release modifiers before the captured digit
            key(None, k, 0, glfw.RELEASE, 0)
        key(None, glfw.KEY_2, 0, glfw.RELEASE, 0)
        wait_for(lambda: switcher.status == "1440p")
        assert session.calls == [(2560, 1440, 1.0)]
        assert not session.input.held
        assert not any(k in (ord("2"), ord("@")) for _, k in session.input.events)
        char(None, ord("x"))
        assert session.input.events[-2:] == [(True, ord("x")), (False, ord("x"))]
        # Ordinary Ctrl+2 still reaches the host, including its release.
        key(None, glfw.KEY_2, 0, glfw.PRESS, glfw.MOD_CONTROL)
        key(None, glfw.KEY_2, 0, glfw.RELEASE, glfw.MOD_CONTROL)
        assert session.input.events[-2:] == [(True, ord("2")), (False, ord("2"))]
    finally:
        switcher.close()


def test_disabled_entry_preserves_original_key_and_char_forwarding():
    session = FakeSession()
    ns, switcher = callbacks(session, enabled=False)
    assert switcher is None
    ns["on_key"](None, glfw.KEY_2, 0, glfw.PRESS, CHORD)
    ns["on_key"](None, glfw.KEY_2, 0, glfw.RELEASE, CHORD)
    ns["on_char"](None, ord("z"))
    assert session.input.events == [(True, ord("2")), (False, ord("2")),
                                    (True, ord("z")), (False, ord("z"))]
    assert not session.calls


def test_network_work_is_off_callback_thread_and_pending_choices_coalesce():
    session = FakeSession()
    session.release = threading.Event()
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0)
    try:
        tap(switcher, "2")
        assert session.entered.wait(1)
        # This call has returned while the network worker remains blocked.
        assert not session.release.is_set()
        for digit in "121":
            tap(switcher, digit)
        session.release.set()
        wait_for(lambda: switcher.status == "1080p" and len(session.calls) == 2)
        assert session.calls == [(2560, 1440, 1.0), (1920, 1080, 1.0)]
    finally:
        session.release.set()
        switcher.close()


def test_return_can_supersede_unconfirmed_resize_even_at_old_canvas_size():
    session = FakeSession(acknowledge=False)
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0.02,
                                   confirmation_timeout=1)
    try:
        tap(switcher, "2")
        assert session.entered.wait(1)
        tap(switcher, "1")
        wait_for(lambda: switcher.status == "1080p" and len(session.calls) == 2)
        assert session.calls[-1] == (1920, 1080, 1.0)
    finally:
        switcher.close()


def test_unconfirmed_resize_reports_timeout_without_retry_or_reconnect():
    session = FakeSession(acknowledge=False)
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0,
                                   confirmation_timeout=0.05)
    try:
        tap(switcher, "2")
        wait_for(lambda: "not confirmed" in switcher.status)
        assert session.calls == [(2560, 1440, 1.0)]
        assert session.canvas_dims == (1920, 1080)
    finally:
        switcher.close()


def test_failed_request_keeps_worker_available_for_return():
    session = FakeSession()
    session.fail = True
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0)
    try:
        tap(switcher, "2")
        wait_for(lambda: "request failed" in switcher.status)
        session.fail = False
        tap(switcher, "1")
        wait_for(lambda: switcher.status == "1080p" and len(session.calls) == 2)
    finally:
        switcher.close()


def test_closed_or_disconnected_session_does_not_send_resize():
    session = FakeSession()
    session.is_connected = False
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0)
    try:
        assert not switcher.handle_key(glfw.KEY_2, glfw.PRESS, glfw.MOD_CONTROL)
        tap(switcher, "2")
        wait_for(lambda: "Disconnected" in switcher.status)
        assert session.calls == []
    finally:
        switcher.close()
    tap(switcher, "1")
    assert session.calls == []


def test_shortcut_uses_existing_encrypted_session_and_true_1440p_wire_geometry():
    records, firs = [], []
    live = types.SimpleNamespace(
        _negotiation=types.SimpleNamespace(
            sock=object(), cipher=types.SimpleNamespace(
                encrypt_and_send=lambda _sock, message: records.append(message))),
        request_fir=lambda: firs.append(True))
    session = FakeSession()

    def native_resize(width, height, *, hidpi_scale):
        Session.send_dynamic_resolution(live, width, height, hidpi_scale=hidpi_scale)
        session.canvas_dims = (width, height)

    session.send_dynamic_resolution = native_resize
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0)
    try:
        tap(switcher, "2")
        wait_for(lambda: switcher.status == "1440p")
        assert records[0] == build_virtual_display(
            width=2560, height=1440, hidpi_scale=1.0, hdr=False)
        assert records[0][0] == 0x1d
        assert records[1][0] == 0x03  # refresh over the same encrypted channel
        assert firs == [True]
    finally:
        switcher.close()
