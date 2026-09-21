from fusebench.benchmark.scheduler import build_paired_schedule


def test_schedule_is_seeded_interleaved_and_pair_adjacent() -> None:
    case_ids = [f"CASE_{index}" for index in range(20)]

    first = build_paired_schedule(case_ids, seed=91)
    second = build_paired_schedule(case_ids, seed=91)
    different = build_paired_schedule(case_ids, seed=92)

    assert first == second
    assert first != different
    assert len(first) == 40
    for index, case_id in enumerate(case_ids):
        pair = first[index * 2 : index * 2 + 2]
        assert {item.case_id for item in pair} == {case_id}
        assert {item.system for item in pair} == {"terra_only", "terra_jev"}
        assert [item.order_index for item in pair] == [index * 2, index * 2 + 1]
    assert {first[index].system for index in range(0, len(first), 2)} == {
        "terra_only",
        "terra_jev",
    }
