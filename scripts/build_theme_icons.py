"""Generate the small static spin-box arrow assets used by the Qt theme."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "resources" / "icons"
SCALE = 4
SIZE = 12

THEMES = {
    "light": "#1f2430",
    "dark": "#e4e7eb",
}


def _render_chevron(direction: str, color: str) -> Image.Image:
    canvas_size = SIZE * SCALE
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset_x = 2 * SCALE
    top_y = (SIZE // 2 - 2) * SCALE
    bottom_y = (SIZE // 2 + 2) * SCALE
    middle_x = (SIZE // 2) * SCALE

    if direction == "up":
        points = [(inset_x, bottom_y), (middle_x, top_y), (canvas_size - inset_x, bottom_y)]
    elif direction == "down":
        points = [(inset_x, top_y), (middle_x, bottom_y), (canvas_size - inset_x, top_y)]
    else:
        raise ValueError(f"Unsupported chevron direction: {direction}")

    draw.line(points, fill=color, width=7, joint="curve")
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for theme_name, color in THEMES.items():
        for direction in ("up", "down"):
            output = ICON_DIR / f"spinbox_arrow_{direction}_{theme_name}.png"
            _render_chevron(direction, color).save(output, format="PNG", optimize=True)
            print(f"Created {output}")


if __name__ == "__main__":
    main()
