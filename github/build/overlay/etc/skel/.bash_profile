# OnlyBrowserOS: automatic login lands on tty1, and that is where the screen
# session starts. Other consoles (Ctrl+Alt+F2) stay a plain shell, the way in
# for fixing a machine whose browser will not start.

[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"

if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then
    state="$HOME/.local/state/onlybrowseros"
    mkdir -p "$state"
    # If the screen session stops (a graphics driver hiccup), start it again
    # instead of leaving a text console. Give up only when it keeps failing
    # within seconds, which means it cannot start at all.
    quick=0
    while [ "$quick" -lt 3 ]; do
        started=$(date +%s)
        [ -f "$state/xorg.log" ] && mv -f "$state/xorg.log" "$state/xorg.log.old"
        startx /usr/bin/onlybrowseros-session -- vt1 -keeptty -nolisten tcp \
            >"$state/xorg.log" 2>&1
        if [ $(( $(date +%s) - started )) -lt 30 ]; then
            quick=$((quick + 1))
        else
            quick=0
        fi
        sleep 2
    done
    echo
    echo "The OnlyBrowserOS screen session could not start."
    echo "Type  startx  to try again, or  sudo reboot  to restart the computer."
    echo "If it keeps happening, start from the OnlyBrowserOS USB stick and choose"
    echo "\"safe graphics\" under Advanced options. Details: ~/.local/state/onlybrowseros/xorg.log"
fi
