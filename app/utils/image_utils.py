from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def is_supported_image_path(path: str | Path) -> bool:
    return Path(str(path)).suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS


def normalize_image_extension(value: str | Path) -> str:
    text = str(value)
    suffix = Path(text).suffix if "." in text else text
    extension = suffix.lstrip(".").casefold()
    if extension == "jpeg":
        return "jpg"
    if extension in {"jpg", "png", "webp"}:
        return extension
    return "jpg"


def write_poster_jpeg(image_bytes: bytes, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(image_bytes)) as image:
        if image.mode in {"RGBA", "LA"}:
            background = Image.new("RGB", image.size, (255, 255, 255))
            alpha = image.getchannel("A") if image.mode == "RGBA" else image.getchannel("A")
            background.paste(image.convert("RGBA"), mask=alpha)
            poster = background
        else:
            poster = image.convert("RGB")
        poster.save(output_path, format="JPEG", quality=95)
