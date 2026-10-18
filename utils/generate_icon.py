"""Generate app_icon.ico — a hub-in-a-wheel design — using Pillow.

Run once:  .venv/bin/python utils/generate_icon.py
Output:    app_icon.ico (and app_icon_512.png for preview)
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Design constants ---
SIZE = 512
CENTER = SIZE // 2
RIM_RADIUS = 210          # outer wheel rim
RIM_THICKNESS = 18
SPOKE_COUNT = 8
SPOKE_ANGLE_OFFSET = -90   # start vertical (12 o'clock)
SPOKE_WIDTH = 10
HUB_RADIUS = 36

# Colours
BG_COLOR = (220, 220, 222, 255)          # light grey
RIM_COLOR = (0, 168, 181, 255)         # teal-blue
SPOKE_COLOR = (0, 168, 181, 255)       # teal-blue
HUB_COLOR = (0, 168, 181, 255)         # teal-blue

ICO_SIZES = [256, 128, 64, 48, 32, 16]


def draw_wheel(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Draw the wheel-with-hub on the given ImageDraw at the given canvas size."""
    cx = cy = size // 2
    scale = size / SIZE
    rim_r = int(RIM_RADIUS * scale)
    rim_t = max(2, int(RIM_THICKNESS * scale))
    spoke_w = max(2, int(SPOKE_WIDTH * scale))
    hub_r = max(2, int(HUB_RADIUS * scale))

    # Background circle
    draw.ellipse(
        [cx - rim_r - rim_t, cy - rim_r - rim_t, cx + rim_r + rim_t, cy + rim_r + rim_t],
        fill=BG_COLOR,
    )

    # Outer rim (two concentric circles for a thick ring)
    draw.ellipse(
        [cx - rim_r - rim_t, cy - rim_r - rim_t, cx + rim_r + rim_t, cy + rim_r + rim_t],
        outline=RIM_COLOR,
        width=rim_t,
    )

    # Spokes
    for i in range(SPOKE_COUNT):
        angle = math.radians(SPOKE_ANGLE_OFFSET + i * (360 / SPOKE_COUNT))
        x1 = cx + hub_r * math.cos(angle)
        y1 = cy + hub_r * math.sin(angle)
        x2 = cx + (rim_r - rim_t // 2) * math.cos(angle)
        y2 = cy + (rim_r - rim_t // 2) * math.sin(angle)
        draw.line([x1, y1, x2, y2], fill=SPOKE_COLOR, width=spoke_w)

    # Centre hub
    draw.ellipse(
        [cx - hub_r, cy - hub_r, cx + hub_r, cy + hub_r],
        fill=HUB_COLOR,
    )


def main() -> None:
    # --- Full-size PNG (preview) ---
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_wheel(draw, SIZE)

    png_path = PROJECT_ROOT / "app_icon_512.png"
    img.save(png_path, "PNG")
    print(f"Preview:  {png_path}")

    # --- Multi-resolution ICO ---
    ico_path = PROJECT_ROOT / "app_icon.ico"
    images: list[Image.Image] = []
    for s in ICO_SIZES:
        resized = img.resize((s, s), Image.LANCZOS)
        images.append(resized)

    # Pillow saves all sizes in one .ico when given a list of images
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=images[1:],
    )
    print(f"Icon:     {ico_path}  ({', '.join(str(s) for s in ICO_SIZES)})")


if __name__ == "__main__":
    main()