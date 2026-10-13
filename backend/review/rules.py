"""Validation rules: plain data, versioned per tenant, evaluated after every extraction.

A rule set is a list like:

    [{"id": "totals-add-up", "type": "consistent", "field": "total"},
     {"id": "under-limit", "type": "max_amount", "field": "total", "max": 500000}]

Changing rules publishes a new version; every decision records the version that produced it,
so "why was this approved?" always has an answer. A document is approved automatically only
when every rule passes; otherwise it goes to a person with the failing rules as the reasons.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from pipeline.schema import AMOUNT_FIELDS, SCALAR_FIELDS


class InvalidRules(ValueError):
    pass


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    type: str
    passed: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


Fields = dict[str, dict[str, Any]]
DuplicateFinder = Callable[[Fields], str | None]


def _value(fields: Fields, name: str) -> Any:
    return (fields.get(name) or {}).get("value")


def _confidence(fields: Fields, name: str) -> float | None:
    confidence = (fields.get(name) or {}).get("confidence")
    return float(confidence) if confidence is not None else None


def _required(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    present = _value(fields, rule["field"]) is not None
    return present, f"{rule['field']} is {'present' if present else 'missing'}"


def _min_confidence(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    if "field" in rule:
        value = _confidence(fields, rule["field"])
        label = rule["field"]
    else:
        value, label = ctx.document_confidence, "document"
    passed = value is not None and value >= rule["min"]
    shown = "n/a" if value is None else f"{value:.2f}"
    return passed, f"{label} confidence {shown} (needs {rule['min']:.2f})"


def _max_amount(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    value = _value(fields, rule["field"])
    if value is None:
        return False, f"{rule['field']} is missing"
    passed = float(value) <= rule["max"]
    return (
        passed,
        f"{rule['field']} {value:,.0f} {'within' if passed else 'over'} the {rule['max']:,.0f} limit",
    )


def _consistent(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    checks = (fields.get(rule["field"]) or {}).get("checks") or {}
    consistent = checks.get("consistent")
    if consistent is None:
        return False, f"nothing on the receipt to check {rule['field']} against"
    return bool(
        consistent
    ), f"{rule['field']} {'matches' if consistent else 'does not match'} the receipt's arithmetic"


def _max_age_days(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    value = _value(fields, rule["field"])
    if value is None:
        return False, f"{rule['field']} is missing"
    age = (ctx.today - date.fromisoformat(value)).days
    return age <= rule["days"], f"{rule['field']} is {age} days old (limit {rule['days']})"


def _allowed_values(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    value = _value(fields, rule["field"])
    passed = value in rule["values"]
    return passed, f"{rule['field']} {value!r} {'is' if passed else 'is not'} allowed"


def _unique_receipt(rule: dict[str, Any], fields: Fields, ctx: "Context") -> tuple[bool, str]:
    duplicate_of = ctx.find_duplicate(fields)
    if duplicate_of:
        return False, f"same merchant, date and total as approved document {duplicate_of}"
    return True, "no approved receipt with the same merchant, date and total"


@dataclass(frozen=True)
class Context:
    document_confidence: float
    find_duplicate: DuplicateFinder
    today: date


# type -> (required parameters, check)
RULE_TYPES: dict[str, tuple[dict[str, type | tuple[type, ...]], Callable[..., tuple[bool, str]]]] = {
    "required": ({"field": str}, _required),
    "min_confidence": ({"min": (int, float)}, _min_confidence),
    "max_amount": ({"field": str, "max": (int, float)}, _max_amount),
    "consistent": ({"field": str}, _consistent),
    "max_age_days": ({"field": str, "days": int}, _max_age_days),
    "allowed_values": ({"field": str, "values": list}, _allowed_values),
    "unique_receipt": ({}, _unique_receipt),
}

DEFAULT_RULES: list[dict[str, Any]] = [
    {"id": "total-present", "type": "required", "field": "total"},
    {"id": "confident", "type": "min_confidence", "min": 0.9},
    {"id": "totals-add-up", "type": "consistent", "field": "total"},
    {"id": "under-limit", "type": "max_amount", "field": "total", "max": 1_000_000},
    {"id": "not-a-duplicate", "type": "unique_receipt"},
]


def validate(rules: object) -> list[dict[str, Any]]:
    """Checks a rule list before it is published; raises InvalidRules with the first problem."""
    if not isinstance(rules, list) or not rules:
        raise InvalidRules("Rules must be a non-empty list.")
    seen: set[str] = set()
    for position, rule in enumerate(rules, start=1):
        where = f"Rule {position}"
        if not isinstance(rule, dict):
            raise InvalidRules(f"{where} must be an object.")
        rule_id, kind = rule.get("id"), rule.get("type")
        if not isinstance(rule_id, str) or not rule_id:
            raise InvalidRules(f"{where} needs an id.")
        if rule_id in seen:
            raise InvalidRules(f"Rule id {rule_id!r} is used twice.")
        seen.add(rule_id)
        if kind not in RULE_TYPES:
            raise InvalidRules(f"{rule_id}: unknown type {kind!r}; use one of {', '.join(RULE_TYPES)}.")
        params, _ = RULE_TYPES[kind]
        allowed = {"id", "type", *params}
        if kind == "min_confidence":
            allowed.add("field")
        if extra := set(rule) - allowed:
            raise InvalidRules(f"{rule_id}: unexpected {', '.join(sorted(extra))}.")
        for name, expected in params.items():
            if not isinstance(rule.get(name), expected) or isinstance(rule.get(name), bool):
                raise InvalidRules(f"{rule_id}: {name} is required and must be {_kind_name(expected)}.")
        if "field" in rule and rule["field"] not in SCALAR_FIELDS:
            raise InvalidRules(f"{rule_id}: unknown field {rule['field']!r}.")
        if kind == "max_amount" and rule["field"] not in AMOUNT_FIELDS:
            raise InvalidRules(f"{rule_id}: max_amount needs an amount field.")
        if kind == "min_confidence" and not 0 <= rule["min"] <= 1:
            raise InvalidRules(f"{rule_id}: min must be between 0 and 1.")
    return rules


def _kind_name(expected: type | tuple[type, ...]) -> str:
    kinds = expected if isinstance(expected, tuple) else (expected,)
    names = {"str": "text", "int": "a number", "float": "a number", "list": "a list"}
    return " or ".join(sorted({names[k.__name__] for k in kinds}))


def evaluate(rules: list[dict[str, Any]], fields: Fields, ctx: Context) -> list[RuleResult]:
    results = []
    for rule in rules:
        _, check = RULE_TYPES[rule["type"]]
        passed, message = check(rule, fields, ctx)
        results.append(RuleResult(rule["id"], rule["type"], passed, message))
    return results


def fingerprint(fields: Fields) -> str | None:
    """Merchant, date and total, normalised: how duplicate submissions of one receipt are spotted."""
    merchant, day, total = (
        _value(fields, "merchant_name"),
        _value(fields, "receipt_date"),
        _value(fields, "total"),
    )
    if total is None or (merchant is None and day is None):
        return None
    name = "".join(ch for ch in str(merchant or "").lower() if ch.isalnum())
    return f"{name}|{day or ''}|{float(total):.2f}"
