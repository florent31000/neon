"""
Generate eye emotion images for Neon.
Run: py generate_eyes.py

Creates stylized neon/cyberpunk eyes on black backgrounds.
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    print("pip install Pillow")
    exit(1)

OUTPUT_DIR = Path(__file__).parent / "assets" / "eyes"
WIDTH, HEIGHT = 1920, 1080


def draw_eye(draw, cx, cy, eye_w, eye_h, pupil_scale, lid_top, lid_bot,
             px_off, py_off, color, glow_color, is_left=True):
    draw.ellipse(
        [cx - eye_w, cy - eye_h, cx + eye_w, cy + eye_h],
        fill=(20, 20, 30),
        outline=glow_color,
        width=3,
    )

    iris_r = eye_w * 0.55
    ix = cx + px_off * eye_w * (1 if is_left else -1)
    iy = cy + py_off * eye_h
    draw.ellipse(
        [ix - iris_r, iy - iris_r, ix + iris_r, iy + iris_r],
        fill=(color[0] // 4, color[1] // 4, color[2] // 4),
        outline=color,
        width=2,
    )

    pupil_r = iris_r * 0.5 * pupil_scale
    if pupil_r > 1:
        draw.ellipse(
            [ix - pupil_r, iy - pupil_r, ix + pupil_r, iy + pupil_r],
            fill=color,
        )
        hl_r = pupil_r * 0.3
        hl_x = ix + pupil_r * 0.25
        hl_y = iy - pupil_r * 0.25
        draw.ellipse(
            [hl_x - hl_r, hl_y - hl_r, hl_x + hl_r, hl_y + hl_r],
            fill=(255, 255, 255, 200),
        )

    if lid_top > 0.02:
        lid_h = eye_h * 2 * lid_top
        draw.rectangle(
            [cx - eye_w - 5, cy - eye_h - 5, cx + eye_w + 5, cy - eye_h + lid_h],
            fill=(0, 0, 0),
        )

    if lid_bot > 0.02:
        lid_h = eye_h * 2 * lid_bot
        draw.rectangle(
            [cx - eye_w - 5, cy + eye_h - lid_h, cx + eye_w + 5, cy + eye_h + 5],
            fill=(0, 0, 0),
        )


def generate_emotion(name, params):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    cx, cy = WIDTH / 2, HEIGHT / 2
    spacing = WIDTH * 0.15
    eye_w = WIDTH * 0.10
    eye_h = HEIGHT * 0.22

    color = params["color"]
    glow = tuple(max(0, c // 2) for c in color)

    for side, is_left in [(-1, True), (1, False)]:
        draw_eye(
            draw, cx + side * spacing, cy, eye_w, eye_h,
            params.get("pupil", 1.0), params.get("lid_top", 0.1),
            params.get("lid_bot", 0.05), params.get("px", 0),
            params.get("py", 0), color, glow, is_left,
        )

    img = img.filter(ImageFilter.GaussianBlur(radius=2))

    draw2 = ImageDraw.Draw(img)
    for side, is_left in [(-1, True), (1, False)]:
        ex = cx + side * spacing
        ix = ex + params.get("px", 0) * eye_w * (1 if is_left else -1)
        iy = cy + params.get("py", 0) * eye_h
        pupil_r = eye_w * 0.55 * 0.5 * params.get("pupil", 1.0)
        if pupil_r > 1:
            hl_r = pupil_r * 0.25
            draw2.ellipse(
                [ix + pupil_r * 0.25 - hl_r, iy - pupil_r * 0.25 - hl_r,
                 ix + pupil_r * 0.25 + hl_r, iy - pupil_r * 0.25 + hl_r],
                fill=(255, 255, 255),
            )

    out = OUTPUT_DIR / f"{name}.png"
    img.save(out)
    print(f"  {name}.png")


EMOTIONS = {
    "neutral":  {"pupil": 1.0, "lid_top": 0.10, "lid_bot": 0.05, "px": 0,   "py": 0,    "color": (77, 230, 255)},
    "happy":    {"pupil": 0.9, "lid_top": 0.30, "lid_bot": 0.15, "px": 0,   "py": 0,    "color": (100, 255, 150)},
    "excited":  {"pupil": 1.3, "lid_top": 0.00, "lid_bot": 0.00, "px": 0,   "py": 0,    "color": (255, 230, 50)},
    "curious":  {"pupil": 1.2, "lid_top": 0.05, "lid_bot": 0.00, "px": 0.1, "py": 0.1,  "color": (100, 200, 255)},
    "annoyed":  {"pupil": 0.8, "lid_top": 0.35, "lid_bot": 0.10, "px": 0,   "py": -0.05,"color": (255, 100, 80)},
    "sad":      {"pupil": 0.9, "lid_top": 0.25, "lid_bot": 0.00, "px": 0,   "py": -0.1, "color": (100, 150, 255)},
    "angry":    {"pupil": 0.7, "lid_top": 0.30, "lid_bot": 0.10, "px": 0,   "py": 0,    "color": (255, 30, 30)},
    "love":     {"pupil": 1.1, "lid_top": 0.15, "lid_bot": 0.10, "px": 0,   "py": 0,    "color": (255, 50, 130)},
    "sleeping": {"pupil": 0.0, "lid_top": 0.95, "lid_bot": 0.00, "px": 0,   "py": 0,    "color": (80, 80, 130)},
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Clean old images
    for f in OUTPUT_DIR.glob("*.png"):
        f.unlink()
    print(f"Generating {len(EMOTIONS)} eye images...")
    for name, params in EMOTIONS.items():
        generate_emotion(name, params)
    print("Done!")


if __name__ == "__main__":
    main()
