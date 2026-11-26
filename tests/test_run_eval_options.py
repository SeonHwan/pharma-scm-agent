import pytest

from pharma_scm.evalset import run_eval

QS = [{"id": "A001", "type": "A"}, {"id": "B001", "type": "B"}, {"id": "E001", "type": "E"}]


def test_parse_ids_splits_commas_and_whitespace_and_dedups():
    assert run_eval.parse_ids("A001,B001 E001\nA001") == ["A001", "B001", "E001"]
    assert run_eval.parse_ids("") == []


def test_select_questions_all_when_no_ids():
    assert run_eval.select_questions(QS, None) == QS


def test_select_questions_keeps_file_order():
    assert [q["id"] for q in run_eval.select_questions(QS, ["E001", "A001"])] == ["A001", "E001"]


def test_select_questions_rejects_unknown_id():
    with pytest.raises(ValueError, match="A999"):
        run_eval.select_questions(QS, ["A001", "A999"])


def test_default_run_id():
    assert run_eval.default_run_id(None) == f"main_{run_eval.PROMPT_VERSION}"
    assert run_eval.default_run_id("0123456789abcdef") == f"main_{run_eval.PROMPT_VERSION}_01234567"


def test_count_problems_excludes_error_rows_from_format_violations():
    rs = [{"error": None, "grade": {"format_ok": True}},
          {"error": None, "grade": {"format_ok": False}},
          {"error": "exception:X", "grade": {"format_ok": False}}]
    assert run_eval.count_problems(rs) == (1, 1)


def test_dry_run_with_ids_and_sha_plans_only_selected(capsys):
    run_eval.main(["--dry-run", "--ids", "A001,B001,E001", "--sha", "0123456789abcdef"])
    out = capsys.readouterr().out
    assert f"run_id=main_{run_eval.PROMPT_VERSION}_01234567" in out
    assert "문항 3개 중 실행할 것 3개" in out
    assert "API 호출은 하지 않았다." in out


def test_unknown_id_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        run_eval.main(["--dry-run", "--ids", "A001,Z999"])
    assert e.value.code == 2
    assert "Z999" in capsys.readouterr().err


@pytest.fixture
def failing_run(monkeypatch, tmp_path):
    """모든 문항이 예외로 실패하는 실행(API 호출 없음). 결과는 임시 폴더에 쓴다."""
    monkeypatch.setattr(run_eval.config, "ROOT", tmp_path)
    monkeypatch.setattr(run_eval, "build_graph", lambda: None)
    monkeypatch.setattr(run_eval, "run_one", lambda q, graph, out_dir, *rest: {
        "id": q["id"], "error": "exception:X", "grade": {"pass": False, "reason": "x", "format_ok": False}})


def test_strict_exits_1_on_execution_error(failing_run, capsys):
    with pytest.raises(SystemExit) as e:
        run_eval.main(["--ids", "A001", "--strict"])
    assert e.value.code == 1
    assert "실행 오류 1건" in capsys.readouterr().out


def test_without_strict_exits_normally_on_execution_error(failing_run, capsys):
    run_eval.main(["--ids", "A001"])
    assert "실행 오류 1건" in capsys.readouterr().out
