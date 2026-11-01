"""Small version-guarded bridge for mailbox on this Pi's wgpu 0.32 runtime.

wgpu-py exposes vsync, but its vsync=False prefers immediate over mailbox.
Restrict only this surface's cached modes to mailbox, preserving synchronized
presentation without the FIFO's queue. Unknown API versions retain defaults.
"""
from __future__ import annotations

import wgpu


def prefer_mailbox(context, adapter) -> tuple[str, str]:
    if tuple(wgpu.version_info[:2]) != (0, 32):
        return "default", "unverified wgpu API version"
    native = getattr(context, "_wgpu_context", None)
    if native is None or not hasattr(native, "_get_capabilities"):
        return "default", "not a native screen context"
    try:
        capabilities = native._get_capabilities(adapter)
        if "mailbox" not in capabilities.get("present_modes", ()):
            return "default", "mailbox unavailable"
        native._capabilities = dict(capabilities, present_modes=["mailbox"])
        return "mailbox", "surface-local mode preference"
    except (AttributeError, TypeError, KeyError):
        return "default", "unrecognized surface capabilities"
