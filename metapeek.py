#!/usr/bin/env python3
"""
MetaPeek — KDE taskbar shortcut overlay.
Hold Meta (Win) for 1 second to see numbered badges above the panel,
revealing which Meta+N shortcut launches which pinned app.
Requires: python-evdev, GTK4, gtk4-layer-shell (all available via gi)
User must be in the 'input' group: sudo usermod -aG input $USER
"""

import os
import selectors
import sys
import threading
import time
from pathlib import Path


def _ensure_layer_shell_preload():
    """gtk4-layer-shell must be loaded before libwayland-client or KWin
    rejects the layer surface. Re-exec ourselves with LD_PRELOAD set."""
    if os.environ.get('_METAPEEK_RELAUNCHED'):
        return
    for candidate in ('/usr/lib/libgtk4-layer-shell.so',
                       '/usr/lib64/libgtk4-layer-shell.so',
                       '/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so'):
        if Path(candidate).exists():
            env = os.environ.copy()
            existing = env.get('LD_PRELOAD', '')
            env['LD_PRELOAD'] = f'{candidate}:{existing}' if existing else candidate
            env['_METAPEEK_RELAUNCHED'] = '1'
            os.execvpe(sys.executable, [sys.executable] + sys.argv, env)
    print("WARNING: libgtk4-layer-shell.so not found, layer-shell may fail to init.",
          file=sys.stderr)


_ensure_layer_shell_preload()

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GLib, Gtk, Gtk4LayerShell, Pango, PangoCairo

from metapeek_config import (
    __version__,
    cfg_bool,
    cfg_float,
    cfg_int,
    load_config,
    read_panel_thickness,
    read_pinned_apps,
    resolve_panel_edge,
)

try:
    import evdev
    from evdev import InputDevice, ecodes
    _EVDEV_OK = True
    META_KEYS = {ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA}
except ImportError:
    _EVDEV_OK = False
    META_KEYS = set()


# ── Overlay window ────────────────────────────────────────────────────────────

class OverlayWindow(Gtk.ApplicationWindow):
    def __init__(self, app, apps, cfg):
        super().__init__(application=app)

        self.apps = apps
        self.cfg  = cfg
        self._layer_ok = None  # resolved on first realize
        self.edge = resolve_panel_edge(cfg)
        self.horizontal = self.edge in ('top', 'bottom')

        # init_for_window MUST come before set_decorated and any GTK surface setup,
        # otherwise GTK4/Wayland realizes the window as a plain xdg_toplevel first
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

        # Anchor to the panel's edge; stretch along the perpendicular axis so the
        # strip spans the panel's full length.
        E = Gtk4LayerShell.Edge
        anchor_edge = {
            'bottom': E.BOTTOM, 'top': E.TOP, 'left': E.LEFT, 'right': E.RIGHT,
        }[self.edge]
        span_edges = (E.LEFT, E.RIGHT) if self.horizontal else (E.TOP, E.BOTTOM)
        for e in span_edges:
            Gtk4LayerShell.set_anchor(self, e, True)
        Gtk4LayerShell.set_anchor(self, anchor_edge, True)
        Gtk4LayerShell.set_exclusive_zone(self, 0)

        # KWin's wlr-layer-shell implementation already reserves space for the
        # real panel's exclusive zone, so anchoring to its edge lands right next
        # to it. Adding the panel thickness here would double-count it.
        panel_gap = cfg_int(cfg, 'panel_bottom_margin') + cfg_int(cfg, 'overlay_gap')
        Gtk4LayerShell.set_margin(self, anchor_edge, panel_gap)

        self.set_decorated(False)

        # Transparent background via CSS
        css = Gtk.CssProvider()
        css.load_from_data(b'window { background: transparent; }')
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Drawing area — fix the strip breadth on the axis perpendicular to the
        # panel, or layer-shell collapses it. Horizontal panel → fixed height;
        # vertical panel → fixed width.
        breadth = cfg_int(cfg, 'overlay_height')
        self.area = Gtk.DrawingArea()
        if self.horizontal:
            self.area.set_content_height(breadth)
            self.set_default_size(100, breadth)
        else:
            self.area.set_content_width(breadth)
            self.set_default_size(breadth, 100)
        self.area.set_draw_func(self._draw, None)
        self.set_child(self.area)

    def _on_realize(self, _widget):
        ok = Gtk4LayerShell.is_layer_window(self)
        self._layer_ok = ok
        if ok:
            print(f"layer-shell: active, window anchored to {self.edge} edge")
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
            print("X11 fallback: GDK surface is not X11 — relaunch with GDK_BACKEND=x11",
                  file=sys.stderr)
            print("  export GDK_BACKEND=x11 && python3 metapeek.py", file=sys.stderr)
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
            breadth  = cfg_int(cfg, 'overlay_height')
            gap      = panel_h + cfg_int(cfg, 'panel_bottom_margin') + cfg_int(cfg, 'overlay_gap')

            # Window rect on the panel's edge; the strip spans the full screen
            # length along the perpendicular axis.
            if self.edge == 'bottom':
                x, y, w, h = 0, sh - gap - breadth, sw, breadth
            elif self.edge == 'top':
                x, y, w, h = 0, gap, sw, breadth
            elif self.edge == 'left':
                x, y, w, h = gap, 0, breadth, sh
            else:  # right
                x, y, w, h = sw - gap - breadth, 0, breadth, sh

            # Override-redirect: WM stops managing this window
            class _XSWAttrs(ctypes.Structure):
                _fields_ = [('_pad', ctypes.c_ulong * 13),
                             ('override_redirect', ctypes.c_int),
                             ('_pad2', ctypes.c_ulong * 2)]
            attrs = _XSWAttrs()
            attrs.override_redirect = 1
            CWOverrideRedirect = 1 << 9
            xlib.XChangeWindowAttributes(xdpy, xid, CWOverrideRedirect, ctypes.byref(attrs))
            xlib.XMoveResizeWindow(xdpy, xid, x, y, w, h)
            xlib.XRaiseWindow(xdpy, xid)
            xlib.XFlush(xdpy)
            print(f"X11 fallback: {self.edge} edge at ({x},{y}) {w}x{h}")
        except Exception as e:
            print(f"X11 fallback error: {e}", file=sys.stderr)
            print("Relaunch with: GDK_BACKEND=x11 python3 metapeek.py", file=sys.stderr)

    def _draw(self, area, cr, width, height, _data):
        n = len(self.apps)
        if n == 0:
            return

        cfg          = self.cfg
        badge        = cfg_int(cfg, 'badge_size')
        show_names   = cfg_bool(cfg, 'show_app_names')
        font_num     = cfg_int(cfg, 'font_size_number')
        font_nm      = cfg_int(cfg, 'font_size_name')

        # 'along' is the axis the badges are distributed on (parallel to the
        # panel); 'cross' is the strip breadth (perpendicular to the panel).
        if self.horizontal:
            along_len  = width
            cross_len  = height
            start_skip = cfg_int(cfg, 'left_margin_px')
            end_skip   = cfg_int(cfg, 'right_margin_px')
        else:
            along_len  = height
            cross_len  = width
            start_skip = cfg_int(cfg, 'top_margin_px')
            end_skip   = cfg_int(cfg, 'bottom_margin_px')

        slot = (along_len - start_skip - end_skip) / n
        # Shift toward the panel to leave room for names (horizontal strips only).
        cross_c = cross_len * 0.42 if (show_names and self.horizontal) else cross_len / 2

        for i, name in enumerate(self.apps):
            along = start_skip + (i + 0.5) * slot
            cx, cy = (along, cross_c) if self.horizontal else (cross_c, along)

            # Dark semi-transparent circle
            cr.new_path()  # drop stray current-point from previous badge's text draw,
                            # otherwise cairo's arc() draws a connecting line to it
            cr.arc(cx, cy, badge / 2, 0, 2 * 3.14159)
            cr.set_source_rgba(0.05, 0.05, 0.05, 0.82)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.18)
            cr.set_line_width(1)
            cr.stroke()

            # Number
            _draw_text(cr, str(i + 1), cx, cy,
                       font_num, bold=True, rgba=(1, 1, 1, 1))

            # Optional app name
            if show_names:
                _draw_text(cr, name, cx, cy + badge / 2 + 2 + font_nm * 0.6,
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
        super().__init__(application_id='io.github.metapeek')
        self.win = None

    def do_activate(self):
        if not _EVDEV_OK:
            print("ERROR: python-evdev not installed.")
            print("Install: pip install evdev")
            print("Then add yourself to input group: "
                  "sudo usermod -aG input $USER  (re-login after)")
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
    if len(sys.argv) > 1 and sys.argv[1] in ('--version', '-V'):
        print(f"metapeek {__version__}")
        sys.exit(0)
    app = OverlayApp()
    sys.exit(app.run(sys.argv))


if __name__ == '__main__':
    main()
