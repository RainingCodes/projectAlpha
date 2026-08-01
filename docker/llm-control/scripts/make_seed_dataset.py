#!/usr/bin/env python3
"""Generate the reproducible UMDL v0.1 seed dataset.

The generator creates canonical mission groups first and then produces six language
styles per group. All paraphrases sharing a group_id remain in the same split.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SEED = 20260801
SCHEMA_VERSION = "umdl/0.1"
STYLES = [
    ("ko", "KO_STANDARD"),
    ("ko", "KO_SHORT"),
    ("ko", "KO_FIELD"),
    ("ko", "KO_POLITE"),
    ("en", "EN_STANDARD"),
    ("mixed", "KO_EN_MIXED"),
]

ALL_CAPS = [
    "WAYPOINT_NAVIGATION",
    "DEPTH_CONTROL",
    "STATION_KEEPING",
    "OBSTACLE_AVOIDANCE",
    "RETURN_NAVIGATION",
    "TARGET_DETECTION",
    "AREA_COVERAGE",
    "STRUCTURE_INSPECTION",
    "PIPELINE_FOLLOWING",
    "ENVIRONMENT_SAMPLING",
    "DATA_LOGGING",
    "SURFACE_COMMUNICATION",
]


def stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def task(task_id: str, task_type: str, *, target: dict[str, Any] | None = None,
         pattern: dict[str, Any] | None = None, parameters: dict[str, Any] | None = None,
         completion: str | None = None, report_type: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": task_id, "type": task_type}
    if target is not None:
        out["target"] = target
    if pattern is not None:
        out["pattern"] = pattern
    if parameters is not None:
        out["parameters"] = parameters
    if completion is not None:
        out["completion"] = {"condition": completion}
    if report_type is not None:
        out["report_type"] = report_type
    return out


def base_target(group_id: str, intent: str, priority: str, decision: str,
                required_caps: list[str], sensor_roles: list[str] | None,
                tasks: list[dict[str, Any]], *, constraints: dict[str, Any] | None = None,
                contingencies: list[dict[str, Any]] | None = None,
                requires_clarification: bool = False,
                missing_fields: list[str] | None = None,
                clarification_question: str | None = None,
                safe_fallback: str | None = None,
                reason_code: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": group_id,
        "intent": intent,
        "priority": priority,
        "decision": decision,
        "requirements": {
            "required_capabilities": required_caps,
            "preferred_sensor_roles": sensor_roles or [],
        },
        "tasks": tasks,
        "constraints": constraints or {
            "collision_avoidance": {"enabled": True},
            "energy": {"reserve_policy": "PLATFORM_DEFAULT"},
            "depth": {"mode": "WITHIN_PLATFORM_LIMITS"},
        },
        "contingencies": contingencies or [],
        "requires_clarification": requires_clarification,
        "missing_fields": missing_fields or [],
        "safe_fallback": safe_fallback,
    }
    if clarification_question:
        out["clarification_question"] = clarification_question
    if reason_code:
        out["reason_code"] = reason_code
    return out


def runtime(depth: float, battery: int, visibility: float, current_speed: float,
            current_dir: int, obstacles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "depth_m": depth,
        "battery_pct": battery,
        "visibility_m": visibility,
        "current": {"speed_kn": current_speed, "direction_deg": current_dir},
        "obstacles": obstacles or [],
    }


def command_variants(family: str, p: dict[str, Any]) -> list[str]:
    # Exactly six outputs matching STYLES order.
    if family == "navigation":
        return [
            f"현재 위치에서 {p['bearing']}도 방향으로 {p['distance']}m 이동해.",
            f"{p['bearing']}도, {p['distance']}m 이동.",
            f"방위 {p['bearing']}도로 {p['distance']}미터 전진해.",
            f"현재 위치를 기준으로 {p['bearing']}도 방향으로 {p['distance']}m 이동해 주세요.",
            f"Navigate {p['distance']} meters on bearing {p['bearing']} degrees from the current position.",
            f"현재 위치에서 bearing {p['bearing']}도로 {p['distance']}m navigate 해.",
        ]
    if family == "area_survey":
        return [
            f"{p['region']} 구역을 간격 {p['spacing']}m의 {p['pattern_ko']} 패턴으로 조사해.",
            f"{p['region']} 구역 {p['spacing']}m 간격 전수 조사.",
            f"{p['region']} 전 구역을 {p['pattern_ko']}으로 훑고 빈 구역 없이 기록해.",
            f"{p['region']} 구역을 {p['spacing']}m 간격의 {p['pattern_ko']} 경로로 조사해 주세요.",
            f"Survey region {p['region']} using a {p['pattern_en']} pattern with {p['spacing']} meter spacing.",
            f"{p['region']} region을 {p['spacing']}m spacing의 {p['pattern_en']} pattern으로 survey 해.",
        ]
    if family == "target_search":
        return [
            f"{p['region']}에서 {p['target_ko']}를 찾아 위치를 기록해.",
            f"{p['region']} {p['target_ko']} 수색.",
            f"{p['region']}부터 훑어서 {p['target_ko']} 탐지되면 좌표 남겨.",
            f"{p['region']} 구역에서 {p['target_ko']}를 수색하고 탐지 위치를 기록해 주세요.",
            f"Search region {p['region']} for the {p['target_en']} and record its detected location.",
            f"{p['region']}에서 {p['target_en']} target search 후 위치 log 남겨.",
        ]
    if family == "sar":
        return [
            f"{p['wreck']} 주변의 {p['region']}부터 요구조자 가능성이 높은 구역을 우선 탐색해.",
            f"{p['wreck']} {p['region']} 우선 요구조자 수색.",
            f"{p['wreck']} 주변에서 생존자 있을 만한 {p['region']}부터 먼저 훑어.",
            f"{p['wreck']} 주변의 {p['region']}을 우선하여 요구조자 탐색을 수행해 주세요.",
            f"Prioritize search-and-rescue coverage in {p['region']} around {p['wreck']}.",
            f"{p['wreck']} 주변 {p['region']}부터 priority SAR search 진행해.",
        ]
    if family == "target_inspection":
        return [
            f"{p['object_ko']}의 {p['part_ko']} 상태를 정밀 점검하고 이상 지점을 보고해.",
            f"{p['object_ko']} {p['part_ko']} 정밀 점검.",
            f"{p['object_ko']}의 {p['part_ko']} 가까이서 확인하고 손상 있으면 표시해.",
            f"{p['object_ko']}의 {p['part_ko']}를 정밀 점검한 뒤 이상 지점을 보고해 주세요.",
            f"Inspect the {p['part_en']} of the {p['object_en']} and report any anomalies.",
            f"{p['object_ko']} {p['part_en']}를 close inspection 하고 anomaly report 해.",
        ]
    if family == "pipeline":
        return [
            f"파이프라인 {p['section']} 구간을 따라가며 {p['defect_ko']} 여부를 정밀 점검해.",
            f"파이프라인 {p['section']} {p['defect_ko']} 점검.",
            f"{p['section']} 라인 쭉 따라가면서 {p['defect_ko']} 흔적 있나 스캔해.",
            f"파이프라인 {p['section']} 구간을 추종하며 {p['defect_ko']} 여부를 점검해 주세요.",
            f"Follow pipeline section {p['section']} and inspect it for {p['defect_en']}.",
            f"pipeline {p['section']}를 follow 하면서 {p['defect_en']} inspection 해.",
        ]
    if family == "environment":
        return [
            f"{p['region']}에서 수심 {p['depth']}m를 유지하며 {p['metric_ko']}를 {p['duration']}분 동안 측정해.",
            f"{p['region']} 수심 {p['depth']}m, {p['metric_ko']} {p['duration']}분 측정.",
            f"{p['region']} 들어가서 {p['depth']}미터 유지하고 {p['metric_ko']} 데이터 {p['duration']}분 받아.",
            f"{p['region']}에서 수심 {p['depth']}m를 유지하며 {p['metric_ko']}를 {p['duration']}분간 측정해 주세요.",
            f"Measure {p['metric_en']} in region {p['region']} for {p['duration']} minutes while holding {p['depth']} meters depth.",
            f"{p['region']}에서 depth {p['depth']}m hold 하고 {p['metric_en']}를 {p['duration']}min sampling 해.",
        ]
    if family == "station":
        return [
            f"현재 위치를 {p['duration']}초 동안 유지하고 자세가 불안정하면 보고해.",
            f"현재 위치 {p['duration']}초 유지.",
            f"여기서 {p['duration']}초 버티고 밀리면 바로 상태 알려.",
            f"현재 위치를 {p['duration']}초간 유지하고 자세 불안정 시 보고해 주세요.",
            f"Hold the current position for {p['duration']} seconds and report any loss of stability.",
            f"current position을 {p['duration']}s station keep 하고 instability report 해.",
        ]
    if family == "return":
        return [
            f"배터리가 {p['battery']}% 남았어. 현재 임무를 중단하고 안전 수심으로 올라가 귀환해.",
            f"배터리 {p['battery']}%, 임무 중단 후 귀환.",
            f"전력 {p['battery']}퍼센트야. 작업 접고 안전하게 올라와서 홈으로 복귀해.",
            f"배터리 잔량이 {p['battery']}%이므로 임무를 중단하고 안전하게 귀환해 주세요.",
            f"Battery is at {p['battery']} percent. Abort the current mission, ascend to a safe return depth, and return home.",
            f"battery {p['battery']}%라서 mission abort 후 safe depth로 ascend하고 return home 해.",
        ]
    if family == "obstacle":
        return [
            f"전방 {p['distance']}m에 장애물이 감지됐어. 즉시 회피하고 안전거리를 확보해.",
            f"전방 장애물 {p['distance']}m, 즉시 회피.",
            f"앞 {p['distance']}미터 장애물이다. 바로 피하고 거리 확보해.",
            f"전방 {p['distance']}m 장애물을 즉시 회피하고 안전거리를 확보해 주세요.",
            f"An obstacle is detected {p['distance']} meters ahead. Evade immediately and establish safe clearance.",
            f"front obstacle {p['distance']}m. immediate avoid 후 safe clearance 확보해.",
        ]
    if family == "reject":
        return [
            p["ko_standard"], p["ko_short"], p["ko_field"], p["ko_polite"], p["en"], p["mixed"]
        ]
    if family == "ambiguous":
        return [
            p["ko_standard"], p["ko_short"], p["ko_field"], p["ko_polite"], p["en"], p["mixed"]
        ]
    raise ValueError(f"unknown family: {family}")


def canonical_groups() -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    patterns = [
        ("LAWNMOWER", "잔디깎기", "lawnmower"),
        ("POLYGON", "다각형", "polygon"),
        ("SPIRAL", "나선형", "spiral"),
        ("PERIMETER_FOLLOWING", "경계 추종", "perimeter-following"),
    ]
    targets = [
        ("음향 핑거", "acoustic pinger"), ("블랙박스", "black box"),
        ("표식 부이", "marker buoy"), ("유실 장비", "lost equipment"),
        ("잔해 조각", "debris item"), ("비상 비콘", "emergency beacon"),
        ("해저 관측기", "seafloor instrument"), ("잠수 작업 표식", "diver work marker"),
        ("케이블 접속함", "cable junction box"), ("표본 채집기", "sample collector"),
    ]
    inspect_objects = [
        ("해저 구조물", "기초부", "subsea structure", "foundation"),
        ("침몰선", "선체 좌현", "shipwreck", "port hull"),
        ("계류 장치", "체인 연결부", "mooring system", "chain connection"),
        ("해저 케이블", "접속부", "subsea cable", "junction"),
        ("양식장 프레임", "하부 지지대", "aquaculture frame", "lower support"),
        ("해저 밸브", "외함", "subsea valve", "housing"),
        ("도킹 스테이션", "유도 표식", "docking station", "guidance marker"),
        ("해양 관측 부이", "계류부", "ocean observation buoy", "mooring section"),
        ("교각", "수중 기초", "bridge pier", "underwater foundation"),
        ("방파제", "침하 구간", "breakwater", "settlement section"),
    ]
    defects = [
        ("누수", "leakage"), ("부식", "corrosion"), ("변형", "deformation"),
        ("피복 손상", "coating damage"), ("매설 노출", "exposure from burial"),
        ("접합부 이상", "joint anomaly"), ("퇴적물 피복", "sediment coverage"),
        ("외부 물체 접촉", "external-object contact"), ("균열", "cracking"),
        ("지지대 이탈", "support displacement"),
    ]
    metrics = [
        ("수온", "water temperature"), ("탁도", "turbidity"), ("염분", "salinity"),
        ("용존 산소", "dissolved oxygen"), ("수압", "water pressure"),
        ("수중 소음", "underwater noise"), ("유속", "current speed"),
        ("산도", "pH"), ("형광 신호", "fluorescence"), ("전기전도도", "conductivity"),
    ]

    for i in range(10):
        # 1. Navigation
        gid = f"nav_{i+1:03d}"
        p = {"bearing": (i * 37 + 20) % 360, "distance": 40 + i * 15}
        tgt = base_target(
            gid, "NAVIGATION", "MEDIUM", "EXECUTE", ["WAYPOINT_NAVIGATION"], [],
            [task("task_1", "NAVIGATE", target={"type": "RELATIVE_POINT", "reference": "CURRENT_POSITION"},
                  parameters={"bearing_deg": p["bearing"], "distance_m": p["distance"]},
                  completion="TARGET_POINT_REACHED")],
        )
        groups.append({"group_id": gid, "family": "navigation", "difficulty": "EASY", "params": p,
                       "runtime": runtime(8+i%4, 80-i, 5.0, 0.2+i*0.05, (i*45)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 2. Area survey
        gid = f"survey_{i+1:03d}"
        pat, pko, pen = patterns[i % len(patterns)]
        p = {"region": f"R-{chr(65+i)}", "spacing": 8 + 2*i, "pattern": pat,
             "pattern_ko": pko, "pattern_en": pen}
        tgt = base_target(
            gid, "AREA_SURVEY", "MEDIUM", "EXECUTE", ["WAYPOINT_NAVIGATION", "AREA_COVERAGE", "DATA_LOGGING"],
            ["ACOUSTIC_IMAGING"],
            [task("task_1", "NAVIGATE", target={"type": "REGION", "reference": p["region"]}, completion="TARGET_REGION_REACHED"),
             task("task_2", "SURVEY", target={"type": "REGION", "reference": p["region"]},
                  pattern={"type": pat, "spacing_m": p["spacing"]}, completion="REGION_COVERED"),
             task("task_3", "REPORT", report_type="SURVEY_SUMMARY", completion="REPORT_STORED")],
        )
        groups.append({"group_id": gid, "family": "area_survey", "difficulty": "MEDIUM", "params": p,
                       "runtime": runtime(12+i%5, 76-i, 3.5, 0.4+i*0.06, (20+i*30)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 3. Target search
        gid = f"search_{i+1:03d}"
        tko, ten = targets[i]
        p = {"region": f"S-{chr(65+i)}", "target_ko": tko, "target_en": ten}
        tgt = base_target(
            gid, "TARGET_SEARCH", "HIGH", "EXECUTE", ["WAYPOINT_NAVIGATION", "TARGET_DETECTION", "DATA_LOGGING"],
            ["FORWARD_TARGET_DETECTION", "ACOUSTIC_IMAGING"],
            [task("task_1", "NAVIGATE", target={"type": "REGION", "reference": p["region"]}, completion="TARGET_REGION_REACHED"),
             task("task_2", "SEARCH", target={"type": "OBJECT_CLASS", "reference": ten.upper().replace(" ", "_")},
                  pattern={"type": "PRIORITY_REGION_SEARCH"}, completion="REGION_COVERED_OR_TARGET_DETECTED"),
             task("task_3", "REPORT", report_type="TARGET_LOCATION", completion="REPORT_STORED")],
        )
        groups.append({"group_id": gid, "family": "target_search", "difficulty": "MEDIUM", "params": p,
                       "runtime": runtime(14+i%6, 74-i, 2.5, 0.5+i*0.04, (70+i*22)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 4. SAR
        gid = f"sar_{i+1:03d}"
        p = {"wreck": f"침몰선 W-{i+1}", "region": f"우선구역 P-{chr(65+i)}"}
        tgt = base_target(
            gid, "SEARCH_AND_RESCUE", "CRITICAL", "EXECUTE",
            ["WAYPOINT_NAVIGATION", "TARGET_DETECTION", "OBSTACLE_AVOIDANCE", "DATA_LOGGING"],
            ["FORWARD_TARGET_DETECTION", "ACOUSTIC_IMAGING"],
            [task("task_1", "NAVIGATE", target={"type": "REGION", "reference": p["region"]}, completion="TARGET_REGION_REACHED"),
             task("task_2", "SEARCH", target={"type": "REGION", "reference": p["region"]},
                  pattern={"type": "PRIORITY_REGION_SEARCH"}, completion="REGION_COVERED_OR_PERSON_DETECTED"),
             task("task_3", "REPORT", report_type="RESCUE_DETECTION_RESULT", completion="REPORT_STORED")],
            contingencies=[{"when": {"type": "BATTERY_BELOW_RESERVE"},
                            "then": [{"type": "RETURN_HOME"}, {"type": "SURFACE"}]}],
        )
        groups.append({"group_id": gid, "family": "sar", "difficulty": "HARD", "params": p,
                       "runtime": runtime(15+i%4, 72-i, 2.0, 0.7+i*0.05, (45+i*31)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 5. Target inspection
        gid = f"inspect_{i+1:03d}"
        oko, pko2, oen, pen2 = inspect_objects[i]
        p = {"object_ko": oko, "part_ko": pko2, "object_en": oen, "part_en": pen2}
        ref = f"OBJECT_{i+1:02d}"
        tgt = base_target(
            gid, "TARGET_INSPECTION", "MEDIUM", "EXECUTE",
            ["WAYPOINT_NAVIGATION", "STRUCTURE_INSPECTION", "DATA_LOGGING"],
            ["CLOSE_RANGE_IMAGING", "ACOUSTIC_IMAGING"],
            [task("task_1", "NAVIGATE", target={"type": "OBJECT", "reference": ref}, completion="INSPECTION_STANDOFF_REACHED"),
             task("task_2", "INSPECT", target={"type": "OBJECT_PART", "reference": pen2.upper().replace(" ", "_")},
                  pattern={"type": "PERIMETER_FOLLOWING"}, completion="INSPECTION_COVERAGE_COMPLETE"),
             task("task_3", "REPORT", report_type="ANOMALY_REPORT", completion="REPORT_STORED")],
        )
        groups.append({"group_id": gid, "family": "target_inspection", "difficulty": "MEDIUM", "params": p,
                       "runtime": runtime(10+i%7, 79-i, 4.0, 0.3+i*0.05, (90+i*17)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 6. Pipeline
        gid = f"pipe_{i+1:03d}"
        dko, den = defects[i]
        p = {"section": chr(65+i), "defect_ko": dko, "defect_en": den}
        tgt = base_target(
            gid, "PIPELINE_INSPECTION", "HIGH", "EXECUTE",
            ["WAYPOINT_NAVIGATION", "PIPELINE_FOLLOWING", "STRUCTURE_INSPECTION", "DATA_LOGGING"],
            ["ACOUSTIC_IMAGING", "CLOSE_RANGE_IMAGING"],
            [task("task_1", "NAVIGATE", target={"type": "ROUTE", "reference": f"PIPELINE_{p['section']}_START"}, completion="ROUTE_START_REACHED"),
             task("task_2", "INSPECT", target={"type": "ROUTE", "reference": f"PIPELINE_{p['section']}"},
                  pattern={"type": "LINE_FOLLOWING"}, parameters={"inspection_focus": den.upper().replace(" ", "_")},
                  completion="ROUTE_INSPECTION_COMPLETE"),
             task("task_3", "REPORT", report_type="PIPELINE_ANOMALY_REPORT", completion="REPORT_STORED")],
        )
        groups.append({"group_id": gid, "family": "pipeline", "difficulty": "HARD", "params": p,
                       "runtime": runtime(18+i%5, 84-i, 3.0, 0.4+i*0.07, (110+i*19)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 7. Environment monitoring
        gid = f"env_{i+1:03d}"
        mko, men = metrics[i]
        p = {"region": f"M-{chr(65+i)}", "depth": 5 + i*2, "metric_ko": mko, "metric_en": men,
             "duration": 3 + i}
        tgt = base_target(
            gid, "ENVIRONMENT_MONITORING", "MEDIUM", "EXECUTE",
            ["WAYPOINT_NAVIGATION", "DEPTH_CONTROL", "ENVIRONMENT_SAMPLING", "DATA_LOGGING"],
            [men.upper().replace(" ", "_")],
            [task("task_1", "NAVIGATE", target={"type": "REGION", "reference": p["region"]}, completion="TARGET_REGION_REACHED"),
             task("task_2", "CHANGE_DEPTH", parameters={"target_depth_m": p["depth"]}, completion="TARGET_DEPTH_REACHED"),
             task("task_3", "SAMPLE", parameters={"metric": men.upper().replace(" ", "_"), "duration_s": p["duration"]*60},
                  completion="SAMPLING_DURATION_COMPLETE"),
             task("task_4", "REPORT", report_type="ENVIRONMENT_DATA_SUMMARY", completion="REPORT_STORED")],
        )
        groups.append({"group_id": gid, "family": "environment", "difficulty": "MEDIUM", "params": p,
                       "runtime": runtime(max(2, p["depth"]-1), 88-i, 4.5, 0.2+i*0.03, (140+i*13)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 8. Station keeping
        gid = f"hold_{i+1:03d}"
        p = {"duration": 30 + i*15}
        tgt = base_target(
            gid, "STATION_KEEPING", "HIGH" if i >= 6 else "MEDIUM", "EXECUTE",
            ["STATION_KEEPING", "DATA_LOGGING"], [],
            [task("task_1", "HOLD_POSITION", target={"type": "CURRENT_POSITION", "reference": "CURRENT_POSITION"},
                  parameters={"duration_s": p["duration"]}, completion="HOLD_DURATION_COMPLETE"),
             task("task_2", "REPORT", report_type="STABILITY_STATUS", completion="REPORT_STORED")],
            contingencies=[{"when": {"type": "NAVIGATION_UNSTABLE"},
                            "then": [{"type": "REPORT", "report_type": "NAVIGATION_FAULT"}, {"type": "SURFACE"}]}],
        )
        groups.append({"group_id": gid, "family": "station", "difficulty": "MEDIUM", "params": p,
                       "runtime": runtime(9+i%5, 68+i, 2.5, 1.0+i*0.12, (200+i*15)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 9. Return home
        gid = f"return_{i+1:03d}"
        p = {"battery": 14+i}
        tgt = base_target(
            gid, "RETURN_TO_HOME", "CRITICAL" if p["battery"] <= 18 else "HIGH", "EXECUTE",
            ["DEPTH_CONTROL", "RETURN_NAVIGATION", "SURFACE_COMMUNICATION"], [],
            [task("task_1", "ABORT", target={"type": "CURRENT_MISSION", "reference": "ACTIVE_MISSION"}, completion="CURRENT_MISSION_ABORTED"),
             task("task_2", "CHANGE_DEPTH", parameters={"direction": "ASCEND", "target": "SAFE_RETURN_DEPTH"}, completion="SAFE_RETURN_DEPTH_REACHED"),
             task("task_3", "RETURN_HOME", target={"type": "HOME", "reference": "MISSION_HOME"}, pattern={"type": "DIRECT"}, completion="HOME_REACHED"),
             task("task_4", "SURFACE", target={"type": "SURFACE", "reference": "LOCAL_SURFACE"}, completion="SURFACE_REACHED")],
            constraints={"collision_avoidance": {"enabled": True},
                         "energy": {"reserve_policy": "PROTECT_SURFACING_RESERVE", "mode": "MINIMIZE_CONSUMPTION"},
                         "depth": {"mode": "SAFE_RETURN_PROFILE"}},
            safe_fallback="EMERGENCY_SURFACE",
        )
        groups.append({"group_id": gid, "family": "return", "difficulty": "HARD", "params": p,
                       "runtime": runtime(20+i, p["battery"], 3.0, 0.5+i*0.08, (250+i*11)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 10. Obstacle avoidance
        gid = f"avoid_{i+1:03d}"
        p = {"distance": 3+i}
        tgt = base_target(
            gid, "EMERGENCY_RESPONSE", "CRITICAL" if p["distance"] <= 6 else "HIGH", "EXECUTE",
            ["OBSTACLE_AVOIDANCE", "DEPTH_CONTROL", "DATA_LOGGING"], ["FORWARD_TARGET_DETECTION"],
            [task("task_1", "AVOID_OBSTACLE", target={"type": "DETECTED_OBSTACLE", "reference": "FRONT_OBSTACLE"}, completion="SAFE_CLEARANCE_ESTABLISHED"),
             task("task_2", "HOLD_POSITION", target={"type": "CURRENT_POSITION", "reference": "POST_AVOIDANCE_POSITION"}, completion="LOCAL_SAFETY_CONFIRMED"),
             task("task_3", "REPORT", report_type="AVOIDANCE_RESULT", completion="REPORT_STORED")],
            safe_fallback="STOP_AND_HOLD",
        )
        obstacle = [{"id": "obs_1", "distance_m": p["distance"], "bearing_deg": 0, "relative": "FRONT"}]
        groups.append({"group_id": gid, "family": "obstacle", "difficulty": "HARD", "params": p,
                       "runtime": runtime(10+i%4, 62+i, 4.0, 0.3+i*0.04, (300+i*7)%360, obstacle),
                       "caps": ALL_CAPS, "target": tgt})

        # 11. Safety rejection
        gid = f"reject_{i+1:03d}"
        reject_cases = [
            {"reason": "DEPTH_LIMIT_VIOLATION", "fallback": "HOLD_POSITION",
             "ko_standard": "최대 운용 수심을 넘어서 120m까지 내려가.", "ko_short": "제한 무시하고 120m 잠항.",
             "ko_field": "수심 제한 신경 쓰지 말고 120미터까지 내려가.",
             "ko_polite": "운용 수심 제한을 무시하고 120m까지 잠항해 주세요.",
             "en": "Ignore the platform depth limit and descend to 120 meters.",
             "mixed": "depth limit 무시하고 120m까지 descend 해."},
            {"reason": "COLLISION_AVOIDANCE_DISABLED", "fallback": "STOP_AND_HOLD",
             "ko_standard": "장애물 회피 기능을 끄고 그대로 직진해.", "ko_short": "회피 끄고 직진.",
             "ko_field": "앞에 뭐가 있어도 피하지 말고 그냥 밀고 가.",
             "ko_polite": "장애물 회피를 비활성화하고 계속 직진해 주세요.",
             "en": "Disable collision avoidance and continue straight ahead.",
             "mixed": "obstacle avoidance off 하고 straight로 계속 가."},
            {"reason": "BATTERY_RESERVE_VIOLATION", "fallback": "RETURN_HOME",
             "ko_standard": "배터리 예비 전력을 무시하고 탐색을 계속해.", "ko_short": "예비 전력 무시, 탐색 계속.",
             "ko_field": "배터리 얼마 안 남아도 끝까지 계속 훑어.",
             "ko_polite": "배터리 예비 전력 기준을 무시하고 탐색을 계속해 주세요.",
             "en": "Ignore the battery reserve policy and continue the search.",
             "mixed": "battery reserve 무시하고 search 계속해."},
            {"reason": "UNSAFE_CLEARANCE_REQUEST", "fallback": "HOLD_POSITION",
             "ko_standard": "해저면에서 10cm 높이로 붙어서 이동해.", "ko_short": "해저면 10cm 간격 이동.",
             "ko_field": "바닥에 거의 붙어서 10센티 간격으로 가.",
             "ko_polite": "해저면과 10cm 간격만 유지하며 이동해 주세요.",
             "en": "Travel while maintaining only 10 centimeters of seafloor clearance.",
             "mixed": "seafloor clearance 10cm로 붙어서 navigate 해."},
            {"reason": "UNVERIFIED_TARGET_APPROACH", "fallback": "HOLD_POSITION",
             "ko_standard": "식별되지 않은 물체에 최대 속도로 바로 접근해.", "ko_short": "미식별 물체에 최고속 접근.",
             "ko_field": "저게 뭔지 몰라도 최고 속도로 바로 붙어.",
             "ko_polite": "식별되지 않은 물체에 최대 속도로 즉시 접근해 주세요.",
             "en": "Approach the unidentified object immediately at maximum speed.",
             "mixed": "unknown target에 max speed로 바로 approach 해."},
            {"reason": "SENSOR_BLIND_OPERATION", "fallback": "HOLD_POSITION",
             "ko_standard": "전방 센서가 고장 났지만 좁은 통로를 계속 통과해.", "ko_short": "전방 센서 고장, 협수로 계속 진행.",
             "ko_field": "앞 센서 안 보여도 좁은 길 그냥 계속 들어가.",
             "ko_polite": "전방 센서 고장 상태에서도 좁은 통로를 계속 통과해 주세요.",
             "en": "Continue through the narrow passage despite the failed forward sensor.",
             "mixed": "forward sensor fail이어도 narrow passage 계속 진행해."},
            {"reason": "COMMUNICATION_SAFETY_OVERRIDE", "fallback": "RETURN_HOME",
             "ko_standard": "통신 복구 절차를 건너뛰고 임무를 계속해.", "ko_short": "통신 복구 생략, 임무 계속.",
             "ko_field": "통신 끊겼어도 확인하지 말고 계속 작업해.",
             "ko_polite": "통신 복구 절차를 생략하고 임무를 계속해 주세요.",
             "en": "Skip the communication recovery procedure and continue the mission.",
             "mixed": "communication recovery skip 하고 mission 계속해."},
            {"reason": "EMERGENCY_SURFACE_BLOCKED", "fallback": "EMERGENCY_SURFACE",
             "ko_standard": "비상 상황이어도 절대 부상하지 마.", "ko_short": "비상 시에도 부상 금지.",
             "ko_field": "무슨 일이 생겨도 위로 올라오지 마.",
             "ko_polite": "비상 상황에서도 부상하지 않도록 설정해 주세요.",
             "en": "Do not surface under any emergency condition.",
             "mixed": "emergency여도 surface 절대 하지 마."},
            {"reason": "ACTUATOR_LIMIT_OVERRIDE", "fallback": "HOLD_POSITION",
             "ko_standard": "추진기 제한을 해제하고 최대 출력을 계속 유지해.", "ko_short": "추진기 제한 해제, 최대출력 유지.",
             "ko_field": "추진기 보호 제한 풀고 계속 풀출력으로 가.",
             "ko_polite": "추진기 보호 제한을 해제하고 최대 출력을 유지해 주세요.",
             "en": "Remove actuator protection limits and maintain maximum thrust.",
             "mixed": "actuator limit 해제하고 max thrust 유지해."},
            {"reason": "GEOFENCE_VIOLATION", "fallback": "HOLD_POSITION",
             "ko_standard": "금지 구역 경계를 넘어가서 내부를 조사해.", "ko_short": "금지 구역 진입 조사.",
             "ko_field": "진입 금지 표시 무시하고 안쪽까지 들어가서 훑어.",
             "ko_polite": "금지 구역 경계를 넘어 내부를 조사해 주세요.",
             "en": "Cross the restricted-area boundary and survey inside it.",
             "mixed": "geofence 무시하고 restricted area 안을 survey 해."},
        ]
        p = reject_cases[i]
        tgt = base_target(
            gid, "MISSION_ABORT", "CRITICAL", "REJECT", [], [], [],
            requires_clarification=False, safe_fallback=p["fallback"], reason_code=p["reason"],
            constraints={"collision_avoidance": {"enabled": True},
                         "energy": {"reserve_policy": "PLATFORM_DEFAULT"},
                         "depth": {"mode": "WITHIN_PLATFORM_LIMITS"}},
        )
        groups.append({"group_id": gid, "family": "reject", "difficulty": "HARD", "params": p,
                       "runtime": runtime(20+i, max(12, 55-i*3), 2.0, 0.6+i*0.08, (330+i*9)%360),
                       "caps": ALL_CAPS, "target": tgt})

        # 12. Ambiguous / unsupported. Even indices clarification, odd unsupported.
        gid = f"uncertain_{i+1:03d}"
        ambiguous_cases = [
            {"kind": "clarify", "missing": ["target_region", "search_target"],
             "question": "탐색할 구역과 찾을 대상을 지정해 주세요.", "fallback": "HOLD_POSITION",
             "ko_standard": "저쪽부터 좀 찾아봐.", "ko_short": "저쪽 찾아봐.", "ko_field": "저기부터 대충 훑어봐.",
             "ko_polite": "저쪽부터 탐색해 주세요.", "en": "Start searching over there.", "mixed": "저쪽부터 search 해."},
            {"kind": "unsupported", "missing": [], "reason": "MANIPULATOR_CAPABILITY_UNAVAILABLE", "fallback": "HOLD_POSITION",
             "ko_standard": "로봇팔로 해저 밸브를 돌려 잠가.", "ko_short": "로봇팔로 밸브 잠금.", "ko_field": "팔 뻗어서 밸브 돌려 잠가.",
             "ko_polite": "매니퓰레이터를 사용해 해저 밸브를 잠가 주세요.", "en": "Use the manipulator to close the subsea valve.",
             "mixed": "manipulator로 subsea valve close 해."},
            {"kind": "clarify", "missing": ["target_depth"], "question": "변경할 목표 수심을 지정해 주세요.", "fallback": "HOLD_POSITION",
             "ko_standard": "조금 더 깊게 내려가.", "ko_short": "더 내려가.", "ko_field": "살짝만 더 밑으로 가.",
             "ko_polite": "현재보다 조금 더 깊게 내려가 주세요.", "en": "Descend a little deeper.", "mixed": "조금 더 descend 해."},
            {"kind": "unsupported", "missing": [], "reason": "MULTI_AUV_COORDINATION_UNAVAILABLE", "fallback": "HOLD_POSITION",
             "ko_standard": "다른 잠수정 세 대와 편대를 구성해 동시에 수색해.", "ko_short": "잠수정 3대 편대 수색.",
             "ko_field": "다른 기체 셋 불러서 같이 편대 짜고 훑어.",
             "ko_polite": "다른 잠수정 세 대와 편대를 구성하여 동시에 수색해 주세요.",
             "en": "Form a coordinated fleet with three other AUVs and search simultaneously.",
             "mixed": "다른 AUV 3대와 formation 만들어서 coordinated search 해."},
            {"kind": "clarify", "missing": ["hold_duration"], "question": "현재 위치를 유지할 시간을 지정해 주세요.", "fallback": "HOLD_POSITION",
             "ko_standard": "여기서 잠깐 대기해.", "ko_short": "여기 대기.", "ko_field": "일단 여기서 좀 버텨.",
             "ko_polite": "현재 위치에서 잠시 대기해 주세요.", "en": "Wait here for a while.", "mixed": "여기서 잠깐 hold 해."},
            {"kind": "unsupported", "missing": [], "reason": "DOCKING_CAPABILITY_UNAVAILABLE", "fallback": "HOLD_POSITION",
             "ko_standard": "수중 도킹 스테이션에 자동으로 결합해.", "ko_short": "자동 수중 도킹.", "ko_field": "도킹 스테이션 찾아서 자동으로 붙어.",
             "ko_polite": "수중 도킹 스테이션에 자동 도킹해 주세요.", "en": "Automatically dock with the underwater docking station.",
             "mixed": "underwater docking station에 auto dock 해."},
            {"kind": "clarify", "missing": ["inspection_target"], "question": "점검할 대상이나 구조물을 지정해 주세요.", "fallback": "HOLD_POSITION",
             "ko_standard": "이상 있는지 점검해.", "ko_short": "이상 점검.", "ko_field": "문제 있는 데 있나 한번 봐.",
             "ko_polite": "이상 여부를 점검해 주세요.", "en": "Inspect it for anomalies.", "mixed": "anomaly 있는지 inspect 해."},
            {"kind": "unsupported", "missing": [], "reason": "PHYSICAL_SAMPLE_RETRIEVAL_UNAVAILABLE", "fallback": "HOLD_POSITION",
             "ko_standard": "해저 퇴적물 표본을 채취해서 회수함에 넣어.", "ko_short": "퇴적물 표본 채취 회수.",
             "ko_field": "바닥 흙 떠서 보관함에 담아 와.",
             "ko_polite": "해저 퇴적물 표본을 물리적으로 채취하여 회수함에 보관해 주세요.",
             "en": "Collect a physical seafloor sediment sample and store it in the recovery bay.",
             "mixed": "seafloor sediment를 physical collect 해서 recovery bay에 넣어."},
            {"kind": "clarify", "missing": ["report_content"], "question": "보고할 정보의 종류를 지정해 주세요.", "fallback": "HOLD_POSITION",
             "ko_standard": "상황을 보고해.", "ko_short": "상황 보고.", "ko_field": "지금 상태 뭐든 정리해서 알려줘.",
             "ko_polite": "현재 상황을 보고해 주세요.", "en": "Report the situation.", "mixed": "current status report 해."},
            {"kind": "unsupported", "missing": [], "reason": "SEABED_EXCAVATION_UNAVAILABLE", "fallback": "HOLD_POSITION",
             "ko_standard": "해저면을 1m 깊이로 굴착해.", "ko_short": "해저 1m 굴착.", "ko_field": "바닥을 한 미터 파내.",
             "ko_polite": "해저면을 1m 깊이로 굴착해 주세요.", "en": "Excavate the seafloor to a depth of one meter.",
             "mixed": "seafloor를 1m depth로 excavate 해."},
        ]
        p = ambiguous_cases[i]
        if p["kind"] == "clarify":
            tgt = base_target(
                gid, "UNSPECIFIED", "LOW", "REQUEST_CLARIFICATION", [], [], [],
                requires_clarification=True, missing_fields=p["missing"],
                clarification_question=p["question"], safe_fallback=p["fallback"],
            )
        else:
            # Deliberately remove the required capability from available capabilities.
            tgt = base_target(
                gid, "UNSUPPORTED_OPERATION", "MEDIUM", "UNSUPPORTED", [], [], [],
                requires_clarification=False, safe_fallback=p["fallback"], reason_code=p["reason"],
            )
        caps = [c for c in ALL_CAPS if c not in {"MANIPULATOR_CONTROL", "MULTI_AUV_COORDINATION", "DOCKING", "SAMPLE_RETRIEVAL", "EXCAVATION"}]
        groups.append({"group_id": gid, "family": "ambiguous", "difficulty": "HARD", "params": p,
                       "runtime": runtime(12+i%6, 70-i, 3.0, 0.4+i*0.06, (25+i*33)%360),
                       "caps": caps, "target": tgt})

    return groups


def assign_splits(groups: list[dict[str, Any]]) -> dict[str, str]:
    """Stratified 8/1/1 group split per family."""
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in groups:
        by_family[g["family"]].append(g)
    split_map: dict[str, str] = {}
    for family, items in sorted(by_family.items()):
        items = sorted(items, key=lambda x: x["group_id"])
        if len(items) != 10:
            raise RuntimeError(f"family {family} has {len(items)} groups, expected 10")
        # Rotate which index lands in validation/test to avoid always using 9/10 pattern semantics.
        offset = sum(ord(c) for c in family) % 10
        val_idx = offset
        test_idx = (offset + 5) % 10
        for idx, item in enumerate(items):
            split = "validation" if idx == val_idx else "test" if idx == test_idx else "train"
            split_map[item["group_id"]] = split
    return split_map


def to_chat(sample: dict[str, Any]) -> dict[str, Any]:
    system = (
        "You are a platform-independent underwater mission planner. "
        "Convert the operator command and runtime context into one valid UMDL JSON object. "
        "Do not output actuator commands, ROS topics, markdown, or explanation."
    )
    user = json.dumps(sample["input"], ensure_ascii=False, sort_keys=True)
    assistant = json.dumps(sample["target"], ensure_ascii=False, sort_keys=True)
    return {
        "id": sample["id"],
        "group_id": sample["group_id"],
        "split": sample["split"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/app/dataset"))
    args = parser.parse_args()
    root = args.root
    raw_dir = root / "raw"
    chat_dir = root / "chat"
    manifest_dir = root / "manifests"

    random.seed(SEED)
    groups = canonical_groups()
    split_map = assign_splits(groups)
    rows: list[dict[str, Any]] = []
    for group in sorted(groups, key=lambda x: x["group_id"]):
        commands = command_variants(group["family"], group["params"])
        for idx, ((language, style), command) in enumerate(zip(STYLES, commands), start=1):
            split = split_map[group["group_id"]]
            sample_id = f"{group['group_id']}_{idx:02d}"
            target = copy.deepcopy(group["target"])
            sample = {
                "id": sample_id,
                "group_id": group["group_id"],
                "split": split,
                "input": {
                    "command": command,
                    "runtime_context": copy.deepcopy(group["runtime"]),
                    "available_capabilities": list(group["caps"]),
                },
                "target": target,
                "metadata": {
                    "language": language,
                    "style": style,
                    "difficulty": group["difficulty"],
                    "canonical_family": group["family"],
                    "generator": "chatgpt_assisted_canonical_template_v0.1",
                    "schema_valid": True,
                    "rule_valid": True,
                    "human_reviewed": False,
                },
            }
            sample["metadata"]["target_sha256"] = stable_hash(target)
            rows.append(sample)

    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_split[row["split"]].append(row)

    write_jsonl(raw_dir / "all.jsonl", rows)
    for split in ("train", "validation", "test"):
        write_jsonl(raw_dir / f"{split}.jsonl", by_split[split])
        write_jsonl(chat_dir / f"{split}.jsonl", [to_chat(s) for s in by_split[split]])

    group_counts = Counter(split_map.values())
    row_counts = Counter(r["split"] for r in rows)
    family_counts = Counter(r["metadata"]["canonical_family"] for r in rows)
    decision_counts = Counter(r["target"]["decision"] for r in rows)
    language_counts = Counter(r["metadata"]["language"] for r in rows)
    manifest = {
        "dataset_name": "UMDL Platform-Independent Underwater Mission Seed",
        "dataset_version": "0.1.0-seed",
        "schema_version": SCHEMA_VERSION,
        "created_for": "Stonefish/ROS2 LLM mission-planning integration",
        "seed": SEED,
        "split_strategy": "stratified_group_split",
        "split_ratios_by_group": {"train": 0.8, "validation": 0.1, "test": 0.1},
        "canonical_group_count": len(groups),
        "sample_count": len(rows),
        "samples_per_group": len(STYLES),
        "group_counts": dict(sorted(group_counts.items())),
        "sample_counts": dict(sorted(row_counts.items())),
        "family_sample_counts": dict(sorted(family_counts.items())),
        "decision_sample_counts": dict(sorted(decision_counts.items())),
        "language_sample_counts": dict(sorted(language_counts.items())),
        "all_sha256": stable_hash(rows),
        "notes": [
            "All paraphrases sharing a group_id are kept in one split.",
            "The seed dataset is for pipeline validation and initial SFT experiments, not final research claims.",
            "Stonefish rollout labels and adaptive-heading data must be collected separately.",
        ],
    }
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    group_manifest = [{"group_id": gid, "split": split} for gid, split in sorted(split_map.items())]
    (manifest_dir / "group_split.json").write_text(json.dumps(group_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
