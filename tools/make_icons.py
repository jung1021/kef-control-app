"""Generates every icon KEF Control uses, from one design (Pillow only).

    python tools/make_icons.py

Design: a warm orange tile with a white speaker cabinet and a large concentric
(coaxial) driver, readable down to 16 px. Small sizes use a simplified drawing.
Writes:
  src/kef_control.ico            app/exe/tray/shortcut icon (16-256 px)
  src/icon.png                   256 px, used as the window (taskbar) icon
  docs/favicon.png               website favicon (64 px)
  docs/icon-512.png              website / social use
  packaging/msix/Assets/*.png    Microsoft Store tiles
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
S = 1024  # master canvas

ORANGE_TOP = (255, 128, 82)
ORANGE_BOTTOM = (214, 66, 22)
CABINET = (250, 250, 250)
DARK = (28, 30, 34)
CONE = (232, 87, 42)
DOME = (44, 47, 53)


def _gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((size, size))


def draw(simple: bool = False, pad: float = 0.0) -> Image.Image:
    """Master drawing at 1024 px. `pad` shrinks the tile (for Store assets with margins)."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    p = round(S * pad)
    tile = S - 2 * p
    # orange tile
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([p, p, S - p - 1, S - p - 1], radius=round(tile * 0.23), fill=255)
    img.paste(_gradient(S, ORANGE_TOP, ORANGE_BOTTOM), (0, 0), mask)
    d = ImageDraw.Draw(img)

    def u(v: float) -> int:  # units relative to the tile
        return p + round(tile * v)

    # cabinet (taller than wide), with a soft lower shade
    cw = 0.50 if not simple else 0.56
    ch = 0.72 if not simple else 0.74
    x0, x1 = u(0.5 - cw / 2), u(0.5 + cw / 2)
    y0, y1 = u(0.5 - ch / 2), u(0.5 + ch / 2)
    r = round(tile * (0.09 if not simple else 0.10))
    d.rounded_rectangle([x0, y0 + round(tile * 0.018), x1, y1 + round(tile * 0.018)], radius=r, fill=(150, 45, 12, 110))
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=CABINET)

    # concentric driver, slightly below centre
    cx, cy = u(0.5), u(0.56 if not simple else 0.55)

    def circle(radius: float, fill: tuple) -> None:
        rr = round(tile * radius)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=fill)

    if simple:
        circle(0.205, DARK)
        circle(0.12, CONE)
        circle(0.05, DARK)
    else:
        circle(0.195, DARK)          # surround
        circle(0.172, (52, 55, 61))  # surround highlight
        circle(0.155, DARK)
        circle(0.125, CONE)          # cone
        circle(0.062, DOME)          # tweeter waveguide
        circle(0.032, (88, 92, 100)) # tweeter dome
        # small status light at the top of the cabinet
        lr = round(tile * 0.018)
        lx, ly = u(0.5), u(0.5 - ch / 2 + 0.085)
        d.ellipse([lx - lr, ly - lr, lx + lr, ly + lr], fill=CONE)
    return img


def render(size: int, pad: float = 0.0) -> Image.Image:
    simple = size <= 24
    return draw(simple=simple, pad=pad).resize((size, size), Image.LANCZOS)


def main() -> None:
    src = ROOT / "src"
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [render(s) for s in sizes]
    frames[-1].save(src / "kef_control.ico", sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])
    render(256).save(src / "icon.png", optimize=True)
    (ROOT / "docs").mkdir(exist_ok=True)
    render(64).save(ROOT / "docs" / "favicon.png", optimize=True)
    render(512).save(ROOT / "docs" / "icon-512.png", optimize=True)
    assets = ROOT / "packaging" / "msix" / "Assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name, size in [("Square44x44Logo.png", 44), ("Square71x71Logo.png", 71), ("Square150x150Logo.png", 150),
                       ("Square310x310Logo.png", 310), ("StoreLogo.png", 50)]:
        render(size, pad=0.06).save(assets / name, optimize=True)
    wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
    wide.paste(render(124, pad=0.04), (93, 13))
    wide.save(assets / "Wide310x150Logo.png", optimize=True)
    print("icons written")


if __name__ == "__main__":
    main()
