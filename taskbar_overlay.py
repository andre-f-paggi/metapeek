#!/usr/bin/env python3
"""
KDE taskbar position overlay.
Hold Meta (Win) for 1 second to see numbered badges above the panel.
Requires: python-evdev, GTK4, gtk4-layer-shell (all available via gi)
User must be in the 'input' group: sudo usermod -aG input $USER
"""

import sys
import os
import re
import threading
import time
import selectors
from pathlib import Path


def _ensure_layer_shell_preload():
    """gtk4-layer-shell must be loaded before libwayland-client or KWin
    rejects the layer surface. Re-exec ourselves with LD_PRELOAD set."""
    if os.environ.get('_TASKBAR_OVERLAY_RELAUNCHED'):
        return
    for candidate in ('/usr/lib/libgtk4-layer-shell.so',
                       '/usr/lib64/libgtk4-layer-shell.so',
                       '/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so'):
        if Path(candidate).exists():
            env = os.environ.copy()
            existing = env.get('LD_PRELOAD', '')
            env['LD_PRELOAD'] = f'{candidate}:{existing}' if existing else candidate
            env['_TASKBAR_OVERLAY_RELAUNCHED'] = '1'
            os.execvpe(sys.executable, [sys.executable] + sys.argv, env)
    print("WARNING: libgtk4-layer-shell.so not found, layer-shell may fail to init.",
          file=sys.stderr)


_ensure_layer_shell_preload()

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gtk4LayerShell, GLib, Gdk, Pango, PangoCairo
import cairo

try:
    import evdev
    from evdev import InputDevice, ecodes
    _EVDEV_OK = True
except ImportError:
    _EVDEV_OK = False


# ── Config paths ──────────────────────────────────────────────────────────────

PLASMA_APPLETS = Path.home() / '.config' / 'plasma-org.kde.plasma.desktop-appletsrc'
PLASMA_SHELL   = Path.home() / '.config' / 'plasmashellrc'
OVERLAY_CONFIG = Path.home() / '.config' / 'taskbar-overlay.ini'

META_KEYS = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}


# ── Config file ───────────────────────────────────────────────────────────────

DEFAULTS = {
    'hold_duration':        '1.0',   # seconds before overlay appears
    'panel_thickness':      'auto',  # px, 'auto' reads from plasmashellrc
    'panel_bottom_margin':  '8',     # floating panel gap from screen bottom (px)
    'overlay_gap':          '6',     # gap between panel top and overlay bottom (px)
    'overlay_height':       '56',    # overlay window height (px)
    'badge_size':           '34',    # diameter of each number circle (px)
    'left_margin_px':       '0',     # skip N px from left before first badge
    'right_margin_px':      '0',     # skip N px from right after last badge
    'show_app_names':       'false', # show app names below numbers
    'font_size_number':     '15',    # badge number font size
    'font_size_name':       '9',     # app name font size
}


def load_config():
    cfg = dict(DEFAULTS)
    if OVERLAY_CONFIG.exists():
        for line in OVERLAY_CONFIG.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
    return cfg


def cfg_float(cfg, key):
    return float(cfg.get(key, DEFAULTS[key]))


def cfg_int(cfg, key):
    return int(cfg.get(key, DEFAULTS[key]))


def cfg_bool(cfg, key):
    return cfg.get(key, DEFAULTS[key]).lower() in ('true', '1', 'yes')


# ── KDE config parsers ────────────────────────────────────────────────────────

def read_panel_thickness():
    """Read panel thickness from plasmashellrc or waybar config."""
    if PLASMA_SHELL.exists():
        content = PLASMA_SHELL.read_text(errors='replace')
        m = re.search(r'^\s*thickness\s*=\s*(\d+)', content, re.MULTILINE)
        if m:
            return int(m.group(1))

    # Try waybar config
    for p in [
        Path.home() / '.config/waybar/config',
        Path.home() / '.config/waybar/config.jsonc',
        Path('/etc/xdg/waybar/config'),
    ]:
        if p.exists():
            content = p.read_text(errors='replace')
            m = re.search(r'"height"\s*:\s*(\d+)', content)
            if m:
                return int(m.group(1))

    return 32  # waybar default when no config found


def read_pinned_apps():
    """Return list of human-readable app names from the icon task manager."""
    if not PLASMA_APPLETS.exists():
        return []

    content = PLASMA_APPLETS.read_text(errors='replace')
    m = re.search(r'^launchers=(.+)$', content, re.MULTILINE)
    if not m:
        return []

    names = []
    for entry in m.group(1).split(','):
        entry = entry.strip()
        if not entry:
            continue
        desktop = _entry_to_desktop_file(entry)
        names.append(_desktop_name(desktop) if desktop else _fallback_name(entry))
    return names


def _entry_to_desktop_file(entry):
    if 'applications:' in entry:
        return entry.split('applications:')[-1].strip()
    if entry.startswith('file://'):
        return entry[7:]  # absolute path
    if 'preferred://' in entry:
        kind = entry.split('preferred://')[-1].strip()
        return _preferred_desktop(kind)
    return None


def _preferred_desktop(kind):
    """Resolve preferred://X to a .desktop filename."""
    mapping = {
        'filemanager': 'org.kde.dolphin.desktop',
        'browser':     'browser.desktop',
        'terminal':    'org.kde.konsole.desktop',
    }
    return mapping.get(kind)


def _desktop_name(desktop_path):
    """Read Name= from a .desktop file path or filename."""
    search_dirs = [
        Path.home() / '.local/share/applications',
        Path('/usr/share/applications'),
        Path('/usr/local/share/applications'),
        Path('/var/lib/flatpak/exports/share/applications'),
        Path('/var/lib/snapd/desktop/applications'),
    ]

    # If absolute path, check directly
    p = Path(desktop_path)
    candidates = [p] if p.is_absolute() else [d / desktop_path for d in search_dirs]

    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text(errors='replace')
            nm = re.search(r'^Name=(.+)$', content, re.MULTILINE)
            if nm:
                return nm.group(1).strip()

    # Fallback: strip extension and path
    return _fallback_name(desktop_path)


def _fallback_name(entry):
    name = Path(entry).stem
    name = name.split('.')[-1]           # org.kde.konsole → konsole
    name = re.sub(r'-', ' ', name)
    return name.capitalize()


# ── Overlay window ────────────────────────────────────────────────────────────

class OverlayWindow(Gtk.ApplicationWindow):
    def __init__(self, app, apps, cfg):
        super().__init__(application=app)

        # init_for_window MUST come before set_decorated and any GTK surface setup,
        # otherwise GTK4/Wayland realizes the window as a plain xdg_toplevel first
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT,   True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT,  True)
        Gtk4LayerShell.set_exclusive_zone(self, 0)

        # KWin's wlr-layer-shell implementation already reserves space for the
        # real panel's exclusive zone, so anchoring BOTTOM lands right above
        # it automatically. Adding panel thickness here would double-count it.
        margin_b = cfg_int(cfg, 'panel_bottom_margin') + cfg_int(cfg, 'overlay_gap')
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.BOTTOM, margin_b)

        self.apps = apps
        self.cfg  = cfg
        self._layer_ok = None  # resolved on first realize

        self.set_decorated(False)
        self.set_default_size(100, cfg_int(cfg, 'overlay_height'))
        self.connect('realize', self._on_realize)

        # Transparent background via CSS
        css = Gtk.CssProvider()
        css.load_from_data(b'window { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Drawing area — must set explicit height or layer-shell collapses it
        self.area = Gtk.DrawingArea()
        self.area.set_content_height(cfg_int(cfg, 'overlay_height'))
        self.area.set_draw_func(self._draw, None)
        self.set_child(self.area)

    def _on_realize(self, _widget):
        ok = Gtk4LayerShell.is_layer_window(self)
        self._layer_ok = ok
        if ok:
            print("layer-shell: active, window anchored to screen bottom")
        else:
            print("layer-shell: FAILED — KWin rejected protocol. Falling back to X11 positioning.")
            self._apply_x11_fallback()

    def _apply_x11_fallback(self):
        """Position window via X11 (XWayland) when wlr-layer-shell is unavailable."""
        try:
            gi.require_version('GdkX11', '4.0')
            from gi.repository import GdkX11
        except Exception as e:
            print(f"X11 fallback unavailable: {e}", file=sys.stderr)
            return

        surface = self.get_surface()
        if not isinstance(surface, GdkX11.X11Surface):
            print("X11 fallback: GDK surface is not X11 — relaunch with GDK_BACKEND=x11", file=sys.stderr)
            print("  export GDK_BACKEND=x11 && python3 taskbar_overlay.py", file=sys.stderr)
            return

        cfg = self.cfg
        try:
            import ctypes
            xlib = ctypes.CDLL('libX11.so.6')
            xdpy = ctypes.c_void_p(int(surface.get_xdisplay()))
            xid  = ctypes.c_ulong(surface.get_xid())

            # Get screen dimensions from GDK
            monitor  = self.get_display().get_monitors().get_item(0)
            geo      = monitor.get_geometry()
            sw, sh   = geo.width, geo.height

            panel_h  = (read_panel_thickness() if cfg.get('panel_thickness') == 'auto'
                        else cfg_int(cfg, 'panel_thickness'))
            ov_h     = cfg_int(cfg, 'overlay_height')
            margin_b = panel_h + cfg_int(cfg, 'panel_bottom_margin') + cfg_int(cfg, 'overlay_gap')
            win_y    = sh - margin_b - ov_h

            # Override-redirect: WM stops managing this window
            class _XSWAttrs(ctypes.Structure):
                _fields_ = [('_pad', ctypes.c_ulong * 13),
                             ('override_redirect', ctypes.c_int),
                             ('_pad2', ctypes.c_ulong * 2)]
            attrs = _XSWAttrs()
            attrs.override_redirect = 1
            CWOverrideRedirect = 1 << 9
            xlib.XChangeWindowAttributes(xdpy, xid, CWOverrideRedirect, ctypes.byref(attrs))
            xlib.XMoveResizeWindow(xdpy, xid, 0, win_y, sw, ov_h)
            xlib.XRaiseWindow(xdpy, xid)
            xlib.XFlush(xdpy)
            print(f"X11 fallback: positioned at y={win_y}, {sw}x{ov_h}")
        except Exception as e:
            print(f"X11 fallback error: {e}", file=sys.stderr)
            print("Relaunch with: GDK_BACKEND=x11 python3 taskbar_overlay.py", file=sys.stderr)

    def _draw(self, area, cr, width, height, _data):
        n = len(self.apps)
        if n == 0:
            return

        cfg          = self.cfg
        badge        = cfg_int(cfg, 'badge_size')
        left_skip    = cfg_int(cfg, 'left_margin_px')
        right_skip   = cfg_int(cfg, 'right_margin_px')
        show_names   = cfg_bool(cfg, 'show_app_names')
        font_num     = cfg_int(cfg, 'font_size_number')
        font_nm      = cfg_int(cfg, 'font_size_name')

        usable_w  = width - left_skip - right_skip
        slot_w    = usable_w / n
        cy_badge  = height * 0.42 if show_names else height / 2

        for i, name in enumerate(self.apps):
            cx = left_skip + (i + 0.5) * slot_w

            # Dark semi-transparent circle
            cr.new_path()  # drop stray current-point from previous badge's text draw,
                            # otherwise cairo's arc() draws a connecting line to it
            cr.arc(cx, cy_badge, badge / 2, 0, 2 * 3.14159)
            cr.set_source_rgba(0.05, 0.05, 0.05, 0.82)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.18)
            cr.set_line_width(1)
            cr.stroke()

            # Number
            _draw_text(cr, str(i + 1), cx, cy_badge,
                       font_num, bold=True, rgba=(1, 1, 1, 1))

            # Optional app name
            if show_names:
                _draw_text(cr, name, cx, cy_badge + badge / 2 + 2 + font_nm * 0.6,
                           font_nm, bold=False, rgba=(0.9, 0.9, 0.9, 0.9))


def _draw_text(cr, text, cx, cy, size_pt, bold, rgba):
    layout = PangoCairo.create_layout(cr)
    desc   = Pango.FontDescription()
    desc.set_family('Sans')
    desc.set_size(int(size_pt * Pango.SCALE))
    if bold:
        desc.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(desc)
    layout.set_text(text, -1)

    lw, lh = layout.get_pixel_size()
    cr.move_to(cx - lw / 2, cy - lh / 2)
    cr.set_source_rgba(*rgba)
    PangoCairo.show_layout(cr, layout)


# ── Key monitor (background thread) ──────────────────────────────────────────

def find_keyboards():
    keyboards = []
    for path in evdev.list_devices():
        try:
            dev  = InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps and ecodes.KEY_LEFTMETA in caps[ecodes.EV_KEY]:
                keyboards.append(dev)
        except Exception:
            pass
    return keyboards


def monitor_keys(hold_duration, on_show, on_hide):
    keyboards = find_keyboards()
    if not keyboards:
        print("ERROR: No keyboard devices accessible.")
        print("Add yourself to input group: sudo usermod -aG input $USER  (re-login after)")
        return

    print(f"Monitoring {len(keyboards)} keyboard device(s). Hold Meta for {hold_duration}s.")

    meta_pressed   = {}   # device.path → monotonic timestamp of keydown
    overlay_active = False

    def check_hold(dev_path, t_down):
        nonlocal overlay_active
        time.sleep(hold_duration)
        if meta_pressed.get(dev_path) == t_down and not overlay_active:
            overlay_active = True
            GLib.idle_add(on_show)

    sel = selectors.DefaultSelector()
    for kbd in keyboards:
        sel.register(kbd, selectors.EVENT_READ)

    while True:
        try:
            ready = sel.select(timeout=0.1)
            for key, _ in ready:
                kbd = key.fileobj
                try:
                    for event in kbd.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        if event.code not in META_KEYS:
                            continue
                        if event.value == 1:   # key down
                            t = time.monotonic()
                            meta_pressed[kbd.path] = t
                            threading.Thread(
                                target=check_hold, args=(kbd.path, t), daemon=True
                            ).start()
                        elif event.value == 0: # key up
                            meta_pressed.pop(kbd.path, None)
                            if overlay_active:
                                overlay_active = False
                                GLib.idle_add(on_hide)
                except OSError:
                    pass
        except Exception as e:
            print(f"Key monitor error: {e}", file=sys.stderr)
            time.sleep(0.5)


# ── Application ───────────────────────────────────────────────────────────────

class OverlayApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='io.github.linux-taskbar-helper')
        self.win = None

    def do_activate(self):
        if not _EVDEV_OK:
            print("ERROR: python-evdev not installed.")
            print("Install: pip install evdev")
            print("Then add yourself to input group: sudo usermod -aG input $USER  (re-login after)")
            self.quit()
            return

        cfg  = load_config()
        apps = read_pinned_apps()

        if not apps:
            print("WARNING: No pinned apps found in KDE config. Using placeholders.")
            apps = [f'App{i}' for i in range(1, 10)]
        else:
            print(f"Apps ({len(apps)}): {', '.join(apps)}")

        self.win = OverlayWindow(self, apps, cfg)

        def show():
            self.win.area.queue_draw()
            self.win.present()
            return False

        def hide():
            self.win.set_visible(False)
            return False

        t = threading.Thread(
            target=monitor_keys,
            args=(cfg_float(cfg, 'hold_duration'), show, hide),
            daemon=True
        )
        t.start()

        print("Running. Hold Meta (Win) key to show overlay, release to hide.")


def main():
    app = OverlayApp()
    sys.exit(app.run(sys.argv))


if __name__ == '__main__':
    main()
