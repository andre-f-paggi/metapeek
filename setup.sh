#!/usr/bin/env bash
set -e

echo "==> Installing dependencies..."
sudo pacman -S --needed python-evdev python-gobject gtk4 gtk4-layer-shell

echo "==> Adding $USER to input group..."
sudo usermod -aG input "$USER"

echo ""
echo "Done. You MUST log out and back in (or reboot) for the group change to take effect."
echo ""
echo "Run the overlay (then hold Meta):"
echo "  python3 taskbar_overlay.py"
echo ""
echo "Optional config: ~/.config/taskbar-overlay.ini  (see README.md)"
echo ""
echo "Autostart: System Settings → Autostart → Add Application, command:"
echo "  python3 $(pwd)/taskbar_overlay.py"
