"""Static 2D skins from the bundled 4096x1700 Indonesia crop. No network."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import numpy as np

DATA = Path("spike/web/data")
SRC = DATA / "skin_satellite.jpg"


def main() -> None:
    source = Image.open(SRC).convert("RGB")
    print("source", source.size)

    relief = ImageOps.grayscale(source)
    relief = ImageEnhance.Contrast(relief).enhance(1.28)
    relief = ImageOps.colorize(relief, black=(9, 18, 15), white=(236, 226, 200),
                               mid=(82, 102, 66), midpoint=86)
    relief = relief.filter(ImageFilter.UnsharpMask(radius=1.0, percent=60,
                                                   threshold=3))
    relief.save(DATA / "skin_relief.jpg", quality=88, optimize=True)

    atlas = ImageEnhance.Color(source).enhance(0.25)
    atlas = ImageEnhance.Contrast(atlas).enhance(0.9)
    paper = Image.new("RGB", source.size, (233, 226, 209))
    atlas = Image.blend(atlas, paper, 0.52)
    arr = np.asarray(source).astype("float32")
    lum = arr @ np.array([0.299, 0.587, 0.114], dtype="float32")
    sea = (lum < 58) | (arr[..., 2] > arr[..., 1] * 1.12)
    mask = Image.fromarray(((~sea) * 255).astype("uint8"), "L").filter(
        ImageFilter.GaussianBlur(2.2))
    sea_img = Image.new("RGB", source.size, (223, 229, 219))
    atlas = Image.composite(atlas, sea_img, mask)
    atlas = atlas.filter(ImageFilter.UnsharpMask(radius=0.8, percent=35,
                                                 threshold=4))
    atlas.save(DATA / "skin_atlas.jpg", quality=88, optimize=True)

    for name in ("skin_relief.jpg", "skin_atlas.jpg"):
        p = DATA / name
        print(name, p.stat().st_size, Image.open(p).size)


if __name__ == "__main__":
    main()
