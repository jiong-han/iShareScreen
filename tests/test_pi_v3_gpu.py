"""Compare real V3D pixels with the accepted renderer, including padded rows."""
import dataclasses
import importlib.util
from pathlib import Path
import av
import numpy as np
import pytest
import wgpu
from wgpu.utils import get_default_device
from isharescreen.frontend.desktop.gpu import Renderer
from isharescreen.proxy.media.decode_common import _av_frame_to_tile

spec=importlib.util.spec_from_file_location('reference_gpu_v2',Path(__file__).with_name('reference_gpu_v2.py'))
reference=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def frame_tile(fmt,owned):
    frame=av.VideoFrame(130,74,'yuv444p' if fmt=='nv24' else fmt)
    for n,plane in enumerate(frame.planes):
        grid=(np.arange(plane.buffer_size,dtype=np.uint32)*13+n*37)%256
        plane.update(grid.astype(np.uint8).tobytes())
    tile,error=_av_frame_to_tile(frame,[None],set(),borrow_planes=True)
    assert not error
    if fmt=='nv24':
        u=np.frombuffer(tile.u,np.uint8).reshape(tile.chroma_height,tile.uv_stride)[:,:tile.chroma_width]
        v=np.frombuffer(tile.v,np.uint8).reshape(tile.chroma_height,tile.uv_stride)[:,:tile.chroma_width]
        tile=dataclasses.replace(tile,u=np.stack((u,v),axis=-1).tobytes(),v=None,uv_stride=tile.chroma_width*2)
    if not owned:
        tile=dataclasses.replace(tile,y=bytes(tile.y),u=bytes(tile.u),
            v=bytes(tile.v) if tile.v is not None else None,owner=None)
    return tile


def pixels(device,cls,tile,crop):
    timings=[]
    options={'timing_callback':lambda name,ms:timings.append((name,ms))} if cls is Renderer else {}
    renderer=cls(device,'rgba8unorm',tile.width,tile.height,**options)
    renderer.upload_tile(0,tile,tile.height)
    target=device.create_texture(size=(191,103,1),format='rgba8unorm',
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT|wgpu.TextureUsage.COPY_SRC)
    view=target.create_view()
    renderer.draw(view,191,103)
    renderer.set_source_rect(crop)
    renderer.draw(view,191,103)
    renderer.draw(view,191,103)
    raw=device.queue.read_texture({'texture':target},{'bytes_per_row':768,'rows_per_image':103},(191,103,1))
    result=np.frombuffer(raw,np.uint8).reshape(103,768)[:,:191*4].copy()
    if cls is Renderer:
        assert [n for n,_ in timings]==['gpu_encode','gpu_submit']*3
        assert all(ms>=0 for _,ms in timings)
    target.destroy()
    return result


@pytest.mark.gpu
@pytest.mark.parametrize('fmt',['yuv420p','yuv444p','nv24'])
@pytest.mark.parametrize('crop',[None,(8,4,100,60)])
@pytest.mark.parametrize('owned',[True,False])
def test_stride_upload_and_cached_uniforms_preserve_pixels(fmt,crop,owned):
    tile=frame_tile(fmt,owned)
    dev=get_default_device()
    expected=pixels(dev,reference.Renderer,tile,crop)
    actual=pixels(dev,Renderer,tile,crop)
    assert np.array_equal(expected,actual)
