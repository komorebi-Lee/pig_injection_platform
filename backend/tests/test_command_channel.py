"""指令通道测试：幂等、审计、错误归一。

这些用例需要 PostgreSQL 可达；不可达时自动 skip。
每个用例结束后 rollback，不污染开发库。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ControlCommand, Device
from app.services import commands
from app.services.arm_gateway import MockArmAdapter


@pytest.fixture()
def db_session(require_db):
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def device(db_session) -> Device:
    row = db_session.scalar(select(Device).where(Device.device_type == "arm").order_by(Device.id))
    if row is None:
        pytest.skip("台账中没有机械臂设备，请先跑 scripts/init_db.py")
    return row


def test_dispatch_writes_audit_row(db_session, device) -> None:
    adapter = MockArmAdapter(obstacle_probability=0.0, seed=7)
    rid = str(uuid.uuid4())
    result = commands.dispatch(
        db_session,
        device=device,
        command_type="jog",
        payload={"axis": "j1", "step": 1.0},
        call=lambda: adapter.jog({"axis": "j1", "direction": 1, "step": 1.0, "speed_pct": 50}),
        request_id=rid,
    )
    assert result.accepted is True
    assert result.result == "success"
    assert result.arm_command_id is not None
    assert result.duration_ms >= 0

    row = db_session.scalar(select(ControlCommand).where(ControlCommand.request_id == uuid.UUID(rid)))
    assert row is not None
    assert row.command_type == "jog"
    assert row.payload == {"axis": "j1", "step": 1.0}
    assert row.response is not None
    assert row.completed_at is not None


def test_same_request_id_does_not_reach_the_arm_twice(db_session, device) -> None:
    """核心安全断言：重复 request_id 只能让机械臂动一次。"""
    adapter = MockArmAdapter(obstacle_probability=0.0, seed=7)
    rid = str(uuid.uuid4())
    calls: list[int] = []

    def call() -> dict:
        calls.append(1)
        return adapter.jog({"axis": "j1", "direction": 1, "step": 1.0, "speed_pct": 100})

    first = commands.dispatch(
        db_session, device=device, command_type="jog", payload={}, call=call, request_id=rid
    )
    second = commands.dispatch(
        db_session, device=device, command_type="jog", payload={}, call=call, request_id=rid
    )

    assert len(calls) == 1, "机械臂被调用了两次，幂等失效"
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.arm_command_id == first.arm_command_id
    assert "重复" in (second.message or "")


def test_non_uuid_request_id_is_still_idempotent(db_session, device) -> None:
    adapter = MockArmAdapter(obstacle_probability=0.0, seed=7)
    calls: list[int] = []

    def call() -> dict:
        calls.append(1)
        return adapter.stop()

    for _ in range(2):
        commands.dispatch(
            db_session,
            device=device,
            command_type="stop",
            payload={},
            call=call,
            request_id="frontend-generated-key-001",
        )
    assert len(calls) == 1


def test_gateway_error_is_recorded_and_translated(db_session, device) -> None:
    adapter = MockArmAdapter(obstacle_probability=0.0, seed=7)
    adapter.estop()

    with pytest.raises(commands.CommandRejected) as excinfo:
        commands.dispatch(
            db_session,
            device=device,
            command_type="jog",
            payload={},
            call=lambda: adapter.jog({"axis": "j1", "direction": 1, "step": 1.0}),
            request_id=str(uuid.uuid4()),
        )
    assert excinfo.value.code == "estop_active"
    assert excinfo.value.status == 409

    row = db_session.scalars(select(ControlCommand).order_by(ControlCommand.id.desc())).first()
    assert row is not None
    assert row.result == "failed"
    assert row.error_code == "estop_active"
    assert row.reject_reason


def test_unexpected_exception_is_wrapped(db_session, device) -> None:
    def boom() -> dict:
        raise RuntimeError("驱动层崩了")

    with pytest.raises(commands.CommandRejected) as excinfo:
        commands.dispatch(
            db_session,
            device=device,
            command_type="home",
            payload={},
            call=boom,
            request_id=str(uuid.uuid4()),
        )
    assert excinfo.value.code == "internal_error"
    assert excinfo.value.status == 500
