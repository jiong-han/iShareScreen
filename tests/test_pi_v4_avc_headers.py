"""Bounded header parsing must agree with the accepted whole-NAL parser."""
import random
import pytest

from isharescreen.proxy.media.avc import _nal_is_keyframe
from isharescreen.proxy.media.bitstream import BitReader, remove_emulation_prevention


def legacy(nalu):
    if len(nalu)<2:return False
    if nalu[0]&31==5:return True
    if nalu[0]&31==1:
        br=BitReader(remove_emulation_prevention(nalu[1:]))
        br.read_ue()
        return br.read_ue() in (2,7)
    return False


def ue(value):
    binary=bin(value+1)[2:]
    return '0'*(len(binary)-1)+binary


def escape(data):
    result=bytearray();zeros=0
    for value in data:
        if zeros>=2 and value<=3:
            result.append(3);zeros=0
        result.append(value)
        zeros=zeros+1 if value==0 else 0
    return bytes(result)


@pytest.mark.parametrize('first_mb',[0,1,120,13500,2**31-1,2**32-1])
@pytest.mark.parametrize('slice_type',range(10))
def test_extreme_exp_golomb_fields_and_escaped_payload(first_mb,slice_type):
    bits=ue(first_mb)+ue(slice_type)+'1'
    bits+='0'*((-len(bits))%8)
    rbsp=int(bits,2).to_bytes(len(bits)//8,'big')+b'\x00\x00\x03'*100
    nalu=b'\x61'+escape(rbsp)
    assert _nal_is_keyframe(nalu)==legacy(nalu)==(slice_type in (2,7))


def test_deterministic_arbitrary_and_truncated_buffers_match_legacy():
    rng=random.Random(8440)
    samples=[b'',b'\x61',b'\x65',b'\x65\x00',b'\x61'+b'\x00'*200]
    samples += [bytes([rng.choice((0x61,0x65,0x67))])+rng.randbytes(rng.randrange(513)) for _ in range(800)]
    for data in samples:assert _nal_is_keyframe(data)==legacy(data)


def test_picture_payload_is_not_read_to_classify_slice():
    class HeaderOnly(bytes):
        def __getitem__(self,key):
            if isinstance(key,slice):
                assert key.stop is not None and key.stop<=65
            return super().__getitem__(key)
    assert _nal_is_keyframe(HeaderOnly(b'\x61\xb0'+b'x'*1_000_000))
    assert not _nal_is_keyframe(HeaderOnly(b'\x61\xc0'+b'x'*1_000_000))
