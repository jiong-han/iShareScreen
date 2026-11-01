"""Wire-format and privacy checks for the Pi input diagnostics controls."""
import struct

import pytest
from Crypto.Cipher import AES

from isharescreen.proxy.input import InputController


class Socket:
    def __init__(self):
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)


class RecordCipher:
    cbc_key = b"a" * 16

    def __init__(self):
        self.records = []

    def encrypt_and_send(self, sock, payload):
        self.records.append(payload)
        sock.sendall(b"encrypted-record")


def controller():
    sock, cipher = Socket(), RecordCipher()
    c = InputController(sock, cipher, server_width=1920, server_height=1080)
    c.set_reference_dims(6144, 3456)
    return c, sock, cipher


def test_default_pointer_keeps_native_wrapper_and_canvas_coordinates():
    c, sock, cipher = controller()
    c.pointer_event(1, 100, 200)
    payload = cipher.records[-1]
    assert payload[:2] == b"\x10\x00"
    plain = AES.new(cipher.cbc_key, AES.MODE_ECB).decrypt(payload[2:])
    assert plain[10:12] == b"\xff\x01"
    assert struct.unpack(">HH", plain[12:]) == (100, 200)
    assert sock.sent == [b"encrypted-record"]


def test_server_space_maps_full_image_edges_without_wraparound():
    c, _, cipher = controller()
    c.set_pointer_policy(protocol="rfb", space="server")
    c.pointer_event(1, 999999, 999999)
    assert struct.unpack(">BBHH", cipher.records[-1]) == (5, 1, 6143, 3455)
    c.pointer_event(0, -100, -200)
    assert struct.unpack(">BBHH", cipher.records[-1]) == (5, 0, 0, 0)
    c.set_server_dims(2560, 1440)
    c.pointer_event(0, 2559, 1439)
    assert struct.unpack(">BBHH", cipher.records[-1]) == (5, 0, 6143, 3455)


def test_legacy_pointer_still_uses_the_encrypted_record_layer():
    c, sock, cipher = controller()
    c.set_pointer_policy(protocol="rfb")
    c.pointer_event(2, 120, 240)
    assert cipher.records == [struct.pack(">BBHH", 5, 2, 120, 240)]
    assert sock.sent == [b"encrypted-record"]


def test_diagnostics_do_not_include_pressed_keys_or_record_keys():
    c, _, _ = controller()
    c.key_event(True, ord("x"))
    c.key_event(False, ord("x"))
    c.set_focus(True)
    s = c.diagnostics()
    assert s["key_event_count"] == 2 and s["focused"] is True
    assert set(s) == {"focused", "pointer_protocol", "pointer_space", "canvas",
                      "server_init", "key_event_count", "pointer_event_count", "last_pointer", "timings_ms",
                      "last_button_down_ms", "last_key_down_ms"}


@pytest.mark.parametrize("kwargs", [{"protocol": "raw"}, {"space": "unknown"}])
def test_invalid_runtime_policies_are_rejected(kwargs):
    c, _, _ = controller()
    with pytest.raises(ValueError):
        c.set_pointer_policy(**kwargs)
