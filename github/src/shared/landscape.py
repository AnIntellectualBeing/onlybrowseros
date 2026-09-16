"""
The OnlyBrowserOS landscape: a painted-style mountain lake at sunrise, made
of a few dozen flat shapes so it costs almost nothing to draw on an old
laptop and needs no image files.

One description, two outputs:

    draw(cr, width, height)           cairo, for the home screen
    python3 landscape.py --svg        SVG on its own
    python3 landscape.py --page FILE  FILE with <!-- LANDSCAPE --> replaced by
                                      the SVG (the build does this for the
                                      start page)

The picture is 1600 x 900 units and is scaled to cover the screen, anchored
to the bottom so the lake and trees always show.
"""

import functools
import math
import random
import sys
from pathlib import Path

PLACEHOLDER = "<!-- LANDSCAPE -->"

W, H = 1600, 900

# (offset, colour) stops for vertical gradients, top to bottom.
SKY = [(0.0, "#a9d2ff"), (0.45, "#d7ebff"), (0.72, "#f3f4f6"), (0.80, "#fde9d2")]
LAKE = [(0.0, "#c7e0fb"), (0.35, "#9cc6f2"), (1.0, "#5f9ce0")]


def _ridge(seed, y_base, amplitude, peaks, x0=-40, x1=W + 40, step=40):
    """A mountain ridge as a closed polygon down to the lake line."""
    rnd = random.Random(seed)
    points = []
    x = x0
    while x <= x1:
        h = 0.0
        for px, py, spread in peaks:
            h = max(h, py * math.exp(-((x - px) / spread) ** 2))
        h += rnd.uniform(-amplitude, amplitude)
        points.append((x, y_base - max(0.0, h)))
        x += step
    return points + [(x1, 700), (x0, 700)]


def _snow(ridge, below):
    """Snow caps: the ridge points higher than `below`, closed along it."""
    caps = []
    run = []
    for x, y in ridge[:-2]:
        if y < below:
            run.append((x, y))
        elif run:
            caps.append(run)
            run = []
    shapes = []
    for run in caps:
        if len(run) < 2:
            continue
        x_mid = sum(p[0] for p in run) / len(run)
        shapes.append(run + [(run[-1][0] + 18, below + 22), (x_mid, below + 6), (run[0][0] - 18, below + 22)])
    return shapes


def _pine(x, base, height, width):
    """A layered pine: three stacked triangles."""
    shapes = []
    for i in range(3):
        top = base - height + i * height * 0.22
        bottom = base - height * 0.30 + i * height * 0.25
        half = width * (0.55 + i * 0.25) / 2
        shapes.append([(x, top), (x + half, bottom), (x - half, bottom)])
    return shapes


@functools.lru_cache(maxsize=1)
def shapes():
    """Everything to paint, back to front: (kind, data, fill, alpha)."""
    out = []
    out.append(("rect", (0, 0, W, 700), ("grad", 0, 700, SKY), 1.0))
    out.append(("circle", (1330, 470, 150), "#fff3dc", 0.55))
    out.append(("circle", (1330, 470, 64), "#fffaf0", 1.0))

    for cx, cy, s in ((260, 250, 1.0), (1180, 190, 0.8), (720, 120, 0.6)):
        for dx, dy, r in ((0, 0, 60), (65, 12, 48), (-62, 16, 44), (120, 28, 34), (-110, 30, 30)):
            out.append(("circle", (cx + dx * s, cy + dy * s, r * s), "#ffffff", 0.75))

    far = _ridge(3, 690, 6, [(150, 300, 160), (520, 210, 190), (980, 260, 170), (1450, 250, 200)])
    out.append(("poly", far, "#c3d4ee", 1.0))
    mid = _ridge(7, 700, 10, [(330, 360, 150), (760, 150, 170), (1270, 290, 150)])
    out.append(("poly", mid, "#9db6df", 1.0))
    for cap in _snow(mid, 420):
        out.append(("poly", cap, "#f4f8ff", 0.9))
    near_left = _ridge(11, 705, 8, [(-20, 250, 260), (300, 120, 160)], x0=-40, x1=720)
    out.append(("poly", near_left, "#6f93c7", 1.0))
    near_right = _ridge(13, 705, 8, [(1640, 260, 260), (1300, 110, 170)], x0=900, x1=W + 40)
    out.append(("poly", near_right, "#7398cb", 1.0))

    out.append(("rect", (0, 690, W, 210), ("grad", 690, 900, LAKE), 1.0))
    for y, x, w in ((712, 560, 520), (736, 300, 360), (736, 1020, 300), (768, 640, 460),
                    (800, 180, 300), (812, 1180, 260), (846, 700, 380)):
        out.append(("rect", (x, y, w, 3), "#ffffff", 0.45))

    out.append(("poly", [(-20, 700), (140, 690), (330, 712), (520, 760), (560, 900), (-20, 900)], "#5c9a5a", 1.0))
    out.append(("poly", [(W + 20, 700), (1470, 692), (1300, 716), (1120, 770), (1080, 900), (W + 20, 900)], "#5c9a5a", 1.0))
    out.append(("poly", [(-20, 790), (240, 800), (430, 900), (-20, 900)], "#7fb86a", 1.0))
    out.append(("poly", [(W + 20, 800), (1380, 808), (1200, 900), (W + 20, 900)], "#7fb86a", 1.0))

    rnd = random.Random(21)
    for x0, x1, side in ((-10, 360, 0), (1250, 1610, 1)):
        x = x0
        while x < x1:
            edge = (x - x0) / (x1 - x0) if side == 0 else (x1 - x) / (x1 - x0)
            height = rnd.uniform(90, 160) * (1.0 - 0.55 * edge)
            base = 720 + rnd.uniform(-6, 10)
            colour = "#2f6b4f" if rnd.random() < 0.6 else "#3d8058"
            for tri in _pine(x, base, height, height * 0.42):
                out.append(("poly", tri, colour, 1.0))
            x += rnd.uniform(22, 38)
    return out


# ------------------------------------------------------------------ cairo

def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def draw(cr, width, height):
    import cairo

    scale = max(width / W, height / H)
    cr.save()
    cr.translate((width - W * scale) / 2, height - H * scale)
    cr.scale(scale, scale)
    for kind, data, fill, alpha in shapes():
        if kind == "rect":
            cr.rectangle(*data)
        elif kind == "circle":
            cr.new_sub_path()
            cr.arc(data[0], data[1], data[2], 0, 2 * math.pi)
        else:
            cr.move_to(*data[0])
            for p in data[1:]:
                cr.line_to(*p)
            cr.close_path()
        if isinstance(fill, tuple):
            _, y1, y2, stops = fill
            grad = cairo.LinearGradient(0, y1, 0, y2)
            for offset, colour in stops:
                grad.add_color_stop_rgba(offset, *_rgb(colour), alpha)
            cr.set_source(grad)
        else:
            cr.set_source_rgba(*_rgb(fill), alpha)
        cr.fill()
    cr.restore()


# -------------------------------------------------------------------- svg

def svg():
    defs, body, grads = [], [], {}
    for kind, data, fill, alpha in shapes():
        if isinstance(fill, tuple):
            key = id(fill[3])
            if key not in grads:
                gid = f"g{len(grads)}"
                grads[key] = gid
                stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in fill[3])
                defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="0" y1="{fill[1]}" '
                            f'x2="0" y2="{fill[2]}">{stops}</linearGradient>')
            paint = f'url(#{grads[key]})'
        else:
            paint = fill
        op = "" if alpha >= 1 else f' opacity="{alpha:g}"'
        if kind == "rect":
            x, y, w, h = data
            body.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{paint}"{op}/>')
        elif kind == "circle":
            body.append(f'<circle cx="{data[0]:g}" cy="{data[1]:g}" r="{data[2]:g}" fill="{paint}"{op}/>')
        else:
            pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in data)
            body.append(f'<polygon points="{pts}" fill="{paint}"{op}/>')
    return (f'<svg class="landscape" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMax slice" '
            f'aria-hidden="true"><defs>{"".join(defs)}</defs>{"".join(body)}</svg>')


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--svg"]:
        print(svg())
    elif len(args) == 2 and args[0] == "--page":
        page = Path(args[1]).read_text()
        if PLACEHOLDER not in page:
            print(f"landscape.py: {args[1]} has no {PLACEHOLDER}", file=sys.stderr)
            sys.exit(1)
        sys.stdout.write(page.replace(PLACEHOLDER, svg(), 1))
    else:
        print("usage: landscape.py --svg | --page FILE", file=sys.stderr)
        sys.exit(2)
