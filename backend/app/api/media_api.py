"""媒体文件接口：上传、列表、下载。前端只认 media id，不接触服务器路径。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MediaAsset
from ..schemas import Page
from ..services import media

router = APIRouter(prefix="/media", tags=["媒体"])


@router.post("", summary="上传媒体文件（图片/视频/温度数据）", status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    category: str = Form(default="snapshot"),
    asset_type: str = Form(default="image"),
    task_id: int | None = Form(default=None),
    device_id: int | None = Form(default=None),
    remark: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    content = await file.read()
    try:
        asset = media.save_media(
            db,
            content=content,
            filename=file.filename or "upload.bin",
            asset_type=asset_type,
            category=category,
            task_id=task_id,
            device_id=device_id,
            remark=remark,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"ok": True, "data": media.asset_to_dict(asset)}


@router.get("", summary="媒体列表")
def list_media(
    category: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(MediaAsset).order_by(MediaAsset.id.desc())
    count_stmt = select(func.count()).select_from(MediaAsset)
    for column, value in (
        (MediaAsset.category, category),
        (MediaAsset.task_id, task_id),
        (MediaAsset.asset_type, asset_type),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    return {
        "ok": True,
        "page": Page(total=int(db.scalar(count_stmt) or 0), limit=limit, offset=offset),
        "items": [media.asset_to_dict(r) for r in rows],
    }


@router.get("/{asset_id}", summary="媒体元数据")
def media_meta(asset_id: int, db: Session = Depends(get_db)) -> dict:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="媒体不存在")
    return {"ok": True, "data": media.asset_to_dict(asset)}


@router.get("/{asset_id}/content", summary="媒体内容（图片/视频二进制流）")
def media_content(asset_id: int, db: Session = Depends(get_db)) -> FileResponse:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="媒体不存在")
    path = media.absolute_path(asset)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="媒体文件已丢失")
    return FileResponse(path, media_type=asset.mime_type or "application/octet-stream", filename=asset.file_name)
