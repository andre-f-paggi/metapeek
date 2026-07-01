"""Pure configuration and KDE-config parsing for the taskbar overlay.

This module deliberately imports only the standard library so it can be
unit-tested and reused without a display server, GTK, or evdev present.
The GTK/evdev overlay lives in ``metapeek.py`` and imports from here.
"""

import re
from pathlib import Path

__version__ = "0.1.0"


# ── Config paths ──────────────────────────────────────────────────────────────

PLASMA_APPLETS = Path.home() / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
PLASMA_SHELL   = Path.home() / ".config" / "plasmashellrc"
OVERLAY_CONFIG = Path.home() / ".config" / "metapeek.ini"

DEFAULT_APPLICATION_DIRS = (
    Path.home() / ".local/share/applications",
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
)

DEFAULT_WAYBAR_PATHS = (
    Path.home() / ".config/waybar/config",
    Path.home() / ".config/waybar/config.jsonc",
    Path("/etc/xdg/waybar/config"),
)


# ── Overlay config file ───────────────────────────────────────────────────────

DEFAULTS = {
    "hold_duration":        "1.0",   # seconds before overlay appears
    "panel_edge":           "auto",  # top|bottom|left|right, 'auto' reads from KDE config
    "panel_thickness":      "auto",  # px, 'auto' reads from plasmashellrc
    "panel_bottom_margin":  "8",     # floating panel gap from its screen edge (px)
    "overlay_gap":          "6",     # gap between the panel and the overlay (px)
    "overlay_height":       "56",    # strip breadth in px (height if horizontal, width if vertical)
    "badge_size":           "34",    # diameter of each number circle (px)
    "left_margin_px":       "0",     # horizontal panels: skip N px from left before first badge
    "right_margin_px":      "0",     # horizontal panels: skip N px from right after last badge
    "top_margin_px":        "0",     # vertical panels: skip N px from top before first badge
    "bottom_margin_px":     "0",     # vertical panels: skip N px from bottom after last badge
    "show_app_names":       "false", # show app names next to numbers
    "font_size_number":     "15",    # badge number font size
    "font_size_name":       "9",     # app name font size
}

# Plasma::Types::Location — the panel containment's `location=` value in the
# appletsrc encodes which screen edge the panel is docked to.
EDGE_BY_LOCATION = {3: "top", 4: "bottom", 5: "left", 6: "right"}
VALID_EDGES = ("top", "bottom", "left", "right")


def load_config(path=OVERLAY_CONFIG):
    """Parse the flat ``key=value`` overlay config, layered over DEFAULTS."""
    cfg = dict(DEFAULTS)
    path = Path(path)
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def cfg_float(cfg, key):
    return float(cfg.get(key, DEFAULTS.get(key)))


def cfg_int(cfg, key):
    return int(cfg.get(key, DEFAULTS.get(key)))


def cfg_bool(cfg, key):
    return cfg.get(key, DEFAULTS.get(key, "")).lower() in ("true", "1", "yes")


# ── KDE / Waybar config parsers ───────────────────────────────────────────────

def read_panel_thickness(plasma_shell=PLASMA_SHELL, waybar_paths=DEFAULT_WAYBAR_PATHS):
    """Return the panel thickness in px from plasmashellrc, else waybar, else 32."""
    plasma_shell = Path(plasma_shell)
    if plasma_shell.exists():
        content = plasma_shell.read_text(errors="replace")
        m = re.search(r"^\s*thickness\s*=\s*(\d+)", content, re.MULTILINE)
        if m:
            return int(m.group(1))

    for p in waybar_paths:
        p = Path(p)
        if p.exists():
            content = p.read_text(errors="replace")
            m = re.search(r'"height"\s*:\s*(\d+)', content)
            if m:
                return int(m.group(1))

    return 32  # waybar default when no config found


def read_panel_edge(applets=PLASMA_APPLETS):
    """Return which screen edge the panel is docked to: top/bottom/left/right.

    Reads the panel containment's ``location=`` from the appletsrc. Desktop
    containments use non-edge locations (0-2), so the first edge value found
    belongs to a panel. Defaults to 'bottom' when nothing is detected.
    """
    applets = Path(applets)
    if not applets.exists():
        return "bottom"

    content = applets.read_text(errors="replace")
    for m in re.finditer(r"^location=(\d+)", content, re.MULTILINE):
        edge = EDGE_BY_LOCATION.get(int(m.group(1)))
        if edge:
            return edge
    return "bottom"


def resolve_panel_edge(cfg, applets=PLASMA_APPLETS):
    """Resolve the configured ``panel_edge`` (honoring 'auto') to a valid edge."""
    edge = cfg.get("panel_edge", "auto").strip().lower()
    if edge in VALID_EDGES:
        return edge
    return read_panel_edge(applets)


def read_pinned_apps(applets=PLASMA_APPLETS, search_dirs=DEFAULT_APPLICATION_DIRS):
    """Return human-readable names of the pinned launchers in the task manager."""
    applets = Path(applets)
    if not applets.exists():
        return []

    content = applets.read_text(errors="replace")
    m = re.search(r"^launchers=(.+)$", content, re.MULTILINE)
    if not m:
        return []

    names = []
    for entry in m.group(1).split(","):
        entry = entry.strip()
        if not entry:
            continue
        desktop = entry_to_desktop_file(entry)
        names.append(
            desktop_name(desktop, search_dirs) if desktop else fallback_name(entry)
        )
    return names


def entry_to_desktop_file(entry):
    """Map a launcher URL entry to a .desktop filename or absolute path."""
    if "applications:" in entry:
        return entry.split("applications:")[-1].strip()
    if entry.startswith("file://"):
        return entry[7:]  # absolute path
    if "preferred://" in entry:
        kind = entry.split("preferred://")[-1].strip()
        return preferred_desktop(kind)
    return None


def preferred_desktop(kind):
    """Resolve ``preferred://X`` to a .desktop filename."""
    mapping = {
        "filemanager": "org.kde.dolphin.desktop",
        "browser":     "browser.desktop",
        "terminal":    "org.kde.konsole.desktop",
    }
    return mapping.get(kind)


def desktop_name(desktop_path, search_dirs=DEFAULT_APPLICATION_DIRS):
    """Read ``Name=`` from a .desktop file (by path or filename)."""
    p = Path(desktop_path)
    candidates = [p] if p.is_absolute() else [Path(d) / desktop_path for d in search_dirs]

    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text(errors="replace")
            nm = re.search(r"^Name=(.+)$", content, re.MULTILINE)
            if nm:
                return nm.group(1).strip()

    return fallback_name(desktop_path)


def fallback_name(entry):
    """Best-effort readable name from a .desktop id when no Name= is found."""
    name = Path(entry).stem
    name = name.split(".")[-1]           # org.kde.konsole → konsole
    name = re.sub(r"-", " ", name)
    return name.capitalize()
