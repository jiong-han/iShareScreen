import types

from isharescreen.frontend.desktop import pi_presentation as presentation


def test_mailbox_is_surface_local_and_preserves_other_capabilities(monkeypatch):
    monkeypatch.setattr(presentation.wgpu, 'version_info', (0, 32, 0))
    caps = {'present_modes':['immediate','mailbox','fifo'], 'formats':['rgba8unorm']}
    native = types.SimpleNamespace(_capabilities=caps, _get_capabilities=lambda adapter:caps)
    context = types.SimpleNamespace(_wgpu_context=native)
    mode, _ = presentation.prefer_mailbox(context, object())
    assert mode == 'mailbox'
    assert native._capabilities['present_modes'] == ['mailbox']
    assert native._capabilities['formats'] == caps['formats']
    assert caps['present_modes'] == ['immediate','mailbox','fifo']


def test_unknown_version_and_unsupported_surface_retain_defaults(monkeypatch):
    monkeypatch.setattr(presentation.wgpu, 'version_info', (0, 33, 0))
    assert presentation.prefer_mailbox(object(), None)[0] == 'default'
    monkeypatch.setattr(presentation.wgpu, 'version_info', (0, 32, 0))
    assert presentation.prefer_mailbox(object(), None)[0] == 'default'
    caps = {'present_modes':['fifo']}
    native = types.SimpleNamespace(_capabilities=caps, _get_capabilities=lambda adapter:caps)
    assert presentation.prefer_mailbox(types.SimpleNamespace(_wgpu_context=native), None)[0] == 'default'
    assert native._capabilities is caps
