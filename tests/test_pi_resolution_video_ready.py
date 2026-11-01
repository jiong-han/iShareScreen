"""v2 readiness uses a new presented frame, not just a canvas acknowledgement."""
from isharescreen.frontend.desktop.resolution_shortcuts import ResolutionShortcuts
from test_pi_resolution_shortcuts import FakeSession, tap, wait_for


def test_layout_alone_and_old_or_wrong_frame_do_not_confirm():
    session = FakeSession()
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0,
                                   confirmation_timeout=1, wait_for_video=True)
    try:
        switcher.note_presented(1920, 1080)
        tap(switcher, "2")
        wait_for(lambda: "waiting for video" in switcher.status)
        switcher.note_presented(1920, 1080)
        assert "waiting for video" in switcher.status
        switcher.note_presented(2560, 1440)
        wait_for(lambda: switcher.status == "1440p video ready")
    finally:
        switcher.close()


def test_noop_at_current_ready_resolution_does_not_restart_stream():
    session = FakeSession()
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0,
                                   wait_for_video=True)
    try:
        switcher.note_presented(1920, 1080)
        tap(switcher, "1")
        wait_for(lambda: switcher.status == "1080p video ready")
        assert session.calls == []
    finally:
        switcher.close()


def test_pending_return_waits_for_first_switch_video_then_sends():
    session = FakeSession()
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0,
                                   confirmation_timeout=1, wait_for_video=True)
    try:
        tap(switcher, "2")
        wait_for(lambda: "waiting for video" in switcher.status)
        tap(switcher, "1")
        # Pending choice does not interrupt SPS/DPB setup of the first resize.
        assert session.calls == [(2560, 1440, 1.0)]
        switcher.note_presented(2560, 1440)
        wait_for(lambda: len(session.calls) == 2)
        switcher.note_presented(1920, 1080)
        wait_for(lambda: switcher.status == "1080p video ready")
    finally:
        switcher.close()


def test_video_timeout_does_not_report_success_or_retry():
    session = FakeSession()
    switcher = ResolutionShortcuts(session, lambda: None, min_interval=0,
                                   confirmation_timeout=0.05, wait_for_video=True)
    try:
        tap(switcher, "2")
        wait_for(lambda: "video not ready" in switcher.status)
        assert session.calls == [(2560, 1440, 1.0)]
    finally:
        switcher.close()
