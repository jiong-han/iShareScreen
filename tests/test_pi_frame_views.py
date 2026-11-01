"""Real PyAV buffer lifetime, decoder telemetry and GPU pixel equivalence."""
import gc
import re

import av
import numpy as np
import pytest

from isharescreen.proxy.media.avc import AvcDecoder
from isharescreen.proxy.media.decode_common import _av_frame_to_tile
from avc_fixtures import SAMPLE


def patterned_frame(width=130, height=74):
    frame = av.VideoFrame(width, height, "yuv420p")
    for n, plane in enumerate(frame.planes):
        values = (np.arange(plane.buffer_size, dtype=np.uint16) + n * 37) % 256
        plane.update(values.astype(np.uint8).tobytes())
    return frame


def test_views_preserve_stride_content_and_owner_after_gc():
    frame = patterned_frame()
    copied, err1 = _av_frame_to_tile(frame, [None], set())
    borrowed, err2 = _av_frame_to_tile(frame, [None], set(), borrow_planes=True)
    assert not err1 and not err2
    assert copied.owner is None and borrowed.owner is frame
    assert (copied.y_stride, copied.uv_stride) == (borrowed.y_stride, borrowed.uv_stride)
    assert all(isinstance(p, memoryview) and p.readonly
               for p in (borrowed.y, borrowed.u, borrowed.v))
    expected = [bytes(p) for p in (borrowed.y, borrowed.u, borrowed.v)]
    assert expected == [copied.y, copied.u, copied.v]
    del frame
    gc.collect()
    for _ in range(20):
        patterned_frame()
    assert [bytes(p) for p in (borrowed.y, borrowed.u, borrowed.v)] == expected


def test_real_avc_decode_emits_views_and_stage_timings(monkeypatch):
    monkeypatch.setenv("ISS_PI_FRAME_VIEWS", "1")
    decoder = AvcDecoder(1, prefer_hwaccel=False, enable_quality_gate=False)
    nalus = [n for n in re.split(b"\x00\x00\x00\x01|\x00\x00\x01", SAMPLE) if n]
    sps = next(n for n in nalus if n[0] & 31 == 7)
    pps = next(n for n in nalus if n[0] & 31 == 8)
    decoder.set_params(b"", sps, {0: pps})
    decoder.start()
    timings, frames = [], []
    decoder.set_timing_callback(lambda name, value: timings.append((name, value)))
    try:
        for nalu in nalus:
            if nalu[0] & 31 in (1, 5):
                decoder.feed_nalu(nalu, 0)
                tile = decoder.get_frame(0)
                if tile is not None:
                    frames.append(tile)
        assert len(frames) == 6
        assert all(isinstance(f.y, memoryview) and isinstance(f.owner, av.VideoFrame)
                   for f in frames)
        assert sum(name == "decode" for name, _ in timings) == 6
        assert sum(name == "convert" for name, _ in timings) == 6
        assert all(value >= 0 for _, value in timings)
        first = bytes(frames[0].y)
    finally:
        decoder.close()
    gc.collect()
    assert bytes(frames[0].y) == first


@pytest.mark.gpu
def test_real_gpu_upload_and_render_matches_copied_planes():
    import wgpu
    from wgpu.utils import get_default_device
    from isharescreen.frontend.desktop.gpu import Renderer

    device = get_default_device()
    frame = patterned_frame()
    copied, _ = _av_frame_to_tile(frame, [None], set())
    borrowed, _ = _av_frame_to_tile(frame, [None], set(), borrow_planes=True)
    del frame
    gc.collect()
    pixels = []
    width, height = copied.width, copied.height
    row_bytes = ((width * 4 + 255) // 256) * 256
    for tile in (copied, borrowed):
        renderer = Renderer(device, "rgba8unorm", width, height)
        target = device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        renderer.upload_tile(0, tile, height)
        renderer.draw(target.create_view(), width, height)
        raw = device.queue.read_texture(
            {"texture": target}, {"bytes_per_row": row_bytes, "rows_per_image": height},
            (width, height, 1))
        pixels.append(np.frombuffer(raw, np.uint8).reshape(height, row_bytes)[:, :width * 4].copy())
        target.destroy()
    assert np.array_equal(pixels[0], pixels[1])
