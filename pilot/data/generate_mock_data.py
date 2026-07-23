"""
Mock 엑셀 데이터 생성 스크립트 (파일럿 검증용).
기획서 §5 가정 스키마 기반 — 실제 데이터 확보 전까지 로더/판정 로직 검증용으로만 사용.
실제 SME 데이터 확보 시 이 파일 대신 교체할 것.
"""
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent

# 5.1 사이즈 기준 테이블 — priority 숫자가 작을수록 우선 매칭, steel_grade="*"는 와일드카드
size_spec_table = pd.DataFrame([
    {"steel_grade": "SS400", "thickness_min": 6, "thickness_max": 100, "width_min": 1000, "width_max": 3200,
     "length_min": 3000, "length_max": 12000, "priority": 1, "result": "적합", "note": "일반 후판 표준 규격"},
    {"steel_grade": "AH36", "thickness_min": 10, "thickness_max": 80, "width_min": 1500, "width_max": 3500,
     "length_min": 4000, "length_max": 15000, "priority": 1, "result": "적합", "note": "조선용 고장력강"},
    {"steel_grade": "AH36", "thickness_min": 80, "thickness_max": 150, "width_min": 1500, "width_max": 3000,
     "length_min": 4000, "length_max": 12000, "priority": 2, "result": "조건부", "note": "극후물, 별도 열처리 필요"},
    {"steel_grade": "*", "thickness_min": 6, "thickness_max": 50, "width_min": 1000, "width_max": 2500,
     "length_min": 3000, "length_max": 10000, "priority": 10, "result": "적합", "note": "강종 무관 일반 규칙"},
    {"steel_grade": "*", "thickness_min": 100, "thickness_max": 200, "width_min": 1000, "width_max": 4000,
     "length_min": 3000, "length_max": 15000, "priority": 20, "result": "확인필요", "note": "극후물 구간은 개별 확인 필요"},
])

# 5.2 수주 실적 / 투입 이력
order_history = pd.DataFrame([
    {"order_no": "ORD-2026-0001", "steel_grade": "SS400", "thickness": 12, "width": 2000, "length": 6000,
     "input_mill": "광양 3후판", "order_date": "2026-03-10", "status": "완료"},
    {"order_no": "ORD-2026-0002", "steel_grade": "AH36", "thickness": 25, "width": 2500, "length": 8000,
     "input_mill": "광양 2후판", "order_date": "2026-05-02", "status": "완료"},
    {"order_no": "ORD-2026-0003", "steel_grade": "AH36", "thickness": 90, "width": 2200, "length": 6000,
     "input_mill": "광양 2후판", "order_date": "2026-06-18", "status": "진행중"},
    {"order_no": "ORD-2026-0004", "steel_grade": "SS400", "thickness": 40, "width": 1800, "length": 5000,
     "input_mill": "포항 1후판", "order_date": "2026-07-01", "status": "진행중"},
])

# 5.3 여재 Slab 현황 — tap_target(출강목표)은 과제질문.xlsx 예시 코드 재사용 (§3.4-보강)
slab_inventory = pd.DataFrame([
    {"slab_id": "SLB-1001", "steel_grade": "SS400", "thickness": 220, "tap_target": "C080155L5201",
     "mill": "광양 3후판", "available_qty": 4},
    {"slab_id": "SLB-1002", "steel_grade": "AH36", "thickness": 250, "tap_target": "C170150PG201",
     "mill": "광양 2후판", "available_qty": 2},
    {"slab_id": "SLB-1003", "steel_grade": "AH36", "thickness": 300, "tap_target": "C090120PG105",
     "mill": "포항 1후판", "available_qty": 0},
])

# 5.4 진행관리 데이터
progress_status = pd.DataFrame([
    {"order_no": "ORD-2026-0003", "current_stage": "압연대기", "updated_at": "2026-07-18"},
    {"order_no": "ORD-2026-0004", "current_stage": "조합설계검토", "updated_at": "2026-07-20"},
])

# 5.5 집약 기준 (소LOT/데일리 판정용 — 구체 항목 TBD, mock 값)
aggregation_criteria = pd.DataFrame([
    {"criteria_type": "소LOT", "steel_grade": "*", "min_qty_ton": 50, "description": "50톤 미만 주문은 소LOT 집약 검토 대상"},
    {"criteria_type": "데일리", "steel_grade": "*", "min_qty_ton": 200, "description": "일일 누적 200톤 이상 시 데일리 집약 가능"},
])

files = {
    "size_spec_table.xlsx": size_spec_table,
    "order_history.xlsx": order_history,
    "slab_inventory.xlsx": slab_inventory,
    "progress_status.xlsx": progress_status,
    "aggregation_criteria.xlsx": aggregation_criteria,
}

if __name__ == "__main__":
    for filename, df in files.items():
        path = DATA_DIR / filename
        df.to_excel(path, index=False)
        print(f"created: {path} ({len(df)} rows)")
