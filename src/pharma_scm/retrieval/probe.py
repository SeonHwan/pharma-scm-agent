"""배포된 환경(컨테이너, Fargate)에서 규정 검색의 시작 시간, 질의 지연, 메모리를 잰다.

이미지 안에는 eval/이 없으므로 질의 10개를 여기에 둔다(벤치마크 v1 문항과 비슷한 길이의 현장 질문).
서버와 별도 프로세스로 모델과 색인을 다시 읽으므로, 메모리는 이 프로세스의 값이고 서버 프로세스의 값이 아니다.

    uv run --no-sync python -m pharma_scm.retrieval.probe
"""

import resource
import statistics
import time

from . import index

QUERIES = [
    "냉장 품목 보관 온도 기준이 어떻게 돼?",
    "입고 수량이 발주와 다르면 언제 입고를 보류해?",
    "유통기한 임박 재고는 어떻게 처리해야 해?",
    "회수 명령이 내려오면 몇 시간 안에 격리해야 해?",
    "운송 중에 온도 일탈이 생기면 누가 판단해?",
    "반품 들어온 약은 다시 팔 수 있어?",
    "라벨이 훼손된 제품은 재라벨해도 돼?",
    "재고 실사에서 차이가 나면 누가 조정 승인을 해?",
    "마약류 폐기할 때 입회는 누가 해?",
    "외주 창고 온도 기록은 얼마나 보관해야 해?",
]
REPEAT = 3  # 질의 10개를 3번 돌린 30회로 p50, p95를 잰다(처음 1회는 준비 호출로 버린다)


def main():
    started = time.perf_counter()
    idx = index.load()
    load_s = time.perf_counter() - started
    idx.search(QUERIES[0])
    ms = []
    for _ in range(REPEAT):
        for q in QUERIES:
            t = time.perf_counter()
            idx.search(q)
            ms.append((time.perf_counter() - t) * 1000)
    ms.sort()
    p95 = ms[max(0, round(0.95 * len(ms)) - 1)]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"모델+색인 로드 {load_s:.1f}초, 질의 {len(ms)}회 p50 {statistics.median(ms):.0f}ms p95 {p95:.0f}ms, "
          f"이 프로세스 최대 메모리 {rss:,.0f}MB")


if __name__ == "__main__":
    main()
