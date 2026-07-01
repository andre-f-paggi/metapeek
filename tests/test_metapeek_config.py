"""Unit tests for metapeek_config — pure logic, no GTK/evdev/display needed."""

import pytest

import metapeek_config as tc

# ── Overlay config file ───────────────────────────────────────────────────────

def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = tc.load_config(tmp_path / "does-not-exist.ini")
    assert cfg == tc.DEFAULTS
    assert cfg is not tc.DEFAULTS  # must be a copy, never the shared dict


def test_load_config_overrides_and_keeps_defaults(tmp_path):
    ini = tmp_path / "overlay.ini"
    ini.write_text(
        "# a comment\n"
        "\n"
        "badge_size = 40\n"
        "overlay_gap=4\n"
        "show_app_names = true\n"
    )
    cfg = tc.load_config(ini)
    assert cfg["badge_size"] == "40"          # overridden, whitespace trimmed
    assert cfg["overlay_gap"] == "4"
    assert cfg["show_app_names"] == "true"
    assert cfg["hold_duration"] == tc.DEFAULTS["hold_duration"]  # untouched default


def test_load_config_ignores_comments_and_blank_and_malformed(tmp_path):
    ini = tmp_path / "overlay.ini"
    ini.write_text("# only comments\n\nno_equals_sign_here\n")
    cfg = tc.load_config(ini)
    assert cfg == tc.DEFAULTS


def test_load_config_value_may_contain_equals(tmp_path):
    ini = tmp_path / "overlay.ini"
    ini.write_text("some_key=a=b=c\n")
    cfg = tc.load_config(ini)
    assert cfg["some_key"] == "a=b=c"


# ── Typed accessors ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("YES", True),
    ("false", False), ("0", False), ("no", False), ("", False), ("nope", False),
])
def test_cfg_bool(value, expected):
    assert tc.cfg_bool({"k": value}, "k") is expected


def test_cfg_int_and_float():
    assert tc.cfg_int({"k": "42"}, "k") == 42
    assert tc.cfg_float({"k": "1.5"}, "k") == 1.5


def test_cfg_accessors_fall_back_to_defaults_for_missing_key():
    assert tc.cfg_int({}, "badge_size") == int(tc.DEFAULTS["badge_size"])
    assert tc.cfg_float({}, "hold_duration") == float(tc.DEFAULTS["hold_duration"])
    assert tc.cfg_bool({}, "show_app_names") is False


# ── Panel thickness ───────────────────────────────────────────────────────────

def test_read_panel_thickness_from_plasmashellrc(tmp_path):
    shell = tmp_path / "plasmashellrc"
    shell.write_text("[PlasmaViews][Panel 27][Defaults]\nthickness=44\n")
    assert tc.read_panel_thickness(plasma_shell=shell, waybar_paths=()) == 44


def test_read_panel_thickness_falls_back_to_waybar(tmp_path):
    waybar = tmp_path / "waybar-config"
    waybar.write_text('{ "height": 28, "layer": "top" }')
    missing_shell = tmp_path / "no-plasma"
    assert tc.read_panel_thickness(missing_shell, waybar_paths=(waybar,)) == 28


def test_read_panel_thickness_default_when_nothing_found(tmp_path):
    assert tc.read_panel_thickness(tmp_path / "nope", waybar_paths=()) == 32


# ── Launcher entry parsing ────────────────────────────────────────────────────

@pytest.mark.parametrize("entry,expected", [
    ("applications:org.kde.konsole.desktop", "org.kde.konsole.desktop"),
    ("file:///opt/app/foo.desktop", "/opt/app/foo.desktop"),
    ("preferred://filemanager", "org.kde.dolphin.desktop"),
    ("preferred://unknownkind", None),
    ("garbage-value", None),
])
def test_entry_to_desktop_file(entry, expected):
    assert tc.entry_to_desktop_file(entry) == expected


@pytest.mark.parametrize("entry,expected", [
    ("org.kde.konsole.desktop", "Konsole"),
    ("visual-studio-code.desktop", "Visual studio code"),
    ("/abs/path/sublime_text.desktop", "Sublime_text"),
])
def test_fallback_name(entry, expected):
    assert tc.fallback_name(entry) == expected


def test_desktop_name_reads_name_field(tmp_path):
    d = tmp_path / "org.example.thing.desktop"
    d.write_text("[Desktop Entry]\nName=Example Thing\nExec=thing\n")
    assert tc.desktop_name("org.example.thing.desktop", search_dirs=(tmp_path,)) == "Example Thing"


def test_desktop_name_falls_back_when_no_file(tmp_path):
    assert tc.desktop_name("org.kde.konsole.desktop", search_dirs=(tmp_path,)) == "Konsole"


# ── read_pinned_apps end to end ───────────────────────────────────────────────

def test_read_pinned_apps_missing_file(tmp_path):
    assert tc.read_pinned_apps(applets=tmp_path / "nope") == []


def test_read_pinned_apps_resolves_mixed_entries(tmp_path):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    (apps_dir / "slack.desktop").write_text("[Desktop Entry]\nName=Slack\n")

    applets = tmp_path / "appletsrc"
    applets.write_text(
        "[Containments][27][Applets][32][General]\n"
        "launchers=applications:slack.desktop,"
        "file://" + str(apps_dir / "slack.desktop") + ","
        "applications:org.kde.konsole.desktop\n"
    )
    names = tc.read_pinned_apps(applets=applets, search_dirs=(apps_dir,))
    assert names == ["Slack", "Slack", "Konsole"]


def test_version_is_semver():
    parts = tc.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
