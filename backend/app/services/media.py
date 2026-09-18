"""媒体文件落盘与登记。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..config import settings
from ..models import MediaAsset

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

ALLOWED_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
    ".mp4", ".avi", ".mov", ".mkv",
    ".tiff", ".tif", ".raw", ".bin", ".json", ".log", ".csv",
}


def _safe_name(name: str) -> str:
    keep = [c for c in name if c.isalnum() or c in "._-"]
    return "".join(keep)[-120:] or "file"


def save_media(
    db: Session,
    *,
    content: bytes,
    filename: str,
    asset_type: str,
    category: str,
    task_id: int | None = None,
    device_id: int | None = None,
    captured_at: datetime | None = None,
    remark: str | None = None,
) -> MediaAsset:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件类型：{suffix or '(无扩展名)'}")

    limit = settings.max_upload_mb * 1024 * 1024
    if len(content) > limit:
        raise ValueError(f"文件超过 {settings.max_upload_mb} MB 上限")

    now = datetime.now(TZ)
    rel_dir = Path(category) / now.strftime("%Y%m%d")
    target_dir = settings.media_root / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = now.strftime("%H%M%S_%f")[:-3]
    file_name = f"{stamp}_{_safe_name(filename)}"
    target = target_dir / file_name
    target.write_bytes(content)

    asset = MediaAsset(
        asset_type=asset_type,
        category=category,
        task_id=task_id,
        device_id=device_id,
        file_path=str(Path(rel_dir) / file_name).replace("\\", "/"),
        file_name=file_name,
        mime_type=_guess_mime(suffix),
        file_size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        captured_at=captured_at or now,
        remark=remark,
    )
    db.add(asset)
    db.flush()
    return asset


def _guess_mime(suffix: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".raw": "application/octet-stream",
        ".bin": "application/octet-stream",
        ".json": "application/json",
        ".log": "text/plain",
        ".csv": "text/csv",
    }.get(suffix, "application/octet-stream")


def absolute_path(asset: MediaAsset) -> Path:
    return settings.media_root / asset.file_path


def asset_to_dict(asset: MediaAsset, url_prefix: str = "/api/v1/media") -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "category": asset.category,
        "task_id": asset.task_id,
        "device_id": asset.device_id,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "file_size_bytes": asset.file_size_bytes,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "checksum_sha256": asset.checksum_sha256,
        "captured_at": asset.captured_at,
        "created_at": asset.created_at,
        "url": f"{url_prefix}/{asset.id}/content",
    }
