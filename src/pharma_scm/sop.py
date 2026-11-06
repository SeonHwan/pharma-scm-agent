"""sop/*.md를 sop_sections 행으로 파싱한다. 문서 제목은 '# SOP-nn 제목', 섹션은 '## SOP-nn-m 제목'."""

import re

from . import config

_H1 = re.compile(r"^# (SOP-\d+) (.+)$")
_H2 = re.compile(r"^## (SOP-\d+-\d+) (.+)$")


def read_sections():
    rows = []
    for path in sorted(config.SOP_DIR.glob("SOP-*.md")):
        doc_id = doc_title = None
        cur = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := _H1.match(line):
                doc_id, doc_title = m.groups()
            elif m := _H2.match(line):
                cur = [m.group(1), doc_id, doc_title, m.group(2), []]
                rows.append(cur)
            elif cur is not None:
                cur[4].append(line)
        assert doc_id, f"{path.name}: H1 없음"
    return [(sid, d, dt, t, "\n".join(b).strip()) for sid, d, dt, t, b in rows]


def load(conn):
    rows = read_sections()
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sop_sections (section_id, doc_id, doc_title, title, body) "
            "VALUES (%s, %s, %s, %s, %s)", rows)
    return rows
