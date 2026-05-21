from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from app.core.models import ComicMetadata, ComicPage, ExportResult, ExporterError, ImportResult
from app.exporters.comicinfo_writer import build_comicinfo_xml
from app.utils.filename import sanitize_windows_filename, unique_path
from app.utils.image_utils import normalize_image_extension, write_poster_jpeg

logger = logging.getLogger(__name__)


def export_cbz(
    import_result: ImportResult,
    output_root: str | Path,
    metadata: ComicMetadata | None = None,
    cover_override_path: str | Path | None = None,
) -> ExportResult:
    if not import_result.pages:
        raise ExporterError("没有可导出的页面。")

    logger.info(
        "CBZ 导出开始 source=%s pages=%s output_root=%s",
        import_result.source_path,
        len(import_result.pages),
        output_root,
    )

    metadata_to_write = metadata or import_result.metadata
    series_title = metadata_to_write.series_title or import_result.metadata.series_title or "Untitled"
    safe_series_title = sanitize_windows_filename(series_title)
    volume_number = int(metadata_to_write.volume_number or 1)

    series_dir = Path(output_root) / "Manga" / safe_series_title
    series_dir.mkdir(parents=True, exist_ok=True)
    cbz_path = unique_path(series_dir / f"{safe_series_title} v{volume_number:02d}.cbz")
    poster_path = series_dir / "poster.jpg"

    try:
        comicinfo_xml = build_comicinfo_xml(metadata_to_write)
        with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
            cbz.writestr("ComicInfo.xml", comicinfo_xml)
            if import_result.source_type in {"epub", "cbz"}:
                _write_archive_pages(cbz, import_result)
            else:
                _write_file_pages(cbz, import_result.pages)

        cover_bytes = _read_cover_bytes(import_result, cover_override_path)
        write_poster_jpeg(cover_bytes, poster_path)
    except OSError as exc:
        raise ExporterError(f"导出失败：{exc}") from exc
    except zipfile.BadZipFile as exc:
        raise ExporterError(f"读取归档源文件失败：{exc}") from exc
    except Exception as exc:
        if isinstance(exc, ExporterError):
            raise
        raise ExporterError(f"导出失败：{exc}") from exc

    logger.info("Exported CBZ to %s", cbz_path)
    return ExportResult(
        cbz_path=cbz_path,
        poster_path=poster_path,
        warnings=import_result.warnings.copy(),
    )


def _read_cover_bytes(import_result: ImportResult, cover_override_path: str | Path | None) -> bytes:
    if cover_override_path is not None:
        cover_path = Path(cover_override_path)
        if not cover_path.is_file():
            raise ExporterError(f"自定义封面不存在：{cover_path}")
        return cover_path.read_bytes()
    return _read_page_bytes(import_result, import_result.pages[0])


def _write_file_pages(cbz: zipfile.ZipFile, pages: list[ComicPage]) -> None:
    for index, page in enumerate(pages, start=1):
        if page.source_path is None:
            raise ExporterError(f"页面缺少源文件路径：{page.display_name}")
        cbz.writestr(_cbz_page_name(index, page), page.source_path.read_bytes())


def _write_archive_pages(cbz: zipfile.ZipFile, import_result: ImportResult) -> None:
    with zipfile.ZipFile(import_result.source_path) as source_zip:
        for index, page in enumerate(import_result.pages, start=1):
            if not page.archive_path:
                raise ExporterError(f"页面缺少归档内部路径：{page.display_name}")
            cbz.writestr(_cbz_page_name(index, page), source_zip.read(page.archive_path))


def _read_page_bytes(import_result: ImportResult, page: ComicPage) -> bytes:
    if import_result.source_type in {"epub", "cbz"}:
        if not page.archive_path:
            raise ExporterError(f"页面缺少归档内部路径：{page.display_name}")
        with zipfile.ZipFile(import_result.source_path) as source_zip:
            return source_zip.read(page.archive_path)

    if page.source_path is None:
        raise ExporterError(f"页面缺少源文件路径：{page.display_name}")
    return page.source_path.read_bytes()


def _cbz_page_name(index: int, page: ComicPage) -> str:
    extension = normalize_image_extension(page.extension)
    return f"{index:04d}.{extension}"
