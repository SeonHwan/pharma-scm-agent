"""규정 검색 벤치마크의 새 SOP 문서를 Claude로 생성한다(docs/rag_eval_protocol.md §2, §9).

기본은 --dry-run이라 API를 부르지 않고 호출 수와 토큰·비용 추정만 보여 준다. 실제 호출은 --run을 줘야 한다.
이미 만든 파일은 건드리지 않는다(--force로만 덮어쓴다). 생성한 파일은 고정해서 쓰고 다시 만들지 않는다.

    uv run python -m pharma_scm.retrieval.gen_corpus                # 추정만
    uv run python -m pharma_scm.retrieval.gen_corpus --only 11 --run  # 문서 하나만 실제 생성(시험)
    uv run python -m pharma_scm.retrieval.gen_corpus --run            # 남은 문서 전부
"""

import argparse
import json
import re
import time

from .. import config
from . import topics

MODEL = "claude-sonnet-5-5"  # 사전 등록 9-1: 코퍼스 생성 모델
EFFORT = "medium"  # 생각 깊이. 글쓰기 작업이라 기본(high)보다 낮춰 출력 토큰을 줄인다
MAX_TOKENS = 8000
# 단가(100만 토큰당 달러). 2026-11-03에 확인한 값이라 바뀌었을 수 있다.
PRICE_IN, PRICE_OUT = 2.0, 10.0

OUT_DIR = config.SOP_DIR  # 생성 당시에는 eval/rag/corpus_v2/였고 이후 sop/로 합쳤다(protocol 9-9)
LOG_PATH = config.ROOT / "eval" / "rag" / "generation_log.jsonl"
NOTICE = "> 이 문서는 포트폴리오용 합성 SOP이며 실제 GMP·사내 규정이 아니다."

SYSTEM = (
    "당신은 의약품 유통 물류센터의 표준작업절차서(SOP)를 합성하는 작성자다. 실제 규정이 아니라 포트폴리오용 "
    "합성 문서를 쓴다. 출력은 마크다운 문서 하나뿐이고, 설명, 코드 블록, 머리말을 붙이지 않는다."
)

PROMPT = """새 SOP 문서를 하나 쓴다.

[문서] SOP-{no} {heading}
[다루는 범위] {scope}
[섹션 수] 정확히 {k}개

[형식 (정확히 지킨다)]
# SOP-{no} {heading}

{notice}

## SOP-{no}-1 <섹션 제목>
<본문 1~3문장>

(섹션 id는 SOP-{no}-1부터 SOP-{no}-{k}까지 순서대로)

[작성 규칙]
1. 섹션마다 그 섹션에만 있는 고유한 사실을 하나 이상 넣는다. 수치(시간, 일수, 비율, 횟수), 기한, 승인자(직책), 조건 중 하나다.
2. 아래 '혼동 문서'와 같은 종류의 규정이 나오면, 같은 종류의 수치와 승인자를 혼동 문서와 **다른 값**으로 쓴다. 같은 주제라도 단계와 대상이 다르다는 것이 드러나야 한다.
3. 섹션 제목은 구체적으로 쓴다("개요", "일반 원칙" 같은 제목은 금지). 같은 문서 안에서 제목이 겹치지 않게 한다.
4. 본문은 1~3문장, 40~200자. 혼동 문서의 문장을 그대로 베끼지 않는다.
5. 실제 약품명, 실제 회사명, 실제 법령 조문 번호는 쓰지 않는다.
6. 다른 섹션이나 다른 문서를 가리키는 표현("앞 절 참조", "SOP-04 참조" 등)을 쓰지 않는다. 섹션은 단독으로 읽혀도 뜻이 통해야 한다.

[문체 예시: 기존 문서]
{style_example}

[혼동 문서 (이 문서와 주제가 겹친다)]
{confusables}
"""

GENERIC_TITLES = {"개요", "일반 원칙", "목적", "적용 범위", "총칙", "기본 원칙"}
H1 = re.compile(r"^# (SOP-\d+) (.+)$")
H2 = re.compile(r"^## (SOP-\d+-\d+) (.+)$")
# 수치와 단위(예: 10분, 2~8도, 영업일 기준 5영업일, 3년). 같은 문서 안의 중복 확인에 쓴다.
FACT = re.compile(r"\d+(?:~\d+)?\s*(?:영업일|도|분|시간|일|주|개월|년|회|%|퍼센트)")


def n_sections(no):
    """문서마다 8개 또는 9개. 번호의 홀짝으로 정해 실행마다 같다."""
    lo, hi = topics.SECTIONS_PER_DOC
    return hi if no % 2 else lo


def read_existing(no):
    paths = sorted((config.SOP_DIR).glob(f"SOP-{no:02d}_*.md"))
    paths += sorted(OUT_DIR.glob(f"SOP-{no}_*.md"))
    return paths[0].read_text(encoding="utf-8").strip() if paths else None


def build_prompt(doc):
    confusables = []
    for no in doc["confusable"]:
        text = read_existing(no)
        if text:
            confusables.append(text)
    return PROMPT.format(
        no=doc["no"], heading=doc["heading"], scope=doc["scope"], k=n_sections(doc["no"]),
        notice=NOTICE, style_example=read_existing(3),
        confusables="\n\n---\n\n".join(confusables) or "(없음)",
    )


def validate(text, doc):
    """형식과 규칙을 코드로 검사한다. (심각한 문제, 경고)를 돌려준다. 심각한 문제가 있으면 .rejected로 저장한다.

    경고는 사람이 볼 것이다: 숫자가 없는 섹션(승인자나 조건이 고유 사실일 수 있다), 한 문서 안에서 같은 수치와
    단위가 둘 이상의 섹션에 나오는 경우(질의 하나에 여러 섹션이 맞을 수 있다).
    """
    problems, warnings = [], []
    no, k = doc["no"], n_sections(doc["no"])
    lines = text.strip().splitlines()
    if not lines or lines[0] != f"# SOP-{no} {doc['heading']}":
        problems.append(f"첫 줄이 '# SOP-{no} {doc['heading']}'이 아니다")
    if NOTICE not in text:
        problems.append("합성 고지 문장이 없다")
    secs, cur = [], None
    for line in lines[1:]:
        if m := H2.match(line):
            cur = [m.group(1), m.group(2), []]
            secs.append(cur)
        elif cur is not None:
            cur[2].append(line)
    if len(secs) != k:
        problems.append(f"섹션 수가 {len(secs)}개다(기대 {k}개)")
    titles, seen = set(), {}
    for i, (sid, title, body) in enumerate(secs, 1):
        text_body = " ".join(x.strip() for x in body if x.strip())
        if sid != f"SOP-{no}-{i}":
            problems.append(f"섹션 id가 순서와 다르다: {sid}(기대 SOP-{no}-{i})")
        if title in GENERIC_TITLES:
            problems.append(f"{sid} 제목이 너무 일반적이다: {title}")
        if title in titles:
            problems.append(f"{sid} 제목이 겹친다: {title}")
        titles.add(title)
        if not 40 <= len(text_body) <= 300:
            problems.append(f"{sid} 본문 길이가 {len(text_body)}자다(40~300)")
        if re.search(r"앞 절|위 절|아래 절|다음 절|SOP-\d", text_body):
            problems.append(f"{sid} 본문이 다른 섹션이나 문서를 가리킨다")
        if not re.search(r"\d", text_body):
            warnings.append(f"{sid} 본문에 숫자가 없다(승인자나 조건이 고유 사실인지 확인)")
        for tok in set(FACT.findall(text_body)):
            seen.setdefault(tok, []).append(sid)
    for tok, sids in seen.items():
        if len(sids) > 1:
            warnings.append(f"수치 '{tok}'가 {', '.join(sids)}에 함께 나온다(질의 하나에 여러 섹션이 맞을 수 있다)")
    return problems, warnings


def out_path(doc):
    return OUT_DIR / f"SOP-{doc['no']}_{doc['title']}.md"


def dry_run(docs):
    print(f"모델 {MODEL}, 단가 입력 ${PRICE_IN}/출력 ${PRICE_OUT} per 100만 토큰(2026-11-03 확인값)")
    print("토큰 수는 글자 수로 추정한다(한국어는 정확한 비율을 모르므로 1토큰=1글자를 상한, 2글자를 하한으로 둔다).")
    tot_in = tot_out = 0
    for d in docs:
        chars = len(SYSTEM) + len(build_prompt(d))
        out_chars = n_sections(d["no"]) * 180 + 60
        tot_in += chars
        tot_out += out_chars
        print(f"  SOP-{d['no']} {d['heading']}: 호출 1회, 입력 약 {chars:,}자, 출력 약 {out_chars:,}자")
    print(f"호출 {len(docs)}회, 입력 {tot_in:,}자, 출력 {tot_out:,}자")
    # 출력에는 생각(thinking) 토큰이 더해진다. 글자 수 추정의 2배까지를 상한으로 본다.
    lo = tot_in / 2 / 1e6 * PRICE_IN + tot_out / 2 / 1e6 * PRICE_OUT
    hi = tot_in / 1e6 * PRICE_IN + tot_out * 2 / 1e6 * PRICE_OUT
    print(f"비용 추정: ${lo:.2f} ~ ${hi:.2f}(생각 토큰 포함 상한). 실제는 첫 호출의 usage로 다시 계산한다.")


def run(docs, force):
    import anthropic

    config.load_env()
    client = anthropic.Anthropic()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for d in docs:
        path = out_path(d)
        if path.exists() and not force:
            print(f"SOP-{d['no']}: 이미 있어서 건너뜀")
            continue
        started = time.time()
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            output_config={"effort": EFFORT},
            messages=[{"role": "user", "content": build_prompt(d)}],
        )
        u = resp.usage
        record = {"no": d["no"], "model": MODEL, "stop_reason": resp.stop_reason,
                  "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "seconds": round(time.time() - started, 1), "request_id": resp._request_id}
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if resp.stop_reason == "refusal":
            raise SystemExit(f"SOP-{d['no']}: 모델이 거절했다. 폴백 없이 중단한다: {resp.stop_details}")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        problems, warnings = validate(text, d)
        target = path if not problems else path.with_suffix(".md.rejected")
        target.write_text(text + "\n", encoding="utf-8")
        status = "통과" if not problems else f"검사 문제 {len(problems)}건 -> {target.name}"
        print(f"SOP-{d['no']} {d['heading']}: 입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} 토큰, {status}")
        for p in problems:
            print(f"    - 문제: {p}")
        for w in warnings:
            print(f"    - 경고: {w}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="실제로 API를 호출한다(기본은 추정만)")
    ap.add_argument("--only", type=int, help="문서 번호 하나만")
    ap.add_argument("--force", action="store_true", help="이미 있는 파일도 다시 만든다")
    a = ap.parse_args()
    docs = [d for d in topics.NEW_DOCS if a.only in (None, d["no"])]
    if not docs:
        raise SystemExit(f"문서 번호 {a.only}가 없다")
    if not a.run:
        dry_run(docs)
    else:
        run(docs, a.force)


if __name__ == "__main__":
    main()
