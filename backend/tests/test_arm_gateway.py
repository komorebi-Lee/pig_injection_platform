"""Mock 机械臂行为测试。

这些用例把"安全语义"固化成测试：急停优先、故障拒动、注射互斥、
热成像必带测温参数。换真实机械臂后，这些语义仍然必须成立。
"""

from __future__ import annotations

import pytest

from app.services.arm_gateway import ArmGatewayError, MockArmAdapter


@pytest.fixture()
def arm() -> MockArmAdapter:
    return MockArmAdapter(obstacle_probability=0.0, seed=42)


def test_status_shape(arm: MockArmAdapter) -> None:
    status = arm.get_status()
    assert status["device_online"] is True
    assert status["control_mode"] == "idle"
    assert len(status["joint_angles_deg"]) == 6
    assert {"x", "y", "z"} <= set(status["tcp_pose"])
    assert {"fx", "fy", "fz"} <= set(status["tcp_force"])
    assert status["estop_pressed"] is False
    assert status["safety_state"] == "normal"


def test_jog_moves_axis_and_switches_to_manual(arm: MockArmAdapter) -> None:
    before = arm.get_status()["joint_angles_deg"][0]
    result = arm.jog({"axis": "j1", "direction": 1, "step": 5.0, "speed_pct": 100})
    assert result["accepted"] is True
    after = arm.get_status()
    assert after["joint_angles_deg"][0] == pytest.approx(before + 5.0, abs=1e-6)
    assert after["control_mode"] == "manual"
    assert after["servo_power_on"] is True


def test_jog_rejects_unknown_axis(arm: MockArmAdapter) -> None:
    with pytest.raises(ArmGatewayError) as excinfo:
        arm.jog({"axis": "j9", "direction": 1, "step": 1.0})
    assert excinfo.value.code == "bad_axis"
    assert excinfo.value.status == 400


def test_estop_blocks_all_motion(arm: MockArmAdapter) -> None:
    arm.estop()
    status = arm.get_status()
    assert status["control_mode"] == "estop"
    assert status["estop_pressed"] is True
    assert status["servo_power_on"] is False

    for call in (
        lambda: arm.jog({"axis": "j1", "direction": 1, "step": 1.0}),
        lambda: arm.move_pose({"pose": {"x": 1, "y": 2, "z": 3}}),
        lambda: arm.move_joint({"joint_angles_deg": [1, 2, 3, 4, 5, 6]}),
        lambda: arm.home(),
        lambda: arm.inject_start({"task_no": "T1"}),
    ):
        with pytest.raises(ArmGatewayError) as excinfo:
            call()
        assert excinfo.value.code == "estop_active"
        assert excinfo.value.status == 409


def test_estop_is_idempotent(arm: MockArmAdapter) -> None:
    for _ in range(3):
        assert arm.estop()["estop_pressed"] is True
    assert arm.get_status()["control_mode"] == "estop"


def test_estop_reset_restores_operability(arm: MockArmAdapter) -> None:
    arm.estop()
    arm.estop_reset()
    status = arm.get_status()
    assert status["estop_pressed"] is False
    assert status["control_mode"] == "idle"
    arm.jog({"axis": "j1", "direction": -1, "step": 1.0})
    assert arm.get_status()["control_mode"] == "manual"


def test_mode_switch_rejected_while_estop(arm: MockArmAdapter) -> None:
    arm.estop()
    with pytest.raises(ArmGatewayError) as excinfo:
        arm.set_mode("auto")
    assert excinfo.value.code == "estop_active"
    arm.set_mode("idle")  # idle 始终允许


def test_injection_is_mutually_exclusive(arm: MockArmAdapter) -> None:
    first = arm.inject_start({"task_no": "T1", "dose_ml": 2.0})
    assert first["accepted"] is True
    assert first["phase"] == "locating"
    with pytest.raises(ArmGatewayError) as excinfo:
        arm.inject_start({"task_no": "T2"})
    assert excinfo.value.code == "injection_busy"
    assert excinfo.value.status == 409


def test_injection_abort_sets_terminal_phase(arm: MockArmAdapter) -> None:
    arm.inject_start({"task_no": "T1"})
    result = arm.inject_abort("T1", reason="operator_abort")
    assert result["aborted"] is True
    assert arm.get_status()["injection"]["phase"] == "aborted"
    # 终态后允许新的注射
    assert arm.inject_start({"task_no": "T2"})["accepted"] is True


def test_thermal_contains_measurement_parameters(arm: MockArmAdapter) -> None:
    thermal = arm.get_thermal()
    for key in ("emissivity", "distance_m", "reflected_temp_c", "temp_range_min_c", "temp_range_max_c"):
        assert thermal[key] is not None, f"缺少测温参数 {key}"
    for key in ("body_temp_c", "injected_site_temp_c", "ambient_temp_c"):
        assert isinstance(thermal[key], float)
    assert len(thermal["rois"]) >= 1
    assert {"roi_name", "geometry", "temp_avg_c"} <= set(thermal["rois"][0])


def test_obstacle_toggle(arm: MockArmAdapter) -> None:
    assert arm.set_obstacle_enabled(False)["enabled"] is False
    assert arm.get_obstacle_status()["enabled"] is False
    assert arm.set_obstacle_enabled(True)["enabled"] is True


def test_obstacle_event_is_reported_once(arm: MockArmAdapter) -> None:
    noisy = MockArmAdapter(obstacle_probability=1.0, seed=1)
    status = noisy.get_status()
    assert status["obstacle_distance_mm"] is not None
    first = noisy.get_obstacle_status()
    assert first["active"] is True
    assert first["event"]["distance_mm"] > 0
    assert first["event"]["action_taken"] in {"slowdown", "stop"}
