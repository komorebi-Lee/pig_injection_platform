"""自动注射任务接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import InjectionEvent, InjectionTask, MediaAsset
from ..schemas import (
    InjectionAbortRequest,
    InjectionCreateRequest,
    InjectionEventOut,
    InjectionTaskOut,
    Page,
)
from ..services import commands, injection

router = APIRouter(prefix="/injection", tags=["自动注射"])


@router.post("/tasks", summary="创建注射任务（可选立即执行）", status_code=201)
def create_task(payload: InjectionCreateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    device = commands.resolve_device(db, payload.device_code)
    task = injection.create_task(
        db,
        device=device,
        pen_id=payload.pen_id,
        pig_id=payload.pig_id,
        operator_id=payload.operator_id,
        operator_name=payload.operator_name,
        mode=payload.mode,
        dose_target_ml=payload.dose_target_ml,
        depth_mm=payload.depth_mm,
        drug_name=payload.drug_name,
        drug_batch_no=payload.drug_batch_no,
        needle_id=payload.needle_id,
        target_point_base=payload.target_point_base,
        target_point_pixel=payload.target_point_pixel,
        target_source=payload.target_source,
        target_confidence=payload.target_confidence,
        batch_no=payload.batch_no,
    )
    db.commit()
    task_id = task.id
    started = False
    if payload.auto_start:
        injection.start_task(task_id)
        started = True
    return {
        "ok": True,
        "started": started,
        "data": InjectionTaskOut.model_validate(db.get(InjectionTask, task_id)),
    }


@router.post("/tasks/{task_id}/start", summary="启动已创建的注射任务")
def start_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(InjectionTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in {"created", "queued", "failed", "aborted"}:
        raise HTTPException(status_code=409, detail=f"当前状态 {task.status} 不能启动")
    injection.start_task(task_id)
    return {"ok": True, "task_id": task_id, "status": "queued"}


@router.post("/tasks/{task_id}/abort", summary="中止注射任务")
def abort_task(task_id: int, payload: InjectionAbortRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        result = injection.abort_task(task_id, payload.reason)
    except injection.InjectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return {"ok": True, "data": result}


@router.get("/tasks", summary="注射任务列表")
def list_tasks(
    status: str | None = Query(default=None),
    pen_id: int | None = Query(default=None),
    pig_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(InjectionTask).order_by(InjectionTask.id.desc())
    count_stmt = select(func.count()).select_from(InjectionTask)
    if status:
        stmt = stmt.where(InjectionTask.status == status)
        count_stmt = count_stmt.where(InjectionTask.status == status)
    if pen_id is not None:
        stmt = stmt.where(InjectionTask.pen_id == pen_id)
        count_stmt = count_stmt.where(InjectionTask.pen_id == pen_id)
    if pig_id is not None:
        stmt = stmt.where(InjectionTask.pig_id == pig_id)
        count_stmt = count_stmt.where(InjectionTask.pig_id == pig_id)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    total = int(db.scalar(count_stmt) or 0)
    return {
        "ok": True,
        "page": Page(total=total, limit=limit, offset=offset),
        "items": [InjectionTaskOut.model_validate(r) for r in rows],
    }


@router.get("/tasks/active", summary="正在执行的注射任务")
def active_tasks(db: Session = Depends(get_db)) -> dict:
    ids = injection.active_task_ids()
    rows = list(db.scalars(select(InjectionTask).where(InjectionTask.id.in_(ids)))) if ids else []
    return {"ok": True, "count": len(rows), "items": [InjectionTaskOut.model_validate(r) for r in rows]}


@router.get("/tasks/{task_id}", summary="注射任务详情")
def task_detail(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(InjectionTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = list(
        db.scalars(select(InjectionEvent).where(InjectionEvent.task_id == task_id).order_by(InjectionEvent.id))
    )
    assets = list(db.scalars(select(MediaAsset).where(MediaAsset.task_id == task_id).order_by(MediaAsset.id)))
    return {
        "ok": True,
        "data": InjectionTaskOut.model_validate(task),
        "events": [InjectionEventOut.model_validate(e) for e in events],
        "media": [
            {
                "id": a.id,
                "asset_type": a.asset_type,
                "category": a.category,
                "file_name": a.file_name,
                "mime_type": a.mime_type,
                "url": f"/api/v1/media/{a.id}/content",
                "captured_at": a.captured_at,
            }
            for a in assets
        ],
    }


@router.get("/tasks/{task_id}/events", summary="注射过程时间线")
def task_events(
    task_id: int,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(InjectionTask, task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = list(
        db.scalars(
            select(InjectionEvent)
            .where(InjectionEvent.task_id == task_id)
            .order_by(InjectionEvent.id)
            .limit(limit)
        )
    )
    return {"ok": True, "count": len(rows), "items": [InjectionEventOut.model_validate(r) for r in rows]}
