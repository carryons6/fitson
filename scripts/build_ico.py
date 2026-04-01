"""Convert main_icon.png to .ico for PyInstaller.

Requires Pillow: pip install Pillow
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PNG_PATH = ROOT / "resources" / "icons" / "main_icon.png"
ICO_PATH = ROOT / "resources" / "icons" / "main_icon.ico"

SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    img = Image.open(PNG_PATH).convert("RGBA")
    icons = [img.resize(s, Image.LANCZOS) for s in SIZES]
    icons[-1].save(ICO_PATH, format="ICO", sizes=SIZES, append_images=icons[1:])
    print(f"Created {ICO_PATH}")


if __name__ == "__main__":
    main()
