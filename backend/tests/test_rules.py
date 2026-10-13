from datetime import date
from typing import Any

import pytest

from review.models import RuleSet
from review.rules import DEFAULT_RULES, Context, InvalidRules, evaluate, fingerprint, validate
from tenants.models import Tenant


def field(value: Any, confidence: float = 1.0, consistent: bool | None = True) -> dict[str, Any]:
    return {
        "value": value,
        "confidence": confidence,
        "checks": {"grounded": True, "valid": True, "consistent": consistent},
    }


FIELDS = {
    "merchant_name": field("Kopi Kenangan"),
    "receipt_date": field("2024-03-12"),
    "total": field(56100.0),
    "currency": {"value": None, "confidence": None, "checks": None},
}


def ctx(confidence: float = 0.95, duplicate: str | None = None) -> Context:
    return Context(document_confidence=confidence, find_duplicate=lambda _: duplicate, today=date(2024, 4, 1))


def results(
    rules: list[dict[str, Any]], fields: dict[str, Any] = FIELDS, **kw: Any
) -> dict[str, tuple[bool, str]]:
    return {r.rule_id: (r.passed, r.message) for r in evaluate(validate(rules), fields, ctx(**kw))}


def test_every_rule_type() -> None:
    outcome = results(
        [
            {"id": "a", "type": "required", "field": "total"},
            {"id": "b", "type": "required", "field": "currency"},
            {"id": "c", "type": "min_confidence", "min": 0.9},
            {"id": "d", "type": "min_confidence", "field": "total", "min": 0.99},
            {"id": "e", "type": "max_amount", "field": "total", "max": 50000},
            {"id": "f", "type": "consistent", "field": "total"},
            {"id": "g", "type": "max_age_days", "field": "receipt_date", "days": 14},
            {"id": "h", "type": "allowed_values", "field": "merchant_name", "values": ["Kopi Kenangan"]},
            {"id": "i", "type": "unique_receipt"},
        ]
    )

    assert {k: passed for k, (passed, _) in outcome.items()} == {
        "a": True, "b": False, "c": True, "d": True, "e": False, "f": True, "g": False, "h": True, "i": True,
    }  # fmt: skip
    assert outcome["e"][1] == "total 56,100 over the 50,000 limit"
    assert outcome["g"][1] == "receipt_date is 20 days old (limit 14)"


def test_duplicates_and_unchecked_arithmetic_need_a_person() -> None:
    unchecked = {**FIELDS, "total": field(56100.0, consistent=None)}

    assert results([{"id": "dup", "type": "unique_receipt"}], duplicate="doc-1")["dup"] == (
        False, "same merchant, date and total as approved document doc-1",
    )  # fmt: skip
    assert results([{"id": "sum", "type": "consistent", "field": "total"}], unchecked)["sum"][0] is False


@pytest.mark.parametrize(
    ("rules", "problem"),
    [
        ([], "non-empty list"),
        ([{"type": "required", "field": "total"}], "needs an id"),
        ([{"id": "x", "type": "nope"}], "unknown type 'nope'"),
        ([{"id": "x", "type": "required"}], "field is required and must be text"),
        ([{"id": "x", "type": "required", "field": "tip"}], "unknown field 'tip'"),
        ([{"id": "x", "type": "max_amount", "field": "merchant_name", "max": 5}], "needs an amount field"),
        ([{"id": "x", "type": "min_confidence", "min": 2}], "between 0 and 1"),
        ([{"id": "x", "type": "max_amount", "field": "total", "max": True}], "must be a number"),
        ([{"id": "x", "type": "unique_receipt", "extra": 1}], "unexpected extra"),
        ([{"id": "x", "type": "unique_receipt"}, {"id": "x", "type": "unique_receipt"}], "used twice"),
    ],
)
def test_invalid_rules_are_refused_with_a_reason(rules: list[dict[str, Any]], problem: str) -> None:
    with pytest.raises(InvalidRules, match=problem):
        validate(rules)


def test_the_default_rules_are_valid() -> None:
    assert validate(DEFAULT_RULES) == DEFAULT_RULES


def test_fingerprints_ignore_formatting() -> None:
    a = fingerprint(
        {
            "merchant_name": {"value": "Kopi Kenangan"},
            "receipt_date": {"value": "2024-03-12"},
            "total": {"value": 56100},
        }
    )
    b = fingerprint(
        {
            "merchant_name": {"value": "KOPI-KENANGAN"},
            "receipt_date": {"value": "2024-03-12"},
            "total": {"value": 56100.0},
        }
    )

    assert a == b == "kopikenangan|2024-03-12|56100.00"
    assert fingerprint({"total": {"value": 5}}) is None, "a total alone is too common to call a duplicate"


def test_publishing_creates_the_next_version_and_one_active(tenant: Tenant) -> None:
    first = RuleSet.active_for(tenant)
    second = RuleSet.publish(
        tenant, [{"id": "t", "type": "required", "field": "total"}], user=None, note="Looser"
    )

    assert (first.version, second.version) == (1, 2)
    assert list(RuleSet.objects.filter(tenant=tenant, is_active=True)) == [second]
    first.refresh_from_db()
    assert first.rules == DEFAULT_RULES, "old versions are kept as they were"
