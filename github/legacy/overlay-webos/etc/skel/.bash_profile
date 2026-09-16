# WebOS: autologin lands on tty1, and that is where the graphical session
# begins. Other ttys stay a plain shell, which is the escape hatch when the
# browser will not start (Ctrl+Alt+F2).

[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"

if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then
    mkdir -p "$HOME/.local/state/webos"
    exec startx -- vt1 >"$HOME/.local/state/webos/xorg.log" 2>&1
fi
