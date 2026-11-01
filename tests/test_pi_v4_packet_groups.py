"""Large/duplicate/reordered AUs preserve the existing RTP ordering rules."""
import random
import time

from isharescreen.proxy.session import Session, _VideoPacketGroup


def session():
    s=Session.__new__(Session)
    s._video_codec='avc'
    s._pending_groups={};s._group_arrival={};s._recently_flushed={}
    s._group_repair_deadline={};s._last_group_marker_seq={}
    s.flushed=[]
    def flush(key):
        packets=s._sorted_group_packets(s._pending_groups.pop(key))
        s.flushed.append((key,packets))
        s._group_arrival.pop(key,None);s._group_repair_deadline.pop(key,None)
        s._last_group_marker_seq[key[0]]=packets[-1][0]
        s._recently_flushed[key]=time.monotonic()
    s._flush_group=flush
    return s


def test_large_wrapped_group_with_retransmits_flushes_exactly_once():
    s=session();start=65520;n=320;key=(100,200)
    s._last_group_marker_seq[100]=(start-1)&65535
    packets=[((start+i)&65535,i==n-1,bytes([i%256])) for i in range(n)]
    for packet in packets:
        s._queue_video_group_packet(*key,*packet)
        s._queue_video_group_packet(*key,*packet)
    assert s.flushed==[(key,packets)]
    assert s._pending_groups=={}


def test_early_marker_and_reordered_retransmits_do_not_skip_a_hole():
    s=session();key=(200,300);n=257
    s._last_group_marker_seq[200]=99
    packets=[(100+i,i==n-1,bytes([i%256])) for i in range(n)]
    order=packets[:-1];random.Random(29).shuffle(order)
    s._queue_video_group_packet(*key,*packets[-1])
    for packet in order[:-1]:
        s._queue_video_group_packet(*key,*packet)
        s._queue_video_group_packet(*key,*packet)
    assert not s.flushed
    s._queue_video_group_packet(*key,*order[-1])
    assert s.flushed==[(key,packets)]


def test_plain_burst_lists_stay_compatible_and_clear_discards_cached_state():
    s=session();key=(300,400)
    s._pending_groups[key]=[(1,False,b'a')]
    s._group_arrival[key]=time.monotonic()
    s._queue_video_group_packet(*key,1,False,b'ignored-duplicate')
    s._queue_video_group_packet(*key,2,True,b'b')
    assert s.flushed==[(key,[(1,False,b'a'),(2,True,b'b')])]
    s._recently_flushed.clear();s._last_group_marker_seq.clear()
    s._queue_video_group_packet(*key,1,False,b'old')
    assert isinstance(s._pending_groups[key],_VideoPacketGroup)
    s._pending_groups.clear();s._group_arrival.clear()
    s._queue_video_group_packet(*key,1,False,b'new')
    s._queue_video_group_packet(*key,2,True,b'end')
    assert s.flushed[-1][1]==[(1,False,b'new'),(2,True,b'end')]
