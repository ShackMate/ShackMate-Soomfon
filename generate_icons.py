"""Generate icons/1.png .. icons/6.png for the Soomfon LCD keys:
RIG, Antenna, Tuner, Rotator, Satellites, Scanner (in key order)."""

import math
import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 160          # generated large, set_key_image() downsamples to 64x64
OUT_DIR = "icons"
WHITE = (240, 240, 240)
LW = 7               # line width for icon strokes


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _label(draw: ImageDraw.ImageDraw, text: str, font_size: int = 22) -> None:
    font = _font(font_size)
    draw.text((SIZE / 2, SIZE - 20), text, fill=WHITE, font=font, anchor="mm")


def draw_rig(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Mobile transceiver + mic glyph (user-provided reference), recolored
    solid white, no text label so it fills the key."""
    _fit_external_image(img, "rig_ref.png", label_h=0, recolor=WHITE, crop_box=(4, 4, 532, 528))


def draw_antenna(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Yagi antenna glyph (user-provided reference), recolored solid white,
    no text label so it fills the key."""
    _fit_external_image(img, "antenna_ref.png", label_h=0, recolor=WHITE, native_alpha=True)


ASSETS_DIR = "assets"


def _fit_external_image(img: Image.Image, filename: str, label_h: int = 36, pad: int = 10,
                         crop_box: tuple = None, recolor: tuple = None, native_alpha: bool = False) -> None:
    """Load a reference image and scale it to fit the icon's content area
    (above the label strip) - used instead of hand-drawing when a provided
    image should be used as-is rather than redrawn.

    If `native_alpha` is True, the source's own alpha channel is trusted as
    the shape mask (e.g. a chart rendered with a transparent background).
    Otherwise its near-white background is keyed out to transparency - only
    safe when the foreground isn't also near-white. If `recolor` is given,
    every non-background pixel is replaced with that solid color."""
    src = Image.open(os.path.join(ASSETS_DIR, filename)).convert("RGBA")
    if crop_box:
        src = src.crop(crop_box)

    if native_alpha:
        mask = src.getchannel("A")
    else:
        gray = src.convert("L")
        mask = gray.point(lambda p: 0 if p > 235 else 255)
    if recolor:
        solid = Image.new("RGBA", src.size, (*recolor, 255))
        solid.putalpha(mask)
        src = solid
    else:
        src.putalpha(mask)

    bbox = src.getbbox()
    if bbox:
        src = src.crop(bbox)

    avail_w, avail_h = SIZE - 2 * pad, SIZE - label_h - 2 * pad
    scale = min(avail_w / src.width, avail_h / src.height)
    src = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.LANCZOS)

    x = (SIZE - src.width) // 2
    y = (SIZE - label_h - src.height) // 2
    img.paste(src, (x, y), src)


def draw_rotator(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Polar/compass plot (user-provided reference, regenerated with fewer
    rings, white rings/labels, and no text so the chart fills the key)."""
    _fit_external_image(img, "rotator_ref.png", label_h=0, native_alpha=True)


def draw_satellites(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Satellite glyph (user-provided reference, used as-is but recolored
    solid white to match the rest of the icon set)."""
    _fit_external_image(img, "satellite_ref.png", label_h=0, recolor=WHITE)


def draw_tuner(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Tuning fork glyph (user-provided reference), recolored solid white,
    no text label so it fills the key."""
    _fit_external_image(img, "tuner_ref.png", label_h=0, recolor=WHITE)


def draw_scanner(img: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Scanner radio glyph (user-provided reference), recolored solid white,
    no text label so it fills the key."""
    _fit_external_image(img, "scanner_ref.jpeg", label_h=0, recolor=WHITE)


TOPICS = {
    1: ("RIG", (120, 40, 40), draw_rig, 30),
    2: ("ANTENNA", (40, 90, 140), draw_antenna, 22),
    3: ("TUNER", (40, 120, 70), draw_tuner, 22),
    4: ("ROTATOR", (20, 35, 85), draw_rotator, 22),
    5: ("SATELLITES", (90, 50, 130), draw_satellites, 22),
    6: ("SCANNER", (30, 120, 120), draw_scanner, 22),
}


NO_LABEL_KEYS = {1, 2, 3, 4, 5, 6}   # all six keys now use image-filled icons


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for key, (label, bg, draw_fn, font_size) in TOPICS.items():
        img = Image.new("RGB", (SIZE, SIZE), bg)
        draw = ImageDraw.Draw(img)
        draw_fn(img, draw)
        if key not in NO_LABEL_KEYS:
            _label(draw, label, font_size)
        path = os.path.join(OUT_DIR, f"{key}.png")
        img.save(path)
        print(f"wrote {path} ({label})")


if __name__ == "__main__":
    main()
