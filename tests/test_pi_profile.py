"""The portable profile needs no real host, user account or display to test."""
import configparser
from pathlib import Path

import pytest

from isharescreen import pi


def environment(tmp_path):
    return {"HOME": str(tmp_path), "XDG_RUNTIME_DIR": str(tmp_path / "runtime")}


def test_profile_uses_interactive_password_and_clears_recording_flags(tmp_path):
    env = environment(tmp_path)
    env.update({name: "inherited" for name in pi._CLEAR})
    args = pi.parser().parse_args(["--host", "mac.example.invalid", "--user", "remote-user"])
    plan = pi.launch_plan(args, env, "/opt/venv/bin/python")
    command = plan["command"]
    assert command[:3] == ["/opt/venv/bin/python", "-m", "isharescreen.cli"]
    assert "--password-stdin" in command and "--no-audio" in command
    assert command[command.index("--advertise") + 1] == "1920x1080@1"
    assert "--record" not in command and not plan["display"]
    assert all(name not in plan["environment"] for name in pi._CLEAR)
    assert all(plan["environment"][name] == value for name, value in pi._PROFILE.items())
    assert not (tmp_path / ".local").exists()  # constructing a plan is read-only


def test_local_config_and_overrides_preserve_percent_characters(tmp_path):
    config = tmp_path / "pi.ini"
    config.write_text("[connection]\nhost=mac.example.invalid\nusername=remote%user\n"
                      "[display]\noutput=HDMI-A-1\nmode=2560x1440@60Hz\n")
    args = pi.parser().parse_args(["--config", str(config), "--user", "override-user", "--audio", "--no-mailbox"])
    plan = pi.launch_plan(args, environment(tmp_path), "/opt/venv/bin/python")
    assert "override-user" in plan["command"]
    assert "--no-audio" not in plan["command"]
    assert "ISS_PI_MAILBOX" not in plan["environment"]
    assert plan["display"] == ["wlr-randr", "--output", "HDMI-A-1", "--mode", "2560x1440@60Hz", "--scale", "1"]
    assert pi._settings(config)["connection"]["username"] == "remote%user"


@pytest.mark.parametrize("extra", ["password=synthetic-test-value", "token=synthetic-test-value"])
def test_credentials_are_rejected_in_configuration(tmp_path, extra):
    config = tmp_path / "pi.ini"
    config.write_text("[connection]\nhost=mac.example.invalid\nusername=remote-user\n" + extra + "\n")
    args = pi.parser().parse_args(["--config", str(config)])
    with pytest.raises(ValueError, match="passwords must not be stored"):
        pi.launch_plan(args, environment(tmp_path), "/opt/venv/bin/python")


@pytest.mark.parametrize("argv", [[], ["--host", "mac.example.invalid"],
                                 ["--host", "mac.example.invalid", "--user", "remote-user", "--output", "HDMI-A-1"]])
def test_incomplete_connection_or_display_settings_are_rejected(tmp_path, argv):
    with pytest.raises(ValueError):
        pi.launch_plan(pi.parser().parse_args(argv), environment(tmp_path), "/opt/venv/bin/python")


def test_missing_explicit_configuration_is_an_error(tmp_path):
    args = pi.parser().parse_args(["--config", str(tmp_path / "missing")])
    with pytest.raises(ValueError, match="does not exist"):
        pi.launch_plan(args, environment(tmp_path), "/opt/venv/bin/python")


def test_desktop_executable_path_is_generated_locally(tmp_path):
    executable = tmp_path / 'environment space% "quote"' / "bin/python"
    path = pi.install_desktop(environment(tmp_path), executable)
    text = path.read_text()
    assert path == tmp_path / ".local/share/applications/isharescreen-pi.desktop"
    assert "-m isharescreen.pi" in text and "Terminal=true" in text
    assert "space%%" in text and '\\"quote\\"' in text
    assert "mac.example.invalid" not in text and "remote-user" not in text


def test_dry_run_does_not_connect_or_write_state(monkeypatch, tmp_path, capsys):
    for name in ["XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(pi.os, "execvpe", lambda *args: pytest.fail("dry-run executed the client"))
    assert pi.main(["--dry-run", "--host", "mac.example.invalid", "--user", "remote-user"]) == 0
    assert "--password-stdin" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
