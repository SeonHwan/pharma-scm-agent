import json

from pharma_scm import config
from pharma_scm.evalset import report_v2, run_eval
from pharma_scm.evalset.build_evalset_v2 import assign_split
from pharma_scm.evalset.grader import grade


def test_v2_file_shape_and_split():
    qs = run_eval.load_questions("v2")
    assert len(qs) == 156 and len({q["id"] for q in qs}) == 156
    for t, n in (("G", 126), ("H", 30)):
        sub = [q for q in qs if q["type"] == t]
        assert len(sub) == n
        assert sum(q["split"] == "dev" for q in sub) == n // 2


def test_g_questions_match_registered_queries():
    src = [json.loads(x) for x in (config.ROOT / "eval/rag/queries_v2_final.jsonl").read_text("utf-8").splitlines()]
    g = [q for q in run_eval.load_questions("v2") if q["type"] == "G"]
    assert [(q["question"], q["gold"]["value"]) for q in g] == [(r["query"], r["section_id"]) for r in src]


def test_split_is_deterministic():
    items = [{"id": f"X{i:03d}", "type": "X"} for i in range(10)]
    a = [q["split"] for q in assign_split([dict(q) for q in items])]
    b = [q["split"] for q in assign_split([dict(q) for q in items])]
    assert a == b and a.count("dev") == 5


def test_grader_handles_v2_kinds():
    h_set = {"id": "H001", "type": "H", "expected_tools": ["query_db"], "gold": {"kind": "set", "value": ["SKU-015"]}}
    assert grade(h_set, "근거\n최종 답: SKU-015", ["query_db"])["pass"]
    h_neg = {"id": "H022", "type": "H", "expected_tools": ["query_db"], "gold": {"kind": "number", "value": -36.1}}
    assert grade(h_neg, "최종 답: -36.1%", ["query_db"])["pass"]
    g = {"id": "G001", "type": "G", "expected_tools": ["search_sop"], "gold": {"kind": "sections", "value": "SOP-12-1"}}
    assert grade(g, "최종 답: SOP-12-1", ["search_sop"])["pass"]


def test_mcnemar_exact():
    assert report_v2.mcnemar_exact(0, 0) == 1.0
    assert abs(report_v2.mcnemar_exact(0, 6) - 0.03125) < 1e-12  # 2 * (1/2)^6
    assert report_v2.mcnemar_exact(3, 3) == 1.0


def test_split_option_requires_v2():
    import pytest

    with pytest.raises(SystemExit):
        run_eval.main(["--split", "dev", "--dry-run"])
