"""생성한 질의를 다른 회사 모델(OpenAI)이 독립적으로 검증한다(docs/rag_eval_protocol.md §9-1, §9-4).

검증 모델에게는 코퍼스와 질의 문장만 주고, 정답 섹션 id와 fact는 **보여 주지 않는다**. 모델이 "이 질문에 답을 줄 수
있는 섹션을 모두 고르라"는 요청에 고른 집합이 정답 섹션 하나와 다르면 그 질의를 표시한다. 표시는 사람이 보는 신호이고,
제외는 사용자가 확인한 뒤에 한다. 질의는 시드 고정 난수로 섞어 묶음(약 25개)으로 보낸다(순서와 문서별 묶음의 영향을 줄임).

    uv run --group gen python -m pharma_scm.retrieval.verify_queries                  # 추정만
    uv run --group gen python -m pharma_scm.retrieval.verify_queries --batch 1 --run  # 첫 묶음만 시험
    uv run --group gen python -m pharma_scm.retrieval.verify_queries --run            # 남은 묶음 전부
    uv run --group gen python -m pharma_scm.retrieval.verify_queries --controls --run # 통제 질의(§9-6)
"""

import argparse
import json
import math
import random
import time

from .. import config
from . import corpus
from .gen_queries import OUT_PATH as QUERIES_PATH
from .gen_queries import render_corpus

MODEL = "gpt-6.1-terra"  # 사전 등록 9-1: 질의 검증 모델
MAX_OUTPUT_TOKENS = 16000  # 생각 토큰을 포함한 상한
# 단가(100만 토큰당 달러). 사용자가 보고한 값(2026-11-25): 입력 $1, 캐시 입력 $0.05, 출력 $5.
PRICE_IN, PRICE_CACHED, PRICE_OUT = 1.0, 0.05, 5.0
BATCH_SIZE = 25
SEED = 20261125

OUT_PATH = config.ROOT / "eval" / "rag" / "verification_v2.jsonl"
LOG_PATH = config.ROOT / "eval" / "rag" / "generation_log.jsonl"
CONTROLS_PATH = config.ROOT / "eval" / "rag" / "verifier_controls.jsonl"
CONTROLS_OUT = config.ROOT / "eval" / "rag" / "verification_controls.jsonl"

INSTRUCTION = """당신은 규정 검색 평가의 검증자다. 아래 [코퍼스]는 합성 SOP 문서 모음이다.
사용자가 주는 [질의 목록]의 각 질의에 대해, 코퍼스에서 그 질문에 **답을 줄 수 있는 섹션을 모두** 고른다.

[판단 기준]
- 섹션 본문에 질문이 묻는 사실이 실제로 들어 있어야 답을 줄 수 있는 섹션이다. 주제만 비슷한 섹션은 고르지 않는다.
- 같은 질문에 답을 줄 수 있는 섹션이 둘 이상이면 모두 고른다.
- 어느 섹션도 답을 줄 수 없으면 sections를 빈 목록으로 쓴다.
- 질의가 묻는 사실이 불분명하거나 여러 해석이 가능하면 note에 이유를 한 줄로 쓴다. 문제가 없으면 note는 빈 문자열이다.

[출력 형식] JSON 배열 하나만 출력한다(설명, 코드 블록 표시 없이). 질의 번호 순서대로, 질의마다 한 항목:
[{"n": 1, "sections": ["SOP-12-3"], "note": ""}]
"""


def make_batches(rows):
    """질의를 시드 고정으로 섞고 25개 안팎의 묶음으로 나눈다. 묶음 번호는 1부터."""
    order = list(range(len(rows)))
    random.Random(SEED).shuffle(order)
    n = math.ceil(len(rows) / BATCH_SIZE)
    return [[rows[i] for i in order[k::n]] for k in range(n)]


def user_input(batch):
    return "[질의 목록]\n" + "\n".join(f"{i}. {r['query']}" for i, r in enumerate(batch, 1))


def parse_json_array(text):
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        raise ValueError("JSON 배열을 찾지 못했다")
    return json.loads(text[a:b + 1])


def validate(items, batch, valid_ids):
    problems = []
    if len(items) != len(batch):
        problems.append(f"항목 수가 {len(items)}개다(기대 {len(batch)}개)")
        return problems
    for i, item in enumerate(items, 1):
        if item.get("n") != i:
            problems.append(f"{i}번 항목의 n이 {item.get('n')}다")
        secs = item.get("sections")
        if not isinstance(secs, list):
            problems.append(f"{i}번 sections가 목록이 아니다")
            continue
        bad = [s for s in secs if s not in valid_ids]
        if bad:
            problems.append(f"{i}번이 코퍼스에 없는 섹션을 골랐다: {bad}")
    return problems


def done_batches():
    if not OUT_PATH.exists():
        return set()
    rows = [json.loads(line) for line in OUT_PATH.read_text(encoding="utf-8").splitlines() if line]
    return {r["batch"] for r in rows}


def dry_run(rows, secs):
    batches = make_batches(rows)
    base = len(INSTRUCTION) + len(render_corpus(secs))
    q_chars = sum(len(user_input(b)) for b in batches)
    n = len(batches)
    print(f"모델 {MODEL}, 단가 입력 ${PRICE_IN}/캐시 입력 ${PRICE_CACHED}/출력 ${PRICE_OUT} per 100만 토큰(사용자 보고)")
    print("토큰 수는 글자 수로 추정한다(한국어는 1토큰 = 약 1글자였다).")
    print(f"질의 {len(rows)}개를 {n}개 묶음으로 나눔({', '.join(str(len(b)) for b in batches)}개). 호출 {n}회")
    print(f"고정 입력(지시 + 코퍼스) 약 {base:,}자 × {n}회, 질의 입력 합계 약 {q_chars:,}자")
    out_lo = n * 1500          # 항목당 약 60토큰 + 형식, 생각 토큰은 거의 없다고 본 하한
    out_hi = n * 20000         # 생각 토큰이 많은 경우의 상한(max_output_tokens 16,000을 넘지 않음에 가까움)
    in_full = (n * base + q_chars) * PRICE_IN / 1e6
    in_cached = (base + q_chars) * PRICE_IN / 1e6 + (n - 1) * base * PRICE_CACHED / 1e6
    lo = in_cached + out_lo * PRICE_OUT / 1e6
    hi = in_full + out_hi * PRICE_OUT / 1e6
    print(f"비용 추정: ${lo:.2f} ~ ${hi:.2f}(하한: 캐시가 읽히고 생각 토큰이 적을 때, 상한: 캐시 없음, 출력 묶음당 2만 토큰)")


def run(rows, secs, only, force):
    from openai import OpenAI

    config.load_env()
    client = OpenAI()
    instructions = INSTRUCTION + "\n" + render_corpus(secs)
    valid_ids = {s["section_id"] for s in secs}
    batches = make_batches(rows)
    existing = done_batches()
    for k, batch in enumerate(batches, 1):
        if only and k != only:
            continue
        if k in existing and not force:
            print(f"묶음 {k}: 이미 있어서 건너뜀")
            continue
        started = time.time()
        resp = client.responses.create(
            model=MODEL, instructions=instructions, input=user_input(batch),
            max_output_tokens=MAX_OUTPUT_TOKENS, store=False,
        )
        usage = resp.usage.model_dump() if resp.usage else {}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"stage": "verify", "batch": k, "model": MODEL, "status": resp.status,
                                "usage": usage, "seconds": round(time.time() - started, 1),
                                "response_id": resp.id}, ensure_ascii=False) + "\n")
        if resp.status != "completed":
            raise SystemExit(f"묶음 {k}: 상태가 {resp.status}다(생각 토큰이 상한을 넘었을 수 있다). usage={usage}")
        try:
            items = parse_json_array(resp.output_text)
        except ValueError as e:
            raise SystemExit(f"묶음 {k}: {e}. 응답 앞부분: {resp.output_text[:200]!r}")
        problems = validate(items, batch, valid_ids)
        if problems:
            for p in problems:
                print(f"    - 문제: {p}")
            raise SystemExit(f"묶음 {k}: 검사 문제 {len(problems)}건, 저장하지 않고 중단한다(자동 재시도 없음)")
        agree = multi = other = 0
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for item, r in zip(items, batch):
                got, gold = item["sections"], r["section_id"]
                kind = ("일치" if got == [gold] else "정답 포함, 다른 섹션도 고름" if gold in got
                        else "정답을 고르지 않음")
                agree += kind == "일치"
                multi += kind.startswith("정답 포함")
                other += kind == "정답을 고르지 않음"
                f.write(json.dumps({"batch": k, "section_id": gold, "query": r["query"],
                                    "verifier_sections": got, "verifier_note": item.get("note", ""),
                                    "agreement": kind}, ensure_ascii=False) + "\n")
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
        print(f"묶음 {k}: 질의 {len(batch)}개, 입력 {usage.get('input_tokens', 0):,}(캐시 {cached:,}) / "
              f"출력 {usage.get('output_tokens', 0):,}(생각 {reasoning:,}) 토큰")
        print(f"    일치 {agree}, 정답 포함+다른 섹션도 {multi}, 정답을 고르지 않음 {other}")


def run_controls(secs):
    """통제 질의(§9-6)를 같은 지시로 검증기에 넣고, 사전 등록한 판정 규칙으로 통과 여부를 적는다."""
    from openai import OpenAI

    config.load_env()
    client = OpenAI()
    controls = [json.loads(line) for line in CONTROLS_PATH.read_text(encoding="utf-8").splitlines() if line]
    batch = [{"query": c["query"], "section_id": ""} for c in controls]
    valid_ids = {s["section_id"] for s in secs}
    started = time.time()
    resp = client.responses.create(
        model=MODEL, instructions=INSTRUCTION + "\n" + render_corpus(secs), input=user_input(batch),
        max_output_tokens=MAX_OUTPUT_TOKENS, store=False,
    )
    usage = resp.usage.model_dump() if resp.usage else {}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": "verify_controls", "model": MODEL, "status": resp.status, "usage": usage,
                            "seconds": round(time.time() - started, 1), "response_id": resp.id},
                           ensure_ascii=False) + "\n")
    if resp.status != "completed":
        raise SystemExit(f"통제 질의: 상태가 {resp.status}다. usage={usage}")
    items = parse_json_array(resp.output_text)
    problems = validate(items, batch, valid_ids)
    if problems:
        raise SystemExit("통제 질의 응답 검사 문제: " + "; ".join(problems))
    passed = {"ambiguous": 0, "unanswerable": 0}
    with open(CONTROLS_OUT, "w", encoding="utf-8") as f:
        for item, c in zip(items, controls):
            got, exp = item["sections"], c["expected_sections"]
            ok = (len(got) >= 2 and bool(set(got) & set(exp))) if c["kind"] == "ambiguous" else got == []
            passed[c["kind"]] += ok
            f.write(json.dumps({"id": c["id"], "kind": c["kind"], "query": c["query"], "expected": exp,
                                "verifier_sections": got, "verifier_note": item.get("note", ""), "pass": ok},
                               ensure_ascii=False) + "\n")
            print(f"{c['id']} ({c['kind']}): 통과 {ok} | 고른 섹션 {got}")
            if item.get("note"):
                print(f"    메모: {item['note']}")
    n_amb = sum(1 for c in controls if c["kind"] == "ambiguous")
    n_un = len(controls) - n_amb
    power = passed["ambiguous"] >= 4 and passed["unanswerable"] == n_un
    print(f"모호 통제 {passed['ambiguous']}/{n_amb} 통과, 답 없음 통제 {passed['unanswerable']}/{n_un} 통과")
    print("사전 등록 규칙(§9-6) 판정: " + ("검증기는 둘 이상의 답과 답 없음을 가려낸다 -> 128개 검증 결과를 사용한다"
                                         if power else "기준 미달 -> 128개의 일치를 확인된 것으로 해석하지 않는다"))
    reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
    print(f"사용량: 입력 {usage.get('input_tokens', 0):,} / 출력 {usage.get('output_tokens', 0):,}(생각 {reasoning:,}) 토큰")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="실제로 API를 호출한다(기본은 추정만)")
    ap.add_argument("--batch", type=int, help="묶음 번호 하나만(시험용)")
    ap.add_argument("--controls", action="store_true", help="통제 질의(§9-6)를 검증기에 넣는다")
    ap.add_argument("--force", action="store_true", help="이미 있는 묶음도 다시 한다(파일에 이어 쓰므로 먼저 지울 것)")
    a = ap.parse_args()
    secs = corpus.load_corpus()
    rows = [json.loads(line) for line in QUERIES_PATH.read_text(encoding="utf-8").splitlines() if line]
    if a.controls:
        if not a.run:
            print("통제 질의 8개, 호출 1회, 비용 약 $0.01 미만. 실제 호출은 --controls --run")
        else:
            run_controls(secs)
    elif not a.run:
        dry_run(rows, secs)
    else:
        run(rows, secs, a.batch, a.force)


if __name__ == "__main__":
    main()
