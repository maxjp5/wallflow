"""Draws the Wallflow 'Flow' logo and writes wallflow.ico (all Windows sizes) and logo.png.

Run: python make_icon.py
"""
from PIL import Image, ImageDraw

SIZE = 1024
K = SIZE / 96            # design grid: 96x96 tile
OFF = 9                  # artwork margin inside the tile (smaller = bigger artwork)
A = (96 - 2 * OFF) / 64  # artwork is drawn on a 64x64 grid, scaled to fill the tile
BG = (20, 20, 24, 255)
WHITE = (255, 255, 255)


def u(v):
    return (OFF + v * A) * K


def card(img, x, y, w, h, opacity, angle=0.0, center=None):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([u(x), u(y), u(x + w), u(y + h)], radius=7 * A * K,
                                            fill=WHITE + (int(255 * opacity),))
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, center=(u(center[0]), u(center[1])))
    img.alpha_composite(layer)


def bezier(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 3
        b = 3 * (1 - t) ** 2 * t
        c = 3 * (1 - t) * t ** 2
        d = t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def draw_logo():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=21 * K, fill=BG)
    card(img, 10, 22, 44, 30, 0.35, angle=10, center=(32, 37))     # back card, tilted
    card(img, 12, 18, 44, 30, 0.60, angle=4, center=(34, 33))      # middle card
    card(img, 14, 16, 40, 30, 1.00)                                # front card
    # the wave on the front card
    wave = bezier((18, 31), (23, 25), (27, 25), (32, 31)) + bezier((32, 31), (37, 37), (41, 37), (46, 31))[1:]
    pts = [(u(x), u(y)) for x, y in wave]
    d = ImageDraw.Draw(img)
    r = 3.4 * A * K / 2
    dense = []                                   # stamp round dots along the curve: a perfectly smooth stroke
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 2))
        dense += [(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps) for i in range(steps)]
    for x, y in dense + [pts[-1]]:
        d.ellipse([x - r, y - r, x + r, y + r], fill=BG)
    return img


if __name__ == "__main__":
    logo = draw_logo()
    logo.resize((512, 512), Image.LANCZOS).save("logo.png")
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    logo.resize((256, 256), Image.LANCZOS).save("wallflow.ico", sizes=sizes)
    print("wrote wallflow.ico and logo.png")
