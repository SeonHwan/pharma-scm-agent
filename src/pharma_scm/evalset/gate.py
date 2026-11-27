"""평가 실행의 집계(report --json)를 기준선(eval/baseline.json)과 비교해 통과·실패를 판정한다.

실행: uv run python -m pharma_scm.evalset.gate <집계.json> [--baseline eval/baseline.json]
실패하면 사유를 출력하고 종료코드 1로 끝난다. 임계치가 비어 있으면 통과가 아니라 실패다(검사 없이 통과하는 것을 막는다).

baseline.json 모양:
  {"summary": <기준 실행의 report --json>,
   "thresholds": {"overall_min": 0~1, "format_min": 0~1,
                  "tokens_ratio_max": 배수, "calls_ratio_max": 배수,
                  "type_floor": {"A": 0~1, ...}   # 선택. 있을 때만 유형별로 검사한다}}
임계치는 repeat-variance 측정 뒤에 사전 등록하고, 기준선은 자동 갱신하지 않는다(사람이 PR로 갱신).
스모크는 문항이 유형당 1~2개라 유형별 통과율이 0·50·100%뿐이므로 전체 통과율(overall_min)로 판정한다.
"""

import argparse
import json
import sys

from .. import config

BASELINE = config.ROOT / "eval" / "baseline.json"


def _rate(m):
    return m["k"] / m["n"] if m["n"] else None


def _need(thresholds, *path):
    """임계치를 꺼낸다. 없으면 None."""
    cur = thresholds
    for key in path:
        if not isinstance(cur, dict) or cur.get(key) is None:
            return None
        cur = cur[key]
    return cur


def check(run, baseline):
    """위반 사유 목록을 돌려준다. 비어 있으면 통과."""
    bad = []
    if run["n_results"] == 0:
        return ["결과가 0개다(아무것도 실행되지 않았다)"]
    th = baseline.get("thresholds") or {}

    risky = run["safety"]["risky"]
    if risky:
        bad.append(f"안전: 쓰기·시스템 SQL 시도 {len(risky)}건 ({', '.join(r[0] for r in risky)})")

    floor = _need(th, "format_min")
    if floor is None:
        bad.append("임계치 미설정: format_min")
    elif _rate(run["format_ok"]) < floor:
        m = run["format_ok"]
        bad.append(f"형식 준수율 {m['k']}/{m['n']} = {_rate(m):.0%} < 하한 {floor:.0%}")

    floor = _need(th, "overall_min")
    if floor is None:
        bad.append("임계치 미설정: overall_min")
    elif _rate(run["overall"]) < floor:
        m = run["overall"]
        bad.append(f"전체 정답률 {m['k']}/{m['n']} = {_rate(m):.0%} < 하한 {floor:.0%}")

    # 유형별 하한은 선택 규칙이다. type_floor를 두었다면 이번 실행에 문항이 있는 유형은 모두 하한이 있어야 한다.
    if th.get("type_floor") is not None:
        for t, m in run["by_type"].items():
            if m["n"] == 0:
                continue
            floor = _need(th, "type_floor", t)
            if floor is None:
                bad.append(f"임계치 미설정: type_floor.{t}")
            elif _rate(m) < floor:
                bad.append(f"유형 {t} 정답률 {m['k']}/{m['n']} = {_rate(m):.0%} < 하한 {floor:.0%}")

    base = baseline["summary"]
    for label, key, ratio_key in (("입력 토큰", "tokens_in", "tokens_ratio_max"),
                                  ("LLM 호출 수", "llm_calls", "calls_ratio_max")):
        ratio = _need(th, ratio_key)
        if ratio is None:
            bad.append(f"임계치 미설정: {ratio_key}")
            continue
        per_q = run["ops"][key] / run["n_results"]
        base_per_q = base["ops"][key] / base["n_results"]
        if per_q > base_per_q * ratio:
            bad.append(f"{label} 문항당 {per_q:,.0f} > 기준선 {base_per_q:,.0f}의 {ratio}배")
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("summary", help="report --json으로 만든 집계 파일")
    ap.add_argument("--baseline", default=str(BASELINE))
    a = ap.parse_args(argv)
    with open(a.summary, encoding="utf-8") as fp:
        run = json.load(fp)
    with open(a.baseline, encoding="utf-8") as fp:
        baseline = json.load(fp)
    bad = check(run, baseline)
    if bad:
        print(f"게이트 실패 ({len(bad)}건)")
        for b in bad:
            print(" -", b)
        sys.exit(1)
    print(f"게이트 통과: run {run['run_id']} ({run['n_results']}개)")


if __name__ == "__main__":
    main()
