import hashlib
import json

from pharma_scm.retrieval import finalize_queries, register

REGISTERED = json.loads(register.REGISTERED.read_text(encoding="utf-8"))

# 검색 평가 결과는 "어떤 코퍼스로 측정했는가"가 고정돼 있어야 비교할 수 있다.
HINT = ("의도한 변경이면 `uv run python -m pharma_scm.retrieval.register`로 다시 등록하고 "
        "사전 등록 문서에 새 날짜의 절로 이유를 적는다.")


def test_corpus_md5():
    got = register.md5_map()
    assert got == REGISTERED["corpus_md5"], f"벤치마크 코퍼스가 등록값과 다르다. {HINT}"


def test_corpus_size():
    # 사전 등록: 문서 약 25개, 섹션 약 150~200개
    got = register.md5_map()
    assert len(got) == 25
    sections = sum(p.read_text(encoding="utf-8").count("\n## SOP-") for p in register.corpus_files())
    assert 150 <= sections <= 200, f"섹션 수 {sections}개가 사전 등록 범위(150~200)를 벗어난다"


def test_final_queries_md5():
    got = hashlib.md5(finalize_queries.FINAL.read_bytes()).hexdigest()
    assert got == REGISTERED["queries_v2_final_md5"], f"최종 질의 파일이 등록값과 다르다. {HINT}"


def test_final_queries_count():
    rows = [json.loads(line) for line in finalize_queries.FINAL.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == REGISTERED["queries_v2_final_count"] == 126
    assert len({r["section_id"] for r in rows}) == len(rows), "질의가 섹션마다 하나여야 한다"
