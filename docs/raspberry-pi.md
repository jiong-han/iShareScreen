# Raspberry Pi 4B desktop profile

This fork adds an opt-in Linux profile based on a Pi 4B (8 GB) running
Debian 13, Wayland and Mesa V3D/Vulkan. It starts remote video at
1920×1080 for unlocking, then lets you request 2560×1440 on the same
authenticated connection. The standard `iss` entry remains available. Close other remote viewers
before starting this profile.

The protocol, virtual-display support and underlying resize API come from
[renegadelink/iShareScreen](https://github.com/renegadelink/iShareScreen).
Window identification hints were adapted from
[sjwasko's upstream PR #28](https://github.com/renegadelink/iShareScreen/pull/28).
This fork retains the upstream AGPL-3.0-or-later license.

## Install

Install the Linux dependencies described in the main README. In a checked-out
copy of this fork, use a virtual environment and the tested video/window
constraints:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c contrib/raspberry-pi/constraints.txt -e '.[test]'
mkdir -p ~/.config/isharescreen
cp contrib/raspberry-pi/pi.ini.example ~/.config/isharescreen/pi.ini
```

During stacked-PR review, check out the final PR's branch before installing.
After the stack is merged, use `main`. The original Pi measurements used the performance CPU governor, adequate
cooling and 5 GHz Wi-Fi with power saving disabled. This profile does not
automatically change those system settings. The constraints cover four packages,
not every transitive dependency or every supported platform. Python 3.13
was used for the original Pi validation.

Edit the local INI with your Mac's host and account name. It accepts no
password or token fields. Keep this file outside Git. You can instead
pass the host and username when launching:

```sh
.venv/bin/iss-pi --host mac.example.invalid --user remote-user
```

The address and username above are placeholders. The existing client prompts
for the Mac password through stdin; the profile does not save it.

To add an application-menu entry with this virtual environment's executable:

```sh
.venv/bin/iss-pi --install-desktop
```

The generated desktop file contains the local executable path, so generate
it on the destination machine rather than committing it. It opens a terminal
for password entry. The profile uses a single-instance lock.

## Display and controls

- The local output mode is preserved by default. Set it to 1440p using your
  desktop settings if desired. To request a mode from the profile, install
  `wlr-randr` and set both `[display] output` and `mode` in the INI. Pick an
  actual mode shown by `wlr-randr`; the profile uses local scale 1.
- The viewer starts maximized independently of the initial 1080p video.
- Unlock the Mac, focus the viewer and press **Ctrl+Alt+Shift+2** for 1440p.
  **Ctrl+Alt+Shift+1** returns to 1080p. Use the top-row number keys.
- The connection is retained, but the Mac must restart its video stream.
  The title distinguishes layout acknowledgement from newly submitted video.
  Consecutive choices are coalesced; duplicate ready-size requests do not
  restart the stream. `video ready` means client draw submission, not
  physical display completion.
- There is no automatic lock-state detection. Switch back to 1080p before
  locking if the larger stream makes unlocking sluggish.
- 1440p uses a 1× logical desktop. This provides more space and smaller UI
  than 1080p at the same panel size; no new fractional UI scaling is provided.

The profile selects software H.264 with upstream low-delay SLICE threading,
a local system cursor, borrowed CPU frame planes, bounded numeric telemetry,
and guarded mailbox presentation. Audio is off by default; `--audio` enables
it. These are profile choices, not global changes to `iss`. The profile
does not change saved Mac settings; it uses the existing remote session's
virtual-display negotiation.

Mailbox currently uses a surface-local wgpu 0.32 capability adapter. It falls
back to the default for unknown versions or unsupported surfaces.
`--no-mailbox` disables the preference explicitly. No dependency source or
system driver is patched. The fork adds no Pi hardware video decoder.

## What changed and what was measured

- H.264 slice classification reads a bounded header instead of scanning the
  entire compressed picture. The decoder still receives the complete NAL.
- RTP groups track sequence membership and marker presence alongside each
  group; sorting, repair and reference-recovery rules remain intact.
- Cursor updates stay on the UI thread; empty shapes restore the system
  arrow. Button callbacks remap the current pointer position at click time.
- Read-only frame-plane views retain their AVFrame owner; stride-aware GPU
  uploads avoid packing padded rows, and unchanged uniforms are reused.
- The UI pumps input again after upload, before a potentially blocking draw.
- Numeric timings distinguish packet wait, header work, decode, frame
  conversion, upload, surface acquisition and presentation-related calls.

Historical Pi synthetic testing compared V3 and V4 using the same 64-frame,
single-slice 1440p fixtures. Complex-content grouping/processing/decode
fell from about 56.5 to 29.5 ms/frame, while low-detail content improved
from about 16.1 to 15.0–15.4 ms. Decoded Y/U/V pixels matched; FFmpeg decode
itself did not become twice as fast. Earlier 1440p plane extraction measured
about 2.43 ms with copies versus 0.024 ms with borrowed views. These are
isolated stage measurements, not end-to-end latency claims.

An interactive V4 session reached roughly 30 draw submissions/second during
steady updates, but heavy content still produced about 2.18 seconds of
packet backlog. The workload was not a controlled original-versus-V4 replay.
This does not establish displayed 60 FPS, 4K performance, or a fixed overall
speedup. Future improvements need to address decode/source throughput.

The former FRAME-thread and stale-compressed-packet-drop experiments are
excluded from this stack. They had latency/reference-recovery tradeoffs.
An advertised 30 FPS capability flag was not a verified source-rate limit,
and is excluded too.

## Test and diagnose

```sh
# Unit, real software-decode and input/resize tests; no remote host required.
.venv/bin/python -m pytest -o addopts= -q -m 'not gpu'

# Offscreen synthetic pixel comparisons; requires a working native GPU adapter.
.venv/bin/python -m pytest -o addopts= -q -m gpu

# Inspect the local launch plan without connecting or writing state.
.venv/bin/iss-pi --dry-run
```

GPU tests fail if the environment cannot access an adapter; they are not
silently skipped. Pixel tests cover 420, 444 and NV24-like buffers, padded
rows, borrowed/copied planes and crop changes. CI runs the non-GPU tests;
it is not a replacement for V3D testing or an interactive Pi session.

Numeric logs are stored under `$XDG_STATE_HOME/isharescreen` (normally
`~/.local/state/isharescreen`) and the local control socket under
`$XDG_RUNTIME_DIR`. Timings do not include key values or clipboard contents.
Input diagnostics can contain coordinates and event times, and ordinary
session logs can identify the host/account. Do not publish raw logs, captures,
media dumps, local configuration or generated desktop files. The profile
clears inherited raw-input and media-dump flags and disables core dumps.

The browser bridge now binds loopback, but this is not complete viewer
authentication. Existing upstream authentication limitations remain:
server SRP proof/parameter validation and automatic legacy-auth fallback
have not been hardened by these performance changes. Do not describe this
fork as security-audited or these limitations as fixed.
