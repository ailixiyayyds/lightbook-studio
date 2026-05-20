from __future__ import annotations

import logging
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.models import ComicMetadata, ExporterError
from app.exporters.comicinfo_writer import build_comicinfo_xml
from app.utils.filename import unique_path
from app.utils.image_utils import is_supported_image_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CbzRewriteResult:
    cbz_path: Path
    warnings: list[str] = field(default_factory=list)


def rewrite_cbz_metadata(
    source_cbz_path: str | Path,
    output_cbz_path: str | Path,
    metadata: ComicMetadata,
    cover_override_path: str | Path | None = None,
) -> CbzRewriteResult:
    source_path = Path(source_cbz_path)
    requested_output_path = Path(output_cbz_path)
    cover_path = Path(cover_override_path) if cover_override_path is not None else None

    if not source_path.exists():
        raise ExporterError(f"源 CBZ 文件不存在：{source_path}")
    if not source_path.is_file():
        raise ExporterError(f"源路径不是 CBZ 文件：{source_path}")
    if source_path.suffix.casefold() != ".cbz":
        raise ExporterError(f"源文件不是 .cbz：{source_path}")
    if cover_path is not None and not cover_path.is_file():
        raise ExporterError(f"封面覆盖文件不存在：{cover_path}")

    output_path = unique_path(requested_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    try:
        with zipfile.ZipFile(source_path) as source_archive:
            image_names = _image_names(source_archive)
            if not image_names:
                raise ExporterError(f"源 CBZ 中没有可复制的图片：{source_path}")

            ignored_names = [
                info.filename
                for info in source_archive.infolist()
                if not info.is_dir()
                and not _is_comicinfo_path(info.filename)
                and not is_supported_image_path(info.filename)
            ]
            if ignored_names:
                warnings.append(
                    "已忽略非图片文件：" + ", ".join(ignored_names[:10])
                )

            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as target_archive:
                target_archive.writestr("ComicInfo.xml", build_comicinfo_xml(metadata))
                _copy_images(source_archive, target_archive, image_names, cover_path)
    except zipfile.BadZipFile as exc:
        raise ExporterError(f"源 CBZ 不是有效的 ZIP 文件：{source_path}") from exc
    except OSError as exc:
        raise ExporterError(f"重写 CBZ 元数据失败：{exc}") from exc

    logger.info("Rewrote CBZ metadata from %s to %s", source_path, output_path)
    return CbzRewriteResult(cbz_path=output_path, warnings=warnings)


def _image_names(archive: zipfile.ZipFile) -> list[str]:
    return [
        info.filename
        for info in archive.infolist()
        if not info.is_dir() and is_supported_image_path(info.filename)
    ]


def _copy_images(
    source_archive: zipfile.ZipFile,
    target_archive: zipfile.ZipFile,
    image_names: list[str],
    cover_override_path: Path | None,
) -> None:
    cover_written = False
    for image_name in image_names:
        if cover_override_path is not None and not cover_written:
            target_archive.writestr(
                _cover_target_name(image_name, cover_override_path),
                cover_override_path.read_bytes(),
            )
            cover_written = True
            continue
        target_archive.writestr(image_name, source_archive.read(image_name))


def _cover_target_name(original_cover_name: str, cover_override_path: Path) -> str:
    original_dir = posixpath.dirname(original_cover_name)
    original_stem = Path(posixpath.basename(original_cover_name)).stem or "cover"
    extension = cover_override_path.suffix or Path(original_cover_name).suffix
    filename = f"{original_stem}{extension.casefold()}"
    return f"{original_dir}/{filename}" if original_dir else filename


def _is_comicinfo_path(path: str) -> bool:
    return posixpath.basename(path).casefold() == "comicinfo.xml"
