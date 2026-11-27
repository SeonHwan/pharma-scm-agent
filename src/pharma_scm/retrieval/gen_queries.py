"""규정 검색 벤치마크의 질의를 Claude Opus 5.5로 생성.

새 문서 15개의 섹션마다 질의를 1개씩 만듦. 코퍼스 전체(25개 문서)를 시스템 프롬프트에 넣고 캐시 지점을 둬서
15번의 호출이 같은 코퍼스를 한 번만 쓰고 나머지는 캐시에서 읽게 함. 기본은 --dry-run(API 호출 없음).

    uv run python -m pharma_scm.retrieval.gen_queries                # 추정만
    uv run python -m pharma_scm.retrieval.gen_queries --only 12 --run  # 문서 하나만 실제 생성(시험)
    uv run python -m pharma_scm.retrieval.gen_queries --run            # 남은 문서 전부
"""

import argparse
import json
import re
import time

from .. import config
from . import corpus, topics

MODEL = "claude-opus-5-5"  # 사전 등록 9-1: 질의 생성 모델
MAX_TOKENS = 16000
# 단가(100만 토큰당 달러). 2026-11-03에 확인한 값이라 바뀌었을 수 있음. 캐시 쓰기는 입력의 1.25배.
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, CACHE_WRITE_X = 4.0, 20.0, 0.20, 1.25

OUT_PATH = config.ROOT / "eval" / "rag" / "queries_v2.jsonl"
LOG_PATH = config.ROOT / "eval" / "rag" / "generation_log.jsonl"

INSTRUCTION = """당신은 의약품 물류센터의 규정 검색 시스템을 평가하기 위한 질의를 쓰는 작성자다.
아래 [코퍼스]는 합성 SOP 문서 모음이다. 사용자가 지정한 문서의 섹션마다 **질의를 정확히 1개** 쓴다.

[질의 작성 규칙]
1. 현장 직원이 챗봇에 묻듯이 자연스러운 질문 한 문장(20~80자)으로 쓴다.
2. 정답 섹션의 **고유한 사실**(수치, 기한, 승인자, 조건)을 묻는다. 정답 섹션 하나가 그 사실에 답할 수 있어야 한다.
3. 섹션 제목과 본문의 표현을 그대로 베끼지 않는다. 같은 뜻의 다른 단어, 구어체, 줄임말, 상황 설명으로 바꿔 쓴다.
4. 질의 안에 정답(수치, 승인자 이름 등 섹션이 알려 주는 값)을 쓰지 않는다. 묻기만 한다.
5. 코퍼스의 다른 섹션도 같은 질문에 답할 수 있어 보이면(같은 주제의 비슷한 규정), 그 섹션과 구분되는 조건(단계, 대상, 상황)을 질의에 넣어 정답이 이 섹션 하나가 되게 한다.
   그렇게 해도 구분되지 않는 사실이면 ambiguous를 true로 쓴다.
6. 섹션 id나 문서 번호를 질의에 쓰지 않는다.

[출력 형식] JSON 배열 하나만 출력한다(설명, 코드 블록 표시 없이). 지정한 섹션 순서대로, 섹션마다 한 항목:
[{"section_id": "SOP-12-1", "query": "질의 문장", "fact": "이 질의가 묻는 고유 사실 한 줄", "ambiguous": false}]
"""


def render_corpus(secs):
    parts = []
    for s in secs:
        parts.append(f"## {s['section_id']} {s['title']} (문서: {s['doc_title']})\n{s['body']}")
    return "[코퍼스]\n" + "\n\n".join(parts)


def system_blocks(secs):
    """캐시 지점은 코퍼스 블록에 둠. 호출마다 같은 내용이어야 캐시가 읽힘."""
    return [
        {"type": "text", "text": INSTRUCTION},
        {"type": "text", "text": render_corpus(secs), "cache_control": {"type": "ephemeral"}},
    ]


def target_sections(doc, secs):
    return [s for s in secs if s["doc_id"] == f"SOP-{doc['no']}"]


def user_message(doc, targets):
    lines = "\n".join(f"- {s['section_id']} {s['title']}" for s in targets)
    return f"SOP-{doc['no']} {doc['heading']}의 섹션 {len(targets)}개 각각에 대해 질의를 쓴다.\n{lines}"


def parse_json_array(text):
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        raise ValueError("JSON 배열을 찾지 못했다")
    return json.loads(text[a:b + 1])


def validate(items, targets):
    """(심각한 문제, 경고)를 돌려줌. 심각한 문제가 있으면 저장하지 않음."""
    problems, warnings = [], []
    if len(items) != len(targets):
        problems.append(f"항목 수가 {len(items)}개다(기대 {len(targets)}개)")
        return problems, warnings
    for item, sec in zip(items, targets):
        sid = sec["section_id"]
        if item.get("section_id") != sid:
            problems.append(f"{sid}: section_id가 {item.get('section_id')}다")
            continue
        q = str(item.get("query", "")).strip()
        if not 15 <= len(q) <= 120:
            problems.append(f"{sid}: 질의 길이가 {len(q)}자다(15~120)")
        if re.search(r"SOP-\d", q):
            problems.append(f"{sid}: 질의에 섹션 id가 들어 있다")
        if not str(item.get("fact", "")).strip():
            problems.append(f"{sid}: fact가 비어 있다")
        if item.get("ambiguous") is True:
            warnings.append(f"{sid}: 모델이 ambiguous로 표시했다")
        ov = corpus.overlap(q, sec)
        if ov >= 0.85:
            warnings.append(f"{sid}: 어휘 겹침이 {ov:.2f}로 높다(섹션 표현을 베꼈을 수 있다)")
    return problems, warnings


def done_docs():
    if not OUT_PATH.exists():
        return set()
    rows = [json.loads(line) for line in OUT_PATH.read_text(encoding="utf-8").splitlines() if line]
    return {r["section_id"].rsplit("-", 1)[0] for r in rows}


def dry_run(docs, secs):
    sys_chars = len(INSTRUCTION) + len(render_corpus(secs))
    print(f"모델 {MODEL}, 단가 입력 ${PRICE_IN}/출력 ${PRICE_OUT}/캐시 읽기 ${PRICE_CACHE_READ} per 100만 토큰(2026-11-03 확인값)")
    print("토큰 수는 글자 수로 추정한다(한국어는 1토큰 = 약 1글자였다, 문서 생성 실측).")
    print(f"고정 프롬프트(지시 + 코퍼스 {len(secs)}개 섹션): 약 {sys_chars:,}자 = 캐시 대상")
    n_out = n_user = 0
    for d in docs:
        t = target_sections(d, secs)
        n_user += len(user_message(d, t))
        n_out += len(t) * 170
    n = len(docs)
    print(f"호출 {n}회, 호출마다 달라지는 입력 합계 약 {n_user:,}자, 출력 합계 약 {n_out:,}자(질의, fact, 형식)")
    # 첫 호출은 캐시 쓰기, 나머지는 캐시 읽기. 출력에는 생각(thinking) 토큰이 더해짐(상한은 4배로 봄).
    cost_lo = (sys_chars * CACHE_WRITE_X * PRICE_IN + (n - 1) * sys_chars * PRICE_CACHE_READ
               + n_user * PRICE_IN + n_out * PRICE_OUT) / 1e6
    cost_hi = (sys_chars * CACHE_WRITE_X * PRICE_IN + (n - 1) * sys_chars * PRICE_CACHE_READ
               + n_user * PRICE_IN + n_out * 4 * PRICE_OUT) / 1e6
    no_cache = (n * sys_chars * PRICE_IN + n_user * PRICE_IN + n_out * 4 * PRICE_OUT) / 1e6
    print(f"비용 추정: ${cost_lo:.2f} ~ ${cost_hi:.2f}(캐시가 읽힐 때, 생각 토큰 상한 4배 포함)")
    print(f"캐시가 전혀 읽히지 않으면 상한이 약 ${no_cache:.2f}까지 올라간다. 첫 두 호출의 usage로 캐시 읽기를 확인한다.")


def run(docs, secs, force):
    import anthropic

    config.load_env()
    client = anthropic.Anthropic()
    existing = done_docs()
    for d in docs:
        doc_id = f"SOP-{d['no']}"
        if doc_id in existing and not force:
            print(f"{doc_id}: 이미 있어서 건너뜀")
            continue
        targets = target_sections(d, secs)
        started = time.time()
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system_blocks(secs),
            messages=[{"role": "user", "content": user_message(d, targets)}],
        )
        u = resp.usage
        record = {"stage": "queries", "no": d["no"], "model": MODEL, "stop_reason": resp.stop_reason,
                  "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "cache_creation_input_tokens": u.cache_creation_input_tokens,
                  "cache_read_input_tokens": u.cache_read_input_tokens,
                  "seconds": round(time.time() - started, 1), "request_id": resp._request_id}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if resp.stop_reason == "refusal":
            raise SystemExit(f"{doc_id}: 모델이 거절했다. 폴백 없이 중단한다: {resp.stop_details}")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        try:
            items = parse_json_array(text)
        except ValueError as e:
            raise SystemExit(f"{doc_id}: {e}. 응답 앞부분: {text[:200]!r}")
        problems, warnings = validate(items, targets)
        usage = (f"입력 {u.input_tokens:,} / 캐시 쓰기 {u.cache_creation_input_tokens or 0:,} / "
                 f"캐시 읽기 {u.cache_read_input_tokens or 0:,} / 출력 {u.output_tokens:,} 토큰")
        if problems:
            print(f"{doc_id}: {usage}, 검사 문제 {len(problems)}건 -> 저장하지 않음")
            for p in problems:
                print(f"    - 문제: {p}")
            raise SystemExit("자동 재시도는 하지 않는다. 문제를 보고 다시 실행한다.")
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for item, sec in zip(items, targets):
                q = item["query"].strip()
                f.write(json.dumps({
                    "section_id": sec["section_id"], "query": q, "fact": item["fact"].strip(),
                    "ambiguous_by_generator": bool(item.get("ambiguous")),
                    "overlap": round(corpus.overlap(q, sec), 4), "source": "v2",
                }, ensure_ascii=False) + "\n")
        print(f"{doc_id} {d['heading']}: {usage}, 통과")
        for w in warnings:
            print(f"    - 경고: {w}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="실제로 API를 호출한다(기본은 추정만)")
    ap.add_argument("--only", type=int, help="문서 번호 하나만")
    ap.add_argument("--force", action="store_true", help="이미 있는 문서도 다시 만든다(파일에 이어 쓰므로 먼저 지울 것)")
    a = ap.parse_args()
    secs = corpus.load_corpus()
    docs = [d for d in topics.NEW_DOCS if a.only in (None, d["no"])]
    if not docs:
        raise SystemExit(f"문서 번호 {a.only}가 없다")
    if not a.run:
        dry_run(docs, secs)
    else:
        run(docs, secs, a.force)


if __name__ == "__main__":
    main()
