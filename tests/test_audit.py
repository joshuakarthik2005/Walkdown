from benchmark.audit_report import _pr


def test_pr_counts_and_baseline():
    pairs = [(True, True), (True, True), (True, False), (False, True), (False, False), (False, False)]
    r = _pr(pairs)
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 1, 1, 2)
    assert r["precision"] == 2 / 3 and r["recall"] == 2 / 3 and r["negatives_rejected"] == 2 / 3
    assert r["precision_if_accept_all"] == 0.5
    assert _pr([])["precision"] is None
