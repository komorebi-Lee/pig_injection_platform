"""台账接口：栏位、猪只、操作员。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Operator, Pen, Pig
from ..schemas import PenIn, PenOut, PigIn, PigOut

router = APIRouter(tags=["台账"])


# --------------------------- 栏位 ---------------------------
@router.get("/pens", summary="栏位列表")
def list_pens(db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(Pen).order_by(Pen.id)))
    return {"ok": True, "count": len(rows), "items": [PenOut.model_validate(r) for r in rows]}


@router.post("/pens", summary="新增栏位", status_code=201)
def create_pen(payload: PenIn, db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(Pen).where(Pen.pen_code == payload.pen_code)):
        raise HTTPException(status_code=409, detail=f"栏位编号已存在：{payload.pen_code}")
    pen = Pen(**payload.model_dump())
    db.add(pen)
    db.commit()
    return {"ok": True, "data": PenOut.model_validate(pen)}


@router.put("/pens/{pen_id}", summary="修改栏位")
def update_pen(pen_id: int, payload: PenIn, db: Session = Depends(get_db)) -> dict:
    pen = db.get(Pen, pen_id)
    if pen is None:
        raise HTTPException(status_code=404, detail="栏位不存在")
    for key, value in payload.model_dump().items():
        setattr(pen, key, value)
    db.commit()
    return {"ok": True, "data": PenOut.model_validate(pen)}


@router.delete("/pens/{pen_id}", summary="删除栏位")
def delete_pen(pen_id: int, db: Session = Depends(get_db)) -> dict:
    pen = db.get(Pen, pen_id)
    if pen is None:
        raise HTTPException(status_code=404, detail="栏位不存在")
    db.delete(pen)
    db.commit()
    return {"ok": True, "deleted": pen_id}


# --------------------------- 猪只 ---------------------------
@router.get("/pigs", summary="猪只档案列表")
def list_pigs(
    pen_id: int | None = Query(default=None),
    ear_tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Pig).order_by(Pig.id)
    if pen_id is not None:
        stmt = stmt.where(Pig.pen_id == pen_id)
    if ear_tag:
        stmt = stmt.where(Pig.ear_tag == ear_tag)
    rows = list(db.scalars(stmt))
    return {"ok": True, "count": len(rows), "items": [PigOut.model_validate(r) for r in rows]}


@router.post("/pigs", summary="新增猪只", status_code=201)
def create_pig(payload: PigIn, db: Session = Depends(get_db)) -> dict:
    if payload.ear_tag and db.scalar(select(Pig).where(Pig.ear_tag == payload.ear_tag)):
        raise HTTPException(status_code=409, detail=f"耳标已存在：{payload.ear_tag}")
    pig = Pig(**payload.model_dump())
    db.add(pig)
    db.commit()
    return {"ok": True, "data": PigOut.model_validate(pig)}


@router.put("/pigs/{pig_id}", summary="修改猪只档案")
def update_pig(pig_id: int, payload: PigIn, db: Session = Depends(get_db)) -> dict:
    pig = db.get(Pig, pig_id)
    if pig is None:
        raise HTTPException(status_code=404, detail="猪只不存在")
    for key, value in payload.model_dump().items():
        setattr(pig, key, value)
    db.commit()
    return {"ok": True, "data": PigOut.model_validate(pig)}


@router.delete("/pigs/{pig_id}", summary="删除猪只档案")
def delete_pig(pig_id: int, db: Session = Depends(get_db)) -> dict:
    pig = db.get(Pig, pig_id)
    if pig is None:
        raise HTTPException(status_code=404, detail="猪只不存在")
    db.delete(pig)
    db.commit()
    return {"ok": True, "deleted": pig_id}


# --------------------------- 操作员 ---------------------------
@router.get("/operators", summary="操作员列表")
def list_operators(db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(Operator).order_by(Operator.id)))
    return {
        "ok": True,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "username": r.username,
                "display_name": r.display_name,
                "role": r.role,
                "active": r.active,
                "last_login_at": r.last_login_at,
            }
            for r in rows
        ],
    }


@router.post("/operators", summary="新增操作员", status_code=201)
def create_operator(payload: dict, db: Session = Depends(get_db)) -> dict:
    username = str(payload.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username 必填")
    if db.scalar(select(Operator).where(Operator.username == username)):
        raise HTTPException(status_code=409, detail=f"用户名已存在：{username}")
    operator = Operator(
        username=username,
        display_name=payload.get("display_name"),
        role=str(payload.get("role") or "operator"),
        active=bool(payload.get("active", True)),
    )
    db.add(operator)
    db.commit()
    return {"ok": True, "data": {"id": operator.id, "username": operator.username}}
