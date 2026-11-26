import json

import numpy as np
import pytest

from pharma_scm.retrieval import corpus, index
from pharma_scm.retrieval.register import md5_map

# 모델 없이 검색 흐름을 시험한다: 섹션마다 고유한 축을 가진 가짜 벡터와, 질의 문자열에 섹션 id가 있으면
# 그 축을 가리키는 가짜 질의 임베딩을 쓴다.


def fake_index():
    sections = corpus.load_corpus()
    ids = [s["section_id"] for s in sections]
    vectors = np.eye(len(ids), dtype=np.float32)

    def embed(q):
        v = np.zeros(len(ids), dtype=np.float32)
        for i, sid in enumerate(ids):
            if sid in q:
                v[i] = 1.0
        return v

    return sections, vectors, embed


def test_search_returns_k_sections_with_fields():
    sections, vectors, embed = fake_index()
    idx = index.SopIndex(sections, vectors, embed)
    got = idx.search("냉장 보관 온도 기록 SOP-02-1", k=3)
    assert len(got) == 3
    assert set(got[0]) == {"section_id", "doc_title", "title", "body", "score"}
    assert got[0]["section_id"] == "SOP-02-1"


def test_load_rejects_stale_index(tmp_path):
    sections, vectors, embed = fake_index()
    np.save(tmp_path / index.VECTORS, vectors)
    meta = {"model": "fake", "section_ids": [s["section_id"] for s in sections], "corpus_md5": md5_map()}
    (tmp_path / index.META).write_text(json.dumps(meta), encoding="utf-8")
    assert len(index.load(tmp_path, embed_query=embed).search("회수 SOP-05-1", k=1)) == 1

    meta["corpus_md5"] = {**meta["corpus_md5"], "sop/SOP-01_입고검수.md": "0" * 32}
    (tmp_path / index.META).write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(RuntimeError):
        index.load(tmp_path, embed_query=embed)
