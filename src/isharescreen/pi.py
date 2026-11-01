"""Opt-in Raspberry Pi desktop profile, with machine-local connection settings."""
from __future__ import annotations

import argparse
import configparser
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys


_SETTINGS = {"connection": {"host", "username"}, "display": {"output", "mode"}}
_PROFILE = {
    "ISS_LOCAL_CURSOR": "1",
    "ISS_FORCE_SW_DECODE": "1",
    "ISS_PI_RESOLUTION_SHORTCUTS": "1",
    "ISS_PI_SWITCH_WAIT_VIDEO": "1",
    "ISS_PI_FRAME_VIEWS": "1",
    "ISS_PI_PERF_STATS": "1",
    "ISS_PI_MAXIMIZE": "1",
    "ISS_PI_MAILBOX": "1",
}
_CLEAR = (
    "ISS_LOG_RFB_OUT", "ISS_NALU_DUMP", "ISS_WT_PROFILE",
    "ISS_AVC_THREAD_MODE", "ISS_AVC_THREADS", "ISS_VIDEO_MAX_QUEUE_MS",
    "ISS_VIDEO_FPS", "ISS_PI_PACK_CHROMA",
)


def _dirs(environ):
    home = Path(environ.get("HOME") or Path.home())
    return {
        "config": Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "isharescreen",
        "state": Path(environ.get("XDG_STATE_HOME") or home / ".local/state") / "isharescreen",
        "applications": Path(environ.get("XDG_DATA_HOME") or home / ".local/share") / "applications",
    }


def _settings(path):
    config = configparser.ConfigParser(interpolation=None)
    if path.is_file():
        with path.open() as handle:
            config.read_file(handle)
    if config.defaults():
        raise ValueError("DEFAULT entries are not supported; use the example configuration")
    for section in config.sections():
        if section not in _SETTINGS or set(config[section]) - _SETTINGS[section]:
            raise ValueError("Unsupported configuration entry; passwords must not be stored here")
    return config


def parser():
    p = argparse.ArgumentParser(description="Pi desktop profile: unlock at 1080p, then switch to 1440p")
    p.add_argument("--config", type=Path, help="local INI file; defaults to XDG_CONFIG_HOME/isharescreen/pi.ini")
    p.add_argument("--host", help="override the local connection host")
    p.add_argument("--user", help="override the local connection username")
    p.add_argument("--output", help="optional Wayland output, paired with --mode")
    p.add_argument("--mode", help="optional wlr-randr mode, paired with --output")
    p.add_argument("--no-mailbox", action="store_true", help="keep the default presentation mode")
    p.add_argument("--audio", action="store_true", help="enable audio; disabled by default in this profile")
    p.add_argument("--dry-run", action="store_true", help="show the command without creating files or connecting")
    p.add_argument("--install-desktop", action="store_true", help="install an application-menu entry for this environment")
    return p


def launch_plan(args, environ, executable):
    """Construct a launch without touching the display, filesystem or network."""
    dirs = _dirs(environ)
    path = args.config or dirs["config"] / "pi.ini"
    if args.config is not None and not path.is_file():
        raise ValueError("The requested configuration file does not exist")
    config = _settings(path)
    host = args.host or config.get("connection", "host", fallback="")
    username = args.user or config.get("connection", "username", fallback="")
    if not host or not username or host.startswith("-") or username.startswith("-"):
        raise ValueError("Set connection host and username in pi.ini or pass --host and --user")
    output = args.output or config.get("display", "output", fallback="")
    mode = args.mode or config.get("display", "mode", fallback="")
    if bool(output) != bool(mode):
        raise ValueError("Display output and mode must be supplied together")
    display = ["wlr-randr", "--output", output, "--mode", mode, "--scale", "1"] if output else []
    env = dict(environ)
    for name in _CLEAR:
        env.pop(name, None)
    env.update(_PROFILE)
    if args.no_mailbox:
        env.pop("ISS_PI_MAILBOX", None)
    runtime = Path(environ.get("XDG_RUNTIME_DIR") or dirs["state"])
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = dirs["state"] / f"pi-{stamp}-{os.getpid()}.log"
    command = [str(executable), "-m", "isharescreen.cli",
               "--host", host, "-u", username, "--password-stdin",
               "--frontend", "desktop", "--codec", "avc", "--advertise", "1920x1080@1",
               "--no-dynamic", "--control-socket", str(runtime / "isharescreen-pi.sock"),
               "--log-file", str(log)]
    if not args.audio:
        command.append("--no-audio")
    return {"command": command, "display": display, "environment": env,
            "state": dirs["state"], "runtime": runtime, "lock": runtime / "isharescreen-pi.lock"}


def install_desktop(environ, executable):
    """Generate the machine-specific executable path locally, never in Git."""
    quoted = str(executable).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    # Desktop Exec quoting differs from shell quoting; no shell is involved.
    quoted = quoted.replace("`", "\\`").replace("$", "\\$")
    destination = _dirs(environ)["applications"] / "isharescreen-pi.desktop"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "[Desktop Entry]\nType=Application\nName=iShareScreen Pi\n"
        "Comment=Unlock at 1080p; Ctrl+Alt+Shift+2 for 1440p, +1 to return\n"
        f'Exec="{quoted}" -m isharescreen.pi\n'
        "Icon=video-display\nTerminal=true\nCategories=Network;RemoteAccess;\nStartupNotify=false\n")
    return destination


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if sys.platform != "linux" and not args.dry_run:
        p.error("This profile runs on Linux; use iss for the standard cross-platform client")
    if args.install_desktop:
        if args.dry_run:
            p.error("Use --install-desktop and --dry-run separately")
        print(install_desktop(os.environ, sys.executable))
        return 0
    try:
        plan = launch_plan(args, os.environ, sys.executable)
    except (ValueError, configparser.Error, OSError) as error:
        p.error(str(error))
    if args.dry_run:
        print(json.dumps({"command": plan["command"], "display": plan["display"],
                          "profile": {name: plan["environment"].get(name) for name in _PROFILE}}, indent=2))
        return 0
    # Private process-local files; no password is accepted in the configuration
    # or command line. The existing CLI reads it interactively from stdin.
    import fcntl
    import resource

    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    plan["state"].mkdir(parents=True, exist_ok=True)
    plan["runtime"].mkdir(parents=True, exist_ok=True)
    fd = os.open(plan["lock"], os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        p.error("Close the current Pi viewer before opening another")
    os.set_inheritable(fd, True)
    try:
        if plan["display"]:
            subprocess.run(plan["display"], env=plan["environment"], check=True)
        print("Starts at 1080p. Unlock, then press Ctrl+Alt+Shift+2 for 1440p; +1 returns.", flush=True)
        print("Enter the Mac password below. Input is hidden and is not saved.", flush=True)
        os.execvpe(plan["command"][0], plan["command"], plan["environment"])
    except (OSError, subprocess.CalledProcessError) as error:
        p.error(str(error))
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
