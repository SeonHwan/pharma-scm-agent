from pharma_scm.retrieval import benchmark_data, corpus


def test_benchmark_size_and_sources():
    items = benchmark_data.load_benchmark()
    assert len(items) == 146
    assert sum(it["source"] == "v1" for it in items) == 20
    assert sum(it["source"] == "v2" for it in items) == 126


def test_gold_sections_exist():
    ids = {s["section_id"] for s in corpus.load_corpus()}
    assert all(it["gold"] in ids for it in benchmark_data.load_benchmark())


def test_low_overlap_is_at_or_below_median():
    # 사전 등록 규칙: 중앙값 이하가 낮은 겹침. 경계값이 높은 겹침으로 새지 않아야 한다.
    items = benchmark_data.load_benchmark()
    low = [it["overlap"] for it in items if it["low_overlap"]]
    high = [it["overlap"] for it in items if not it["low_overlap"]]
    assert max(low) <= min(high)
    assert len(low) >= len(items) // 2
