# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-30

### Added
- Meta-hold overlay drawing numbered badges above pinned KDE Task Manager icons,
  anchored to the screen bottom via `gtk4-layer-shell`.
- Automatic `LD_PRELOAD` self-relaunch so `gtk4-layer-shell` loads before
  `libwayland-client` (otherwise KWin rejects the layer surface).
- X11/XWayland fallback positioning when `wlr-layer-shell` is unavailable.
- Configurable behavior via `~/.config/taskbar-overlay.ini` (badge size, margins,
  hold duration, optional app names, fonts).
- Reads panel thickness from `plasmashellrc` (or Waybar config) and pinned launcher
  names from `plasma-org.kde.plasma.desktop-appletsrc`.
- `--version` / `-V` flag.
- `setup.sh` installer for dependencies and `input` group membership.
- Unit test suite for the configuration/parsing core and CI running lint + tests.

### Fixed
- Overlay no longer double-counts the panel thickness in its bottom margin (KWin's
  layer-shell already reserves that space), so badges sit correctly on top of the bar.
- Removed a stray connecting line drawn between badges caused by a leftover Cairo
  current-point from the number-label rendering.

[Unreleased]: https://github.com/andre-f-paggi/linux-taskbar-helper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/andre-f-paggi/linux-taskbar-helper/releases/tag/v0.1.0
