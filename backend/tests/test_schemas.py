"""请求模型校验测试：确保前端传错参数时能被挡在 400/422，而不是打到机械臂。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    DeviceRequest,
    InjectionCreateRequest,
    JogRequest,
    ModeRequest,
    MovePoseRequest,
    ObstacleToggleRequest,
)


def test_jog_requires_known_axis() -> None:
    JogRequest(axis="j1")
    with pytest.raises(ValidationError):
        JogRequest(axis="j9")


def test_jog_speed_and_step_bounds() -> None:
    with pytest.raises(ValidationError):
        JogRequest(axis="x", speed_pct=0)
    with pytest.raises(ValidationError):
        JogRequest(axis="x", speed_pct=101)
    with pytest.raises(ValidationError):
        JogRequest(axis="x", step=0)
    JogRequest(axis="x", speed_pct=1, step=0.001)


def test_jog_direction_only_plus_minus_one() -> None:
    JogRequest(axis="x", direction=1)
    JogRequest(axis="x", direction=-1)
    with pytest.raises(ValidationError):
        JogRequest(axis="x", direction=2)


def test_device_request_allows_empty_body() -> None:
    assert DeviceRequest().request_id is None
    assert DeviceRequest(request_id="abc").request_id == "abc"


def test_mode_request_only_accepts_known_modes() -> None:
    for mode in ("idle", "manual", "auto"):
        assert ModeRequest(mode=mode).mode == mode
    with pytest.raises(ValidationError):
        ModeRequest(mode="turbo")


def test_move_pose_requires_full_xyz() -> None:
    MovePoseRequest(pose={"x": 1, "y": 2, "z": 3})
    with pytest.raises(ValidationError):
        MovePoseRequest(pose={"x": 1, "y": 2})


def test_obstacle_toggle_requires_bool() -> None:
    assert ObstacleToggleRequest(enabled=True).enabled is True
    with pytest.raises(ValidationError):
        ObstacleToggleRequest(enabled="maybe")


def test_injection_dose_and_depth_bounds() -> None:
    InjectionCreateRequest(dose_target_ml=2.0, depth_mm=3.5)
    with pytest.raises(ValidationError):
        InjectionCreateRequest(dose_target_ml=-1)
    with pytest.raises(ValidationError):
        InjectionCreateRequest(depth_mm=0)
    with pytest.raises(ValidationError):
        InjectionCreateRequest(target_confidence=1.5)


def test_injection_defaults() -> None:
    payload = InjectionCreateRequest()
    assert payload.mode == "auto"
    assert payload.auto_start is True
    assert payload.target_source == "guardrail_camera"
