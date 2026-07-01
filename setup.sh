#!/usr/bin/env bash
set -e

echo "==> Installing dependencies..."
sudo pacman -S --needed python-evdev python-gobject gtk4 gtk4-layer-shell

echo "==> Adding $USER to input group..."
sudo usermod -aG input "$USER"

echo ""
echo "Done. You MUST log out and back in (or reboot) for group change to take effect."
echo ""
echo "To run the overlay:"
echo "  python3 taskbar_overlay.py"
echo ""
echo "To autostart: add to KDE Autostart in System Settings → Autostart"
echo "  Command: python3 $(pwd)/taskbar_overlay.py"
