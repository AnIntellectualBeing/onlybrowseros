# OnlyBrowserOS: automatic login lands on tty1, and that is where the screen
# session starts. Other consoles (Ctrl+Alt+F2) stay a plain shell, the way in
# for fixing a machine whose browser will not start.

[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"

if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then
    mkdir -p "$HOME/.local/state/onlybrowseros"
    startx /usr/bin/onlybrowseros-session -- vt1 -keeptty -nolisten tcp \
        >"$HOME/.local/state/onlybrowseros/xorg.log" 2>&1
    echo
    echo "The OnlyBrowserOS screen session stopped."
    echo "Type  startx  to try again, or  sudo reboot  to restart the computer."
    echo "Details: ~/.local/state/onlybrowseros/xorg.log"
fi
