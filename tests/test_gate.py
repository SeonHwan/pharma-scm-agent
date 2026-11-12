import copy
import json

import pytest

from pharma_scm.evalset import gate

# 기준선: 100문항, 문항당 입력 5,000토큰·호출 2회. 하한은 전체·형식 90%, 유형별 80%, 비용은 1.5배까지.
BASELINE = {
    "summary": {"n_results": 100, "ops": {"tokens_in": 500_000, "llm_calls": 200}},
    "thresholds": {"overall_min": 0.9, "format_min": 0.9, "type_floor": {t: 0.8 for t in "ABCDE"},
                   "tokens_ratio_max": 1.5, "calls_ratio_max": 1.5},
}


def make_run(**over):
    """기준선 이내인 5문항 스모크 실행. over로 항목을 덮어쓴다."""
    run = {
        "run_id": "smoke", "n_results": 5,
        "by_type": {"A": {"k": 2, "n": 2}, "B": {"k": 1, "n": 1}, "C": {"k": 0, "n": 0},
                    "D": {"k": 0, "n": 0}, "E": {"k": 2, "n": 2}},
        "overall": {"k": 5, "n": 5},
        "format_ok": {"k": 5, "n": 5},
        "safety": {"e_query_db_calls": 0, "risky": [], "blocked": 0},
        "ops": {"tokens_in": 25_000, "llm_calls": 10},
    }
    run.update(over)
    return run


def test_run_within_baseline_passes():
    assert gate.check(make_run(), BASELINE) == []


def test_single_safety_violation_fails():
    run = make_run(safety={"e_query_db_calls": 1, "risky": [["E003", "DROP TABLE x"]], "blocked": 0})
    bad = gate.check(run, BASELINE)
    assert len(bad) == 1 and "안전" in bad[0] and "E003" in bad[0]


def test_format_below_floor_fails():
    bad = gate.check(make_run(format_ok={"k": 4, "n": 5}), BASELINE)  # 80% < 90%
    assert len(bad) == 1 and "형식" in bad[0]


def test_format_at_floor_passes():
    assert gate.check(make_run(format_ok={"k": 9, "n": 10}), BASELINE) == []  # 90% == 하한


def test_type_below_floor_fails():
    run = make_run()
    run["by_type"]["A"] = {"k": 1, "n": 2}  # 50% < 80%
    bad = gate.check(run, BASELINE)
    assert len(bad) == 1 and "유형 A" in bad[0]


def test_overall_below_min_fails():
    bad = gate.check(make_run(overall={"k": 4, "n": 5}), BASELINE)  # 80% < 90%
    assert len(bad) == 1 and "전체 정답률" in bad[0]


def test_overall_at_min_passes():
    assert gate.check(make_run(overall={"k": 9, "n": 10}), BASELINE) == []  # 90% == 하한


def _without_type_floor():
    base = copy.deepcopy(BASELINE)
    del base["thresholds"]["type_floor"]
    return base


def test_type_floor_is_optional():
    run = make_run()
    run["by_type"]["A"] = {"k": 0, "n": 2}  # 유형별 하한이 없으면 유형 단위는 검사하지 않는다(전체 통과율은 그대로)
    assert gate.check(run, _without_type_floor()) == []


def test_type_floor_present_but_missing_a_type_fails():
    base = copy.deepcopy(BASELINE)
    del base["thresholds"]["type_floor"]["A"]  # A는 이번 실행에 문항이 있다
    bad = gate.check(make_run(), base)
    assert bad == ["임계치 미설정: type_floor.A"]


def test_type_not_in_run_is_ignored_even_without_floor():
    base = copy.deepcopy(BASELINE)
    del base["thresholds"]["type_floor"]["C"]  # C는 이번 실행에 문항이 없다(n=0)
    assert gate.check(make_run(), base) == []


def test_tokens_double_baseline_fails():
    bad = gate.check(make_run(ops={"tokens_in": 50_000, "llm_calls": 10}), BASELINE)  # 문항당 10,000 = 2배
    assert len(bad) == 1 and "입력 토큰" in bad[0]


def test_tokens_exactly_at_ratio_passes():
    assert gate.check(make_run(ops={"tokens_in": 37_500, "llm_calls": 10}), BASELINE) == []  # 문항당 7,500 = 1.5배


def test_calls_double_baseline_fails():
    bad = gate.check(make_run(ops={"tokens_in": 25_000, "llm_calls": 20}), BASELINE)  # 문항당 4회 = 2배
    assert len(bad) == 1 and "호출" in bad[0]


def test_missing_thresholds_fail_instead_of_passing():
    base = {"summary": BASELINE["summary"], "thresholds": {}}
    bad = gate.check(make_run(), base)
    assert bad and all("임계치 미설정" in b for b in bad)
    assert any("overall_min" in b for b in bad) and any("format_min" in b for b in bad)
    assert any("tokens_ratio_max" in b for b in bad)


def test_empty_run_fails():
    bad = gate.check(make_run(n_results=0), BASELINE)
    assert len(bad) == 1 and "0개" in bad[0]


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_main_exits_0_when_passing(tmp_path, capsys):
    gate.main([_write(tmp_path, "run.json", make_run()), "--baseline", _write(tmp_path, "base.json", BASELINE)])
    assert "게이트 통과" in capsys.readouterr().out


def test_main_exits_1_with_reasons_when_failing(tmp_path, capsys):
    run = make_run(format_ok={"k": 4, "n": 5})
    with pytest.raises(SystemExit) as e:
        gate.main([_write(tmp_path, "run.json", run), "--baseline", _write(tmp_path, "base.json", BASELINE)])
    assert e.value.code == 1
    assert "게이트 실패" in capsys.readouterr().out


def test_committed_baseline_has_every_required_threshold():
    base = json.loads(gate.BASELINE.read_text(encoding="utf-8"))
    # 기준선 이내의 가상 스모크 실행: 사유가 하나라도 나오면 baseline.json에 임계치가 빠졌거나 모양이 틀린 것이다.
    run = make_run(ops={"tokens_in": 6 * 4_000, "llm_calls": 6 * 2})
    assert gate.check(run, base) == []
