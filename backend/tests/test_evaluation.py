from evaluation import metrics, report, truth


def test_cord_labels_become_our_fields() -> None:
    gt = {
        "menu": [
            {"nm": "ICE BLACK COFFEE", "cnt": "2", "price": "82,000"},
            {"nm": "AVOCADO", "price": "61,000"},
        ],
        "sub_total": {"subtotal_price": "194,000", "discount_price": "-19,400"},
        "total": {"total_price": "174,600", "cashprice": "200,000"},
    }

    parsed = truth.parse(gt)

    assert parsed.fields == {
        "total": 174600,
        "subtotal": 194000,
        "tax": None,
        "service_charge": None,
        "discount": 19400,
        "cash_paid": 200000,
        "change": None,
    }
    assert parsed.item_amounts == [82000, 61000]


def test_labels_that_repeat_a_group_use_the_first() -> None:
    parsed = truth.parse(
        {"total": [{"total_price": "60.000"}, {"total_price": "1"}], "menu": {"price": "60.000"}}
    )

    assert (parsed.fields["total"], parsed.item_amounts) == (60000, [60000])


def test_field_scores_separate_precision_from_recall() -> None:
    blank = dict.fromkeys(truth.EVALUATED_FIELDS)
    rows = [
        metrics.row_for(truth.Truth({**blank, "total": 100, "tax": 10}), {"total": 100, "subtotal": 90}, []),
        metrics.row_for(truth.Truth({**blank, "total": 200}), {"total": 250}, []),
    ]

    scores = metrics.score_fields(rows)

    assert (scores["total"].precision, scores["total"].recall) == (0.5, 0.5)
    assert (scores["subtotal"].precision, scores["subtotal"].recall) == (0.0, None), "invented"
    assert (scores["tax"].precision, scores["tax"].recall) == (None, 0.0), "missed"


def test_line_items_are_matched_as_multisets() -> None:
    assert metrics.score_items([10.0, 10.0, 5.0], [10.0, 7.0]) == (1, 3, 2)


def test_decisions_are_judged_on_the_total() -> None:
    rows = [
        {"truth": {"total": 1}, "total_correct": True, "auto_approved": True},
        {"truth": {"total": 1}, "total_correct": False, "auto_approved": True},
        {"truth": {"total": 1}, "total_correct": False, "auto_approved": False},
        {"truth": {"total": None}, "total_correct": False, "auto_approved": False},
    ]

    summary = metrics.decision_summary(rows)

    assert summary == {
        "documents": 3, "auto_approved": 2, "auto_approve_rate": 2 / 3, "wrong_auto_approvals": 1,
        "auto_approval_error_rate": 0.5, "wrong_totals": 2, "wrong_totals_caught": 1,
    }  # fmt: skip


def test_the_report_renders() -> None:
    field = {"labelled": 2, "extracted": 2, "correct": 1, "precision": 0.5, "recall": 0.5}
    decisions = {"documents": 2, "auto_approved": 1, "auto_approve_rate": 0.5, "wrong_auto_approvals": 0,
                 "auto_approval_error_rate": 0.0, "wrong_totals": 1, "wrong_totals_caught": 1}  # fmt: skip
    run = {
        "date": "2026-10-13T10:00:00+00:00",
        "dataset": "cord (test, 2)",
        "pipeline_version": "x",
        "machine": "arm64",
    }
    names = ["ocr", "extraction", "document", "cached_document"]
    latency = {f"{name}_{p}": 1500.0 for name in names for p in ("p50", "p95")}
    result = {
        "run": run,
        "summary": {
            "fields": {name: field for name in truth.EVALUATED_FIELDS},
            "line_items": {"matched": 1, "precision": 1.0, "recall": 0.5},
            "decisions": decisions,
            "threshold_sweep": [{"threshold": 0.9, **decisions}],
            "latency_ms": latency,
            "model_ms_per_document": 15000,
        },
    }

    markdown = report.render(result)

    assert "| Approved automatically | 1 (50%) |" in markdown
    assert "| 0.90 | 1 (50%) | 0 | 0% |" in markdown
    assert "about 4.2 hours" in markdown
