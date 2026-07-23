"""후판 수주 문의 응답 챗봇 - 파일럿 (mock 데이터 기반)

docs/기획서_후판수주문의챗봇.md 의 설계를 그대로 구현한 단일 파일 파일럿.
실제 SME 데이터/규칙 확정 전까지는 pilot/data/*.xlsx (mock)를 사용한다.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request

load_dotenv()

# ---------- 0. 설정 (기획서 §6) ----------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

SIZE_SPEC_PATH = DATA_DIR / "size_spec_table.xlsx"
ORDER_HISTORY_PATH = DATA_DIR / "order_history.xlsx"
SLAB_INVENTORY_PATH = DATA_DIR / "slab_inventory.xlsx"
PROGRESS_STATUS_PATH = DATA_DIR / "progress_status.xlsx"
AGGREGATION_CRITERIA_PATH = DATA_DIR / "aggregation_criteria.xlsx"
FEEDBACK_LOG_PATH = LOG_DIR / "feedback.jsonl"

# TODO: 실제 URL은 소LOT 에이전트 쪽에서 확정 필요 (기획서 §3.5)
SMALL_LOT_AGENT_URL = os.environ.get("SMALL_LOT_AGENT_URL", "https://example.internal/small-lot-review")
# TODO: 소LOT 판정 threshold는 SME 확인 필요 (기획서 §8-1). 현재는 mock 값.
SMALL_LOT_THRESHOLD_TON = float(os.environ.get("SMALL_LOT_THRESHOLD_TON", 50))

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
client = Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("husan_chatbot")


# ---------- 1. 데이터 접근 계층 (기획서 §3.2) ----------
# 지금은 엑셀을 읽지만, 반환 타입(DataFrame)과 컬럼 계약만 유지하면 추후 DB 쿼리로 교체 가능.
def load_size_spec_table() -> pd.DataFrame:
    return pd.read_excel(SIZE_SPEC_PATH)


def load_order_history() -> pd.DataFrame:
    return pd.read_excel(ORDER_HISTORY_PATH)


def load_slab_inventory() -> pd.DataFrame:
    return pd.read_excel(SLAB_INVENTORY_PATH)


def load_progress_status() -> pd.DataFrame:
    return pd.read_excel(PROGRESS_STATUS_PATH)


def load_aggregation_criteria() -> pd.DataFrame:
    return pd.read_excel(AGGREGATION_CRITERIA_PATH)


# ---------- 2. 사이즈 기준 판정 로직 (기획서 §3.3, 경로 B) ----------
def evaluate_size_spec(thickness, width, length, steel_grade, heat_treated=False) -> dict:
    """와일드카드 + 우선순위 매칭. 매칭 규칙이 없으면 반드시 '확인필요'로 응답한다 (임의 추정 금지).
    heat_treated: 열처리재 여부. 현재 mock 기준 테이블에는 열처리 축이 없어 매칭에는 반영하지
    않고, 별도 확인이 필요하다는 안내만 붙인다 (기획서 §8-12 미결 사항)."""
    df = load_size_spec_table()
    candidates = df[(df["steel_grade"] == steel_grade) | (df["steel_grade"] == "*")]

    matched = None
    for _, row in candidates.sort_values("priority").iterrows():
        if (
            row["thickness_min"] <= thickness <= row["thickness_max"]
            and row["width_min"] <= width <= row["width_max"]
            and row["length_min"] <= length <= row["length_max"]
        ):
            matched = row
            break

    if matched is None:
        result = {
            "status": "확인필요",
            "matched_rule": None,
            "reason": "기준 테이블에서 매칭되는 규칙을 찾지 못했습니다. 임의로 판정하지 않고 확인 필요로 안내합니다.",
        }
    else:
        result = {
            "status": matched["result"],
            "matched_rule": matched.to_dict(),
            "reason": f"{matched['steel_grade']} 규칙(우선순위 {matched['priority']})에 매칭됨 — {matched['note']}",
        }

    if heat_treated:
        result["heat_treatment_note"] = (
            "열처리재로 표시되었으나 현재 기준 테이블에는 열처리 여부가 매칭 축으로 반영되어 "
            "있지 않습니다. 위 판정 결과와 별도로 열처리 가능 구간은 확인이 필요합니다."
        )

    return result


# ---------- 2b. 단중 산출 (기획서 §3.7, 보조 계산) ----------
# 단중 "예측"(공정 손실·수율 감안 추정, 범위 밖)과는 다른 단순 기하학적 계산 — LLM 미개입.
STEEL_DENSITY = 7.82  # 사용자 제공 상수


def calculate_unit_weight(thickness, width, length) -> float:
    """두께/폭/길이(mm) -> 단중(kg). 결정론적 계산, 임의 추정 아님."""
    return thickness * width * length * STEEL_DENSITY / 1_000_000


# ---------- 3. 정형 데이터 조회 (기획서 §3.4, 경로 C) ----------
def query_structured_data(steel_grade=None, order_no=None, tap_target=None) -> dict:
    evidence = {}

    history = load_order_history()
    if steel_grade:
        history = history[history["steel_grade"] == steel_grade]
    evidence["order_history"] = history.to_dict(orient="records")

    slabs = load_slab_inventory()
    if tap_target:
        slabs = slabs[slabs["tap_target"] == tap_target]
    elif steel_grade:
        slabs = slabs[slabs["steel_grade"] == steel_grade]
    evidence["slab_inventory"] = slabs.to_dict(orient="records")

    progress = load_progress_status()
    if order_no:
        progress = progress[progress["order_no"] == order_no]
    evidence["progress_status"] = progress.to_dict(orient="records")

    evidence["aggregation_criteria"] = load_aggregation_criteria().to_dict(orient="records")
    return evidence


# ---------- 4. 소LOT 라우팅 (기획서 §3.5, 경로 A — 링크 안내로 확정, LLM 미호출) ----------
def is_small_lot_delegation(order_context: dict) -> bool:
    """규칙 기반 1차 게이트.
    TODO: '주문서 작성 상태' 판별 필드는 SME 확인 필요 (기획서 §8-1). 현재는 수량(톤)만 사용하는 mock 규칙."""
    if not order_context:
        return False
    qty = order_context.get("quantity_ton")
    order_written = order_context.get("order_written", False)
    if qty is None:
        return False
    return bool(order_written) and qty < SMALL_LOT_THRESHOLD_TON


def small_lot_route(order_context: dict) -> dict:
    return {
        "type": "link_card",
        "title": "소LOT 주문 투입 검토",
        "description": "소LOT 주문으로 판단되어 전용 검토 화면으로 연결됩니다.",
        "url": SMALL_LOT_AGENT_URL,
    }


# ---------- 5. LLM 의도 분류 (기획서 §3.1, §4.1) ----------
CLASSIFY_TOOL = {
    "name": "classify_inquiry",
    "description": "판매 담당자 문의를 사이즈기준 문의/정형데이터 조회 문의로 분류하고 규격 정보를 추출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string", "enum": ["size_spec", "structured_query"]},
                "description": "해당하는 카테고리 전부. 복합 질문이면 둘 다 포함.",
            },
            "extracted_spec": {
                "type": "object",
                "description": "문의에서 추출한 규격/주문 정보 (있는 경우만 채움)",
                "properties": {
                    "steel_grade": {"type": "string"},
                    "thickness": {"type": "number"},
                    "width": {"type": "number"},
                    "length": {"type": "number"},
                    "order_no": {"type": "string"},
                    "tap_target": {"type": "string", "description": "출강목표 코드"},
                },
            },
        },
        "required": ["categories"],
    },
}


def classify_inquiry(user_message: str) -> dict:
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_inquiry"},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return block.input
    return {"categories": []}


# ---------- 6. 응답 생성 (기획서 §4.2) ----------
SYSTEM_PROMPT = """당신은 포스코그룹 후판 수주 문의에 응답하는 1차 응대 챗봇입니다.
반드시 지켜야 할 규칙:
1. 제공된 근거자료(evidence)에 없는 내용은 절대 생성하지 마세요.
2. 근거자료가 부족하거나 판정 결과가 '확인필요'이면 그대로 확인 필요라고 답하세요. 임의로 적합/부적합을 판단하지 마세요.
3. 조합 설계 가능여부, 투입 가능 소 등 최종 판단이 필요한 내용을 언급할 때는 반드시
   "이 응답은 참고 의견이며, 최종 승인은 수주 담당자가 진행합니다"라는 취지의 문구를 포함하세요.
4. 단중 "예측"(공정 손실·수율 등을 감안한 실제 생산량 추정)이나 조합 설계의 최종 확정은 이
   챗봇의 역할이 아닙니다. 요청받아도 답하지 말고 담당자 확인을 안내하세요.
5. 간결하게, 근거자료의 값을 함께 인용하며 답변하세요.
6. 근거자료에 heat_treatment_note가 있으면 반드시 그 내용을 함께 안내하세요.
7. 근거자료에 unit_weight_kg가 있으면 값을 안내하되, 이는 두께×폭×길이 기반 기하학적
   계산값이며 공정 손실·수율을 감안한 예측치가 아니라는 점을 반드시 함께 명시하세요.
"""


def stream_response(user_message: str, evidence: dict):
    evidence_text = json.dumps(evidence, ensure_ascii=False, default=str)
    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"문의: {user_message}\n\n근거자료(JSON): {evidence_text}"}],
    ) as stream:
        yield from stream.text_stream


# ---------- 7. Flask + SSE (기획서 §2.3) ----------
app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


def _describe_structured_spec(spec: dict) -> str:
    """구조화 입력만 있고 자유 텍스트 문의가 비어 있을 때, LLM 프롬프트용 문의 문장을 합성."""
    parts = []
    if spec.get("tap_target"):
        parts.append(f"출강목표 {spec['tap_target']}")
    if spec.get("steel_grade"):
        parts.append(f"규격 {spec['steel_grade']}")
    if spec.get("heat_treated"):
        parts.append("열처리재")
    if spec.get("thickness") is not None:
        parts.append(f"두께 {spec['thickness']}T")
    if spec.get("width") is not None:
        parts.append(f"폭 {spec['width']}")
    if spec.get("length") is not None:
        parts.append(f"길이 {spec['length']}")
    return (", ".join(parts) + " 관련 문의") if parts else "문의 정보 없음"


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_message = (data.get("message") or "").strip()
    order_context = data.get("order_context") or {}
    # 상단 구조화 입력 폼(출강목표/규격/열처리/두께/폭/길이) — 값이 있는 필드만 채워서 온다.
    structured_spec = {k: v for k, v in (data.get("structured_spec") or {}).items() if v not in (None, "", False)}

    def generate():
        # Step 1: 규칙 게이트 (소LOT) — LLM 미호출
        if is_small_lot_delegation(order_context):
            card = small_lot_route(order_context)
            yield f"event: link_card\ndata: {json.dumps(card, ensure_ascii=False)}\n\n"
            return

        # Step 2: LLM 의도 분류 — 자유 텍스트가 있을 때만 호출 (구조화 입력만 있으면 스킵)
        categories = set()
        llm_spec = {}
        if user_message:
            try:
                classification = classify_inquiry(user_message)
            except Exception:
                logger.exception("classify_inquiry failed")
                err = {"text": "문의 분류 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}
                yield f"event: message\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"
                return
            categories.update(classification.get("categories", []))
            llm_spec = classification.get("extracted_spec") or {}

        # 구조화 입력이 LLM 추출값보다 우선 (사용자가 직접 입력한 값 = 임의 추정 아님)
        spec = {**llm_spec, **structured_spec}

        # 채워진 구조화 필드로 카테고리 보강 — 폼만 채우고 문의는 비워도 라우팅되도록
        if all(spec.get(k) is not None for k in ("thickness", "width", "length")):
            categories.add("size_spec")
        if spec.get("tap_target"):
            categories.add("structured_query")
        if not categories and structured_spec:
            # 규격 일부만 채워진 애매한 경우 — 정형 조회로 폴백해 근거자료라도 보여준다
            categories.add("structured_query")

        if not categories:
            msg = "어떤 종류의 문의인지 조금 더 구체적으로 말씀해 주세요. (예: 규격 기준 문의 / 실적·진행 조회 문의)"
            yield f"event: message\ndata: {json.dumps({'text': msg}, ensure_ascii=False)}\n\n"
            return

        # Step 3: 근거자료 수집 (경로 B/C)
        evidence = {}
        if "size_spec" in categories and all(k in spec for k in ("thickness", "width", "length")):
            evidence["size_spec_result"] = evaluate_size_spec(
                spec.get("thickness"), spec.get("width"), spec.get("length"),
                spec.get("steel_grade") or "*", heat_treated=bool(spec.get("heat_treated")),
            )
        if "structured_query" in categories:
            evidence["structured_data"] = query_structured_data(
                steel_grade=spec.get("steel_grade"), order_no=spec.get("order_no"), tap_target=spec.get("tap_target")
            )

        # 단중 산출 (§3.7) — 카테고리와 무관하게 두께/폭/길이가 모두 있으면 항상 계산해 첨부
        if all(spec.get(k) is not None for k in ("thickness", "width", "length")):
            evidence["unit_weight_kg"] = round(
                calculate_unit_weight(spec["thickness"], spec["width"], spec["length"]), 2
            )

        if not evidence:
            evidence["note"] = "분류는 되었으나 판정/조회에 필요한 규격 정보가 부족합니다. 강종/두께/폭/길이 등을 포함해 다시 문의해 주세요."

        # Step 4: 응답 생성 (스트리밍) — 자유 텍스트가 없으면 구조화 입력으로 문의 문장을 합성
        prompt_message = user_message or _describe_structured_spec(spec)
        try:
            for chunk in stream_response(prompt_message, evidence):
                yield f"event: message\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("stream_response failed")
            err = {"text": "응답 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}
            yield f"event: message\ndata: {json.dumps(err, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream")


# ---------- 8. 피드백 저장 (기획서 §3.6) ----------
@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.get_json(force=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_message": data.get("user_message", ""),
        "bot_response": data.get("bot_response", ""),
        "feedback": data.get("feedback", ""),
    }
    with open(FEEDBACK_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"status": "saved"}


if __name__ == "__main__":
    app.run(debug=True, port=5000)
