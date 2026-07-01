# linux-taskbar-helper

**Hold the Meta (Super/Win) key to flash numbered badges over your pinned taskbar
icons — so you can see which `Meta+1`, `Meta+2`, … shortcut launches what.**

KDE Plasma lets you focus or launch pinned Task Manager entries with `Meta+<number>`,
but nothing tells you *which* number maps to which icon. This tool draws a translucent
overlay of numbered circles, aligned directly above your pinned icons, for as long as you
hold Meta. Release the key and it disappears.

> Wayland-first: the overlay anchors itself to the bottom of the screen using the
> `wlr-layer-shell` protocol (via `gtk4-layer-shell`), with an XWayland/X11 fallback.

---

## Requirements

- **KDE Plasma 6** on **Wayland** (X11 works via the fallback path)
- **Python 3.9+**
- System libraries, all available on Arch as packages:
  - `python-evdev` — global key monitoring
  - `python-gobject`, `gtk4`, `gtk4-layer-shell` — the overlay window
- Your user must be in the **`input`** group to read keyboard events

## Install

```bash
git clone https://github.com/andre-f-paggi/linux-taskbar-helper.git
cd linux-taskbar-helper
./setup.sh          # installs deps + adds you to the 'input' group
```

Then **log out and back in** (or reboot) so the `input` group membership takes effect.

<details>
<summary>Manual install (non-Arch, or if you prefer to do it by hand)</summary>

```bash
# Debian/Ubuntu example — package names vary by distro
sudo apt install python3-evdev python3-gi gir1.2-gtk-4.0 gtk4-layer-shell
sudo usermod -aG input "$USER"    # then log out and back in
```
</details>

## Run

```bash
python3 taskbar_overlay.py
```

Hold **Meta** for ~1 second: numbered badges appear above your pinned icons.
Release to hide. Check it works with:

```bash
python3 taskbar_overlay.py --version
```

### Autostart

Add it to **System Settings → Autostart → Add Application**, with the command:

```
python3 /full/path/to/linux-taskbar-helper/taskbar_overlay.py
```

## Configure

All tuning is optional and lives in `~/.config/taskbar-overlay.ini`
(a flat `key=value` file; lines starting with `#` are ignored). Any key you omit
falls back to its default:

| Key | Default | Meaning |
|-----|---------|---------|
| `hold_duration` | `1.0` | Seconds to hold Meta before the overlay appears |
| `panel_thickness` | `auto` | Panel height in px; `auto` reads it from `plasmashellrc` |
| `panel_bottom_margin` | `8` | Gap of a floating panel from the screen bottom (px) |
| `overlay_gap` | `6` | Gap between the panel top and the overlay bottom (px) |
| `overlay_height` | `56` | Overlay window height (px) |
| `badge_size` | `34` | Diameter of each numbered circle (px) |
| `left_margin_px` | `0` | Skip N px from the left before the first badge |
| `right_margin_px` | `0` | Skip N px from the right after the last badge |
| `show_app_names` | `false` | Draw the app name under each number |
| `font_size_number` | `15` | Badge number font size |
| `font_size_name` | `9` | App-name font size |

**Aligning the badges:** the overlay spreads badges evenly across the width between
`left_margin_px` and `screen_width − right_margin_px`. If your pinned icons don't span
the whole screen (a centered or floating panel), set those two margins so the badge
strip lines up with your icons. Example for a 1920px screen with icons starting ~56px
from the left:

```ini
left_margin_px=56
right_margin_px=1396
badge_size=40
overlay_gap=4
```

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `No keyboard devices accessible` | You're not in the `input` group yet, or haven't re-logged in after `setup.sh`. Run `groups` to check. |
| `layer-shell: FAILED` / badges misplaced | The script auto-relaunches itself with `LD_PRELOAD` pointed at `libgtk4-layer-shell.so`. If the library lives somewhere unusual, the overlay falls back to X11 positioning. |
| Badges appear but don't line up with icons | Tune `left_margin_px` / `right_margin_px` — see *Aligning the badges* above. |
| Nothing pinned shows up | The app reads pinned launchers from `plasma-org.kde.plasma.desktop-appletsrc`; if it can't find any it shows `App1…App9` placeholders. |

## How it works

- **`taskbar_config.py`** — pure, dependency-free parsing of the KDE/Waybar config files
  and the overlay `.ini`. This is the unit-tested core.
- **`taskbar_overlay.py`** — the GTK4 layer-shell window plus the evdev key-monitor thread.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the dev setup, tests, and the CI contract.

## License

[MIT](LICENSE) © André Franciscato Paggi
