"""告警产生与状态流转。所有告警统一从这里写，保证编号与去重规则一致。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alarm

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

# 同类告警在窗口内只记一条，避免机械臂持续报同一个错把表刷爆
DEDUP_WINDOW_SECONDS = 60


def _today_prefix() -> str:
    return datetime.now(TZ).strftime("AL%Y%m%d")


def raise_alarm(
    db: Session,
    *,
    level: str,
    category: str,
    title: str,
    message: str | None = None,
    code: str | None = None,
    value: float | Decimal | None = None,
    threshold: float | Decimal | None = None,
    device_id: int | None = None,
    task_id: int | None = None,
    asset_id: int | None = None,
    raw: dict[str, Any] | None = None,
    dedup_key: str | None = None,
) -> Alarm | None:
    """写一条告警。

    dedup_key 相同且同一条告警在 DEDUP_WINDOW_SECONDS 内已存在时，只更新 value，
    不新增记录。返回 None 表示被去重。
    """
    key = dedup_key or f"{category}:{code or title}"
    since = datetime.now(TZ) - timedelta(seconds=DEDUP_WINDOW_SECONDS)
    existing = db.scalar(
        select(Alarm)
        .where(Alarm.status == "active")
        .where(Alarm.category == category)
        .where(Alarm.code.is_not_distinct_from(code))
        .where(Alarm.title == title)
        .where(Alarm.device_id.is_not_distinct_from(device_id))
        .where(Alarm.created_at >= since)
        .order_by(Alarm.id.desc())
        .limit(1)
    )
    if existing is not None:
        existing.message = message or existing.message
        if value is not None:
            existing.value = Decimal(str(value))
        existing.raw = raw or existing.raw
        logger.debug("告警去重命中：%s", key)
        return None

    alarm = Alarm(
        alarm_no="PENDING",
        level=level,
        category=category,
        title=title,
        message=message,
        code=code,
        value=None if value is None else Decimal(str(value)),
        threshold=None if threshold is None else Decimal(str(threshold)),
        device_id=device_id,
        task_id=task_id,
        asset_id=asset_id,
        status="active",
        raw=raw,
    )
    db.add(alarm)
    db.flush()
    alarm.alarm_no = f"{_today_prefix()}-{alarm.id:04d}"
    return alarm


def acknowledge(db: Session, alarm_id: int, operator_id: int | None) -> Alarm | None:
    alarm = db.get(Alarm, alarm_id)
    if alarm is None or alarm.status != "active":
        return None
    alarm.status = "acknowledged"
    alarm.acknowledged_by = operator_id
    alarm.acknowledged_at = datetime.now(TZ)
    return alarm


def clear(db: Session, alarm_id: int) -> Alarm | None:
    alarm = db.get(Alarm, alarm_id)
    if alarm is None:
        return None
    alarm.status = "cleared"
    alarm.cleared_at = datetime.now(TZ)
    return alarm


def clear_by_category(db: Session, category: str, code: str | None = None, device_id: int | None = None) -> int:
    """条件已恢复时批量关闭活动告警（例如急停被复位）。"""
    stmt = select(Alarm).where(Alarm.status.in_(("active", "acknowledged"))).where(Alarm.category == category)
    if code is not None:
        stmt = stmt.where(Alarm.code == code)
    if device_id is not None:
        stmt = stmt.where(Alarm.device_id == device_id)
    now = datetime.now(TZ)
    count = 0
    for alarm in db.scalars(stmt):
        alarm.status = "cleared"
        alarm.cleared_at = now
        count += 1
    return count
