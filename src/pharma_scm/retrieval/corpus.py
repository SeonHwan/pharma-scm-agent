"""벤치마크 코퍼스(기존 sop/ + eval/rag/corpus_v2/)를 섹션 단위로 읽고, 질의와 섹션의 어휘 겹침을 계산한다."""

import re

from .register import corpus_files

H1 = re.compile(r"^# (SOP-\d+) (.+)$")
H2 = re.compile(r"^## (SOP-\d+-\d+) (.+)$")


def parse_text(text):
    """문서 하나를 섹션 목록으로 바꾼다. 항목: section_id, doc_id, doc_title, title, body."""
    doc_id = doc_title = None
    secs, cur = [], None
    for line in text.splitlines():
        if m := H1.match(line):
            doc_id, doc_title = m.groups()
        elif m := H2.match(line):
            cur = {"section_id": m.group(1), "doc_id": doc_id, "doc_title": doc_title,
                   "title": m.group(2), "lines": []}
            secs.append(cur)
        elif cur is not None and not line.startswith(">"):
            cur["lines"].append(line)
    for s in secs:
        s["body"] = " ".join(x.strip() for x in s.pop("lines") if x.strip())
    return secs


def load_corpus():
    """벤치마크 코퍼스 전체 섹션(문서 번호와 섹션 번호 순)."""
    out = []
    for path in corpus_files():
        out.extend(parse_text(path.read_text(encoding="utf-8")))
    return out


def section_text(sec):
    return f"{sec['title']} {sec['body']}"


def grams(text):
    """공백을 없앤 소문자 글자 2-gram 목록(현재 search_sop의 토큰과 같은 방식)."""
    t = re.sub(r"\s+", "", text.lower())
    return [t[i:i + 2] for i in range(len(t) - 1)]


def overlap(query, sec):
    """질의의 글자 2-gram 중 정답 섹션(제목과 본문)에 들어 있는 것의 비율(사전 등록 §3의 정의)."""
    q = grams(query)
    if not q:
        return 0.0
    s = set(grams(section_text(sec)))
    return sum(1 for g in q if g in s) / len(q)
