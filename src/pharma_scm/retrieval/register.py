"""규정 문서(sop/)와 벤치마크 질의의 고정 파일 목록과 md5를 eval/rag/registered.json에 등록한다(docs/rag_eval_protocol.md §2).

    uv run python -m pharma_scm.retrieval.register

등록은 파일을 고정하는 순간에만 한다. 등록 뒤에 파일이 바뀌면 tests/test_rag_registration.py가 실패한다.
의도한 변경이면 이 명령으로 다시 등록하고, 사전 등록 문서(docs/rag_eval_protocol.md)에 새 날짜의 절로 이유를 적는다.
"""

import hashlib
import json

from .. import config

REGISTERED = config.ROOT / "eval" / "rag" / "registered.json"


def corpus_files():
    """코퍼스 = sop/ 문서 전체. 서비스하는 규정 문서와 벤치마크가 같은 파일을 쓴다."""
    return sorted(config.SOP_DIR.glob("SOP-*.md"))


def md5_map():
    return {str(p.relative_to(config.ROOT)): hashlib.md5(p.read_bytes()).hexdigest()
            for p in corpus_files()}


def main():
    data = json.loads(REGISTERED.read_text(encoding="utf-8")) if REGISTERED.exists() else {}
    data["corpus_md5"] = md5_map()
    REGISTERED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"코퍼스 {len(data['corpus_md5'])}개 파일의 md5를 등록했다: {REGISTERED.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
