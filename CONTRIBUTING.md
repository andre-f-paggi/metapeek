# Contributing

Thanks for your interest in improving metapeek! This is a small project,
so the process is light.

## Project layout

| File | Responsibility |
|------|----------------|
| `metapeek_config.py` | Pure, stdlib-only parsing of KDE/Waybar config + the overlay `.ini`. **Unit-tested.** |
| `metapeek.py` | The GTK4 layer-shell overlay window and the evdev key-monitor thread. |
| `tests/` | `pytest` suite covering `metapeek_config.py`. |
| `setup.sh` | One-shot dependency + `input` group installer (Arch). |

Keep display-independent logic in `metapeek_config.py` so it stays testable without a
GTK runtime or a Wayland session. Anything that touches GTK, evdev, or the live desktop
belongs in `metapeek.py`.

## Dev setup

The runtime needs system GTK libraries, but the **tests and linter only need the
standard library plus `pytest`/`ruff`**, so a plain virtualenv is enough:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"      # installs pytest + ruff
```

## Before you open a PR

CI runs exactly these two commands — run them locally first:

```bash
ruff check .          # lint + import sort
pytest -q             # unit tests
```

Both must pass. If you change behavior in `metapeek_config.py`, add or update a test
in `tests/test_metapeek_config.py`.

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`).
- **Changelog:** add a bullet under the `## [Unreleased]` section of
  [`CHANGELOG.md`](CHANGELOG.md) for any user-visible change.
- **Style:** enforced by `ruff` (config in `pyproject.toml`, 100-col lines).

## Releasing (maintainers)

1. Move the `## [Unreleased]` entries into a new `## [x.y.z] - YYYY-MM-DD` section.
2. Bump `version` in `pyproject.toml` and `__version__` in `metapeek_config.py`.
3. Commit, then tag: `git tag vX.Y.Z && git push --tags`.
