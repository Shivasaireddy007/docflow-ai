from typing import Any

from evaluation import calibrate


def row(truth: dict[str, Any], scored: dict[str, Any]) -> dict[str, Any]:
    return {"truth": truth, "scored": scored}


def field(value: Any, confidence: float, grounded: bool, consistent: bool | None) -> dict[str, Any]:
    checks = {"grounded": grounded, "valid": True, "consistent": consistent}
    return {"value": value, "confidence": confidence, "checks": checks}


def test_samples_are_the_extracted_fields_that_have_a_label() -> None:
    results = {
        "documents": [
            row(
                {"total": 193.0, "subtotal": None, "tax": 6.0},
                {
                    "total": field(193.0, 0.95, grounded=True, consistent=True),
                    "subtotal": field(187.0, 0.7, grounded=True, consistent=None),  # no label
                    "tax": field(60.0, 0.25, grounded=False, consistent=False),
                },
            )
        ]
    }

    assert calibrate.samples(results) == [
        ([1.0, 1.0, 1.0, 0.0], 0.95, True),
        ([0.0, 1.0, 0.0, 1.0], 0.25, False),
    ]


def test_the_fit_learns_which_checks_predict_a_right_field() -> None:
    grounded, ungrounded = [1.0, 1.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]
    data = (
        [(grounded, 0.5, True)] * 9
        + [(grounded, 0.5, False)]
        + [(ungrounded, 0.5, False)] * 9
        + [(ungrounded, 0.5, True)]
    )

    w = calibrate.fit(data)

    assert 0.8 < calibrate.predict(w, grounded) < 0.95
    assert 0.05 < calibrate.predict(w, ungrounded) < 0.2


def test_reliability_measures_the_gap_between_confidence_and_accuracy() -> None:
    table, ece, brier = calibrate.reliability([(0.95, True), (0.95, False)])

    assert table == [{"bin": "0.9-1.0", "fields": 2, "predicted": 0.95, "correct": 0.5}]
    assert round(ece, 3) == 0.45
    assert round(brier, 4) == round((0.05**2 + 0.95**2) / 2, 4)


def test_the_fit_is_adopted_only_if_it_is_better_on_new_data() -> None:
    better = {"fitted": {"ece": 0.02}, "heuristic": {"ece": 0.04}}
    worse = {"fitted": {"ece": 0.11}, "heuristic": {"ece": 0.04}}

    assert "fitted score is better" in calibrate.verdict(better)
    assert "keeps them" in calibrate.verdict(worse)
