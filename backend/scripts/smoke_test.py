"""端到端冒烟测试：把后端所有主要接口按真实使用顺序打一遍。

用法：
    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py --base http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import httpx

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append((name, PASS if condition else FAIL, detail))
    flag = "[OK]  " if condition else "[FAIL]"
    print(f"{flag} {name}{('  -> ' + detail) if detail else ''}")
    return condition


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    api = f"{base}/api/v1"

    with httpx.Client(timeout=30.0) as client:
        # 1) 健康检查
        r = client.get(f"{api}/health")
        health = r.json()
        check("GET /health 返回 200", r.status_code == 200, f"status={r.status_code}")
        check("数据库连通", health.get("database") == "ok", str(health.get("database")))
        check("机械臂驱动为 mock", health.get("arm_driver") == "mock", str(health.get("arm_driver")))
        check("遥测轮询在跑", int(health.get("telemetry_cycles") or 0) >= 0, f"cycles={health.get('telemetry_cycles')}")

        # 2) 概览
        r = client.get(f"{api}/overview")
        data = r.json().get("data", {})
        check("GET /overview 有栏位数据", data.get("pens", 0) >= 1, json.dumps(data, ensure_ascii=False)[:120])

        # 3) 设备与栏位台账
        r = client.get(f"{api}/devices")
        devices = r.json().get("items", [])
        check("GET /devices 返回设备", len(devices) >= 4, f"count={len(devices)}")
        r = client.get(f"{api}/pens")
        pens = r.json().get("items", [])
        check("GET /pens 返回栏位", len(pens) >= 1, f"count={len(pens)}")
        r = client.get(f"{api}/pigs")
        pigs = r.json().get("items", [])
        check("GET /pigs 返回猪只", len(pigs) >= 2, f"count={len(pigs)}")

        # 4) 机械臂实时状态
        r = client.get(f"{api}/arm/status")
        status = r.json()
        check("GET /arm/status 返回 200", r.status_code == 200, f"status={r.status_code}")
        check("含 6 轴关节角", isinstance(status.get("joint_angles_deg"), list) and len(status["joint_angles_deg"]) == 6)
        check("含 TCP 位姿", isinstance(status.get("tcp_pose"), dict) and "x" in status["tcp_pose"])
        check("含安全状态字段", "safety_state" in status)

        # 5) 手动控制：点动 + 幂等验证
        rid = str(uuid.uuid4())
        body = {"request_id": rid, "axis": "j1", "direction": 1, "step": 2.0, "speed_pct": 20}
        r1 = client.post(f"{api}/arm/jog", json=body)
        check("POST /arm/jog 成功", r1.status_code == 200 and r1.json().get("accepted"), str(r1.json())[:120])
        r2 = client.post(f"{api}/arm/jog", json=body)
        replay = r2.json()
        check(
            "幂等：相同 request_id 不重复下发",
            r2.status_code == 200 and "重复" in str(replay.get("message", "")),
            str(replay.get("message")),
        )

        # 6) 手动控制：回零 / 模式切换 / 停止
        for path, payload in (
            ("/arm/mode", {"mode": "manual"}),
            ("/arm/home", {}),
            ("/arm/stop", {}),
        ):
            r = client.post(f"{api}{path}", json={**payload, "request_id": str(uuid.uuid4())})
            check(f"POST {path} 成功", r.status_code == 200, f"status={r.status_code}")

        # 7) 避障
        r = client.get(f"{api}/arm/obstacle/status")
        check("GET /arm/obstacle/status 成功", r.status_code == 200, str(r.json())[:100])
        r = client.post(
            f"{api}/arm/obstacle/enabled",
            json={"enabled": True, "request_id": str(uuid.uuid4())},
        )
        check("POST /arm/obstacle/enabled 成功", r.status_code == 200, f"status={r.status_code}")

        # 8) 热成像：直读 + 历史
        r = client.get(f"{api}/arm/thermal/latest")
        thermal = r.json().get("data", {})
        check("GET /arm/thermal/latest 有体温", thermal.get("body_temp_c") is not None, f"body={thermal.get('body_temp_c')}")
        check("含测温参数 EMS", thermal.get("emissivity") is not None)
        r = client.get(f"{api}/arm/thermal/history", params={"limit": 5})
        check("GET /arm/thermal/history 有落库记录", r.json().get("count", 0) >= 1, f"count={r.json().get('count')}")

        # 9) 自动注射全流程
        r = client.post(
            f"{api}/injection/tasks",
            json={
                "pen_id": pens[0]["id"],
                "pig_id": pigs[0]["id"],
                "mode": "auto",
                "dose_target_ml": 2.0,
                "depth_mm": 3.5,
                "drug_name": "猪瘟疫苗",
                "drug_batch_no": "B20260917",
                "needle_id": "N-001",
                "auto_start": True,
                "request_id": str(uuid.uuid4()),
            },
        )
        check("POST /injection/tasks 创建成功", r.status_code == 201, f"status={r.status_code} {str(r.json())[:100]}")
        task = r.json()["data"]
        task_id = task["id"]
        check("任务号已生成", bool(task.get("task_no")), str(task.get("task_no")))

        # 等待流程跑完
        final = {}
        for _ in range(40):
            time.sleep(0.5)
            detail = client.get(f"{api}/injection/tasks/{task_id}").json()
            final = detail["data"]
            if final["status"] in ("completed", "failed", "aborted"):
                break
        check("注射任务执行完成", final.get("status") == "completed", f"status={final.get('status')} reason={final.get('fail_reason')}")
        check("记录了总耗时", final.get("duration_ms") is not None, f"duration_ms={final.get('duration_ms')}")
        check("记录了阶段耗时", isinstance(final.get("phase_durations_ms"), dict), str(final.get("phase_durations_ms")))
        detail = client.get(f"{api}/injection/tasks/{task_id}").json()
        events = detail.get("events", [])
        check("生成了过程事件时间线", len(events) >= 5, f"events={len(events)}")
        check(
            "事件含各阶段",
            {"locating", "aligning", "inserting", "injecting", "retracting"}.issubset(
                {e.get("phase") for e in events if e.get("phase")}
            ),
            str(sorted({e.get("phase") for e in events if e.get("phase")})),
        )

        # 10) 查询与报表
        r = client.get(f"{api}/injection/tasks", params={"limit": 10})
        check("GET /injection/tasks 列表", r.json().get("page", {}).get("total", 0) >= 1)
        r = client.get(f"{api}/reports/injections/daily", params={"days": 7})
        check("GET /reports/injections/daily", r.status_code == 200 and len(r.json().get("items", [])) >= 1)
        r = client.get(f"{api}/reports/injections/phase-durations")
        check("GET /reports/injections/phase-durations", r.status_code == 200 and len(r.json().get("items", [])) >= 5,
              str(r.json().get("items"))[:160])
        r = client.get(f"{api}/reports/pig-production")
        check("GET /reports/pig-production", r.status_code == 200)
        r = client.get(f"{api}/reports/thermal/trend")
        check("GET /reports/thermal/trend", r.status_code == 200 and r.json().get("count", 0) >= 1)

        # 11) 遥测历史
        r = client.get(f"{api}/arm/status/history", params={"limit": 10})
        check("GET /arm/status/history 有采样", r.json().get("count", 0) >= 1, f"count={r.json().get('count')}")

        # 12) 指令审计
        r = client.get(f"{api}/arm/commands", params={"limit": 20})
        cmds = r.json().get("items", [])
        check("GET /arm/commands 有审计记录", len(cmds) >= 4, f"count={len(cmds)}")
        check("指令记录含耗时", any(c.get("duration_ms") is not None for c in cmds))

        # 13) 告警
        r = client.get(f"{api}/alarms")
        check("GET /alarms 成功", r.status_code == 200, f"total={r.json().get('page', {}).get('total')}")

        # 14) 急停链路（放到最后，避免影响前面流程）
        r = client.post(f"{api}/arm/estop", json={"request_id": str(uuid.uuid4())})
        check("POST /arm/estop 成功", r.status_code == 200 and r.json().get("accepted"), str(r.json())[:100])
        r = client.get(f"{api}/arm/status")
        check("急停后状态为 estop", r.json().get("control_mode") == "estop", str(r.json().get("control_mode")))
        r = client.post(
            f"{api}/arm/jog",
            json={"axis": "j1", "direction": 1, "step": 1, "request_id": str(uuid.uuid4())},
        )
        check("急停后运动指令被拒绝", r.status_code == 409, f"status={r.status_code} {str(r.json())[:90]}")
        r = client.post(f"{api}/arm/estop/reset", json={"request_id": str(uuid.uuid4())})
        check("POST /arm/estop/reset 成功", r.status_code == 200, f"status={r.status_code}")

    print()
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = [(n, d) for n, s, d in results if s == FAIL]
    print(f"===== {passed}/{len(results)} 通过 =====")
    for name, detail in failed:
        print(f"  失败：{name}  {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
