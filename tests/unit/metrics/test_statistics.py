import pytest

from fusebench.contracts.actions import Action
from fusebench.metrics.statistics import mcnemar_test, paired_bootstrap


def paired_records(make_record):
    outcomes = [
        (Action.WAIT, Action.WAIT, Action.WAIT),
        (Action.WAIT, Action.REFUND, Action.WAIT),
        (Action.WAIT, Action.WAIT, Action.REFUND),
    ]
    records = []
    for index, (gold, terra, hybrid) in enumerate(outcomes):
        case_id = f"PAIR_{index}"
        records.append(make_record(case_id=case_id, system="terra_only", gold=gold, raw=terra))
        records.append(make_record(case_id=case_id, system="terra_jev", gold=gold, raw=hybrid))
    return records


def test_mcnemar_contingency_and_exact_p_value(make_record) -> None:
    result = mcnemar_test(paired_records(make_record))

    assert result.both_correct == 1
    assert result.terra_only_correct == 1
    assert result.terra_jev_correct == 1
    assert result.both_wrong == 0
    assert result.exact_p_value == pytest.approx(1.0)


def test_paired_bootstrap_is_seeded_and_has_requested_shape(make_record) -> None:
    records = paired_records(make_record)

    first = paired_bootstrap(records, metric="accuracy", samples=100, seed=17)
    second = paired_bootstrap(records, metric="accuracy", samples=100, seed=17)

    assert first.samples == second.samples
    assert len(first.samples) == 100
    assert first.observed_difference == pytest.approx(0.0)
    assert first.lower <= first.observed_difference <= first.upper


def test_pairing_rejects_missing_system_case(make_record) -> None:
    records = paired_records(make_record)[:-1]

    with pytest.raises(ValueError, match="paired"):
        mcnemar_test(records)
