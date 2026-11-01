"""Replay real callbacks without a window, host connection or captured input."""
import ast
import logging
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).parents[1] / "src/isharescreen/frontend/desktop/app.py"


def callback(name, namespace):
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(nodes) == 1
    node = nodes[0]
    node.body = [ast.Global(n.names) if isinstance(n, ast.Nonlocal) else n for n in node.body]
    exec(compile(ast.fix_missing_locations(ast.Module([node], [])), str(SOURCE), "exec"), namespace)
    return namespace[name]


def test_first_click_and_layout_change_use_current_pointer_position():
    sent = []
    pos = [20, 30]
    scale = [1]
    ns = dict(button_mask=0, cursor=(999, 999), _mw_views=[], glfw_window=object(),
              glfw=SimpleNamespace(PRESS=1, RELEASE=0, get_cursor_pos=lambda window: tuple(pos)),
              glfw_button_to_rfb_bit=lambda button: 1,
              to_canvas=lambda x, y: (x * scale[0], y * scale[0]),
              session=SimpleNamespace(input=SimpleNamespace(pointer_event=lambda *args: sent.append(args))))
    click = callback("on_mouse_button", ns)
    click(None, 0, 1, 0)
    scale[0] = 2
    click(None, 0, 0, 0)
    assert sent == [(1, 20, 30), (0, 40, 60)]


@pytest.mark.parametrize("image", [None, SimpleNamespace(width=0, height=0, rgba=b""),
                                  SimpleNamespace(width=1, height=1, rgba=b"\x10\x20\x30\x00")])
def test_empty_cursor_restores_system_pointer(image):
    calls = []
    ns = dict(_cursor_state={"img": object()}, _glfw_cursor_handle_cache={},
              glfw_window=object(), glfw=SimpleNamespace(set_cursor=lambda *args: calls.append(args)),
              log=logging.getLogger(__name__))
    apply = callback("_set_cursor_now", ns)
    apply(image)
    assert len(calls) == 1 and calls[0][1] is None
    assert ns["_cursor_state"] == {"img": None, "handle": None}


def test_network_cursor_callback_defers_glfw_until_ui_thread():
    image = object()
    ns = dict(_canvas_cursor=False, _cursor_direct_apply=False,
              _cursor_lock=threading.Lock(), _pending_cursor={"img": None},
              _set_cursor_now=lambda image: pytest.fail("GLFW called on worker thread"))
    on_cursor = callback("_on_cursor", ns)
    worker = threading.Thread(target=on_cursor, args=(image,))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert ns["_pending_cursor"]["img"] is image
