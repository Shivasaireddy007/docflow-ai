"""Labelled datasets, turned into the same fields the pipeline extracts.

CORD (Indonesian receipts) labels the amounts: total, subtotal, tax, service, discount, cash and
change, and the line items; store names and dates are blurred, so they can't be checked there.
SROIE (Malaysian receipts) labels the company, the date and the total, which fills that gap.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pipeline.schema import to_amount, to_date, to_text

Value = float | str | None

# (our field, CORD group, CORD key)
CORD_FIELDS = [
    ("total", "total", "total_price"),
    ("subtotal", "sub_total", "subtotal_price"),
    ("tax", "sub_total", "tax_price"),
    ("service_charge", "sub_total", "service_price"),
    ("discount", "sub_total", "discount_price"),
    ("cash_paid", "total", "cashprice"),
    ("change", "total", "changeprice"),
]
EVALUATED_FIELDS = [name for name, _, _ in CORD_FIELDS]


@dataclass
class Truth:
    fields: dict[str, Value]
    item_amounts: list[float] = field(default_factory=list)


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _amount(raw: Any) -> float | None:
    value = to_amount(_first(raw)) if raw is not None else None
    return abs(value) if value is not None else None


def parse(gt: dict[str, Any]) -> Truth:
    """CORD: nested groups whose values are printed strings like "60.000" or "-19,400"; a group or
    item can also be a list when a receipt repeats it."""
    fields: dict[str, Value] = {}
    for name, group, key in CORD_FIELDS:
        section = _first(gt.get(group))
        fields[name] = _amount(section.get(key)) if isinstance(section, dict) else None

    menu = gt.get("menu") or []
    items = menu if isinstance(menu, list) else [menu]
    amounts = [
        a for item in items if isinstance(item, dict) and (a := _amount(item.get("price"))) is not None
    ]
    return Truth(fields=fields, item_amounts=amounts)


def parse_sroie(entities: dict[str, Any]) -> Truth:
    """SROIE: {"company": ..., "date": "15/01/2019", "address": ..., "total": "193.00"}."""
    return Truth(
        fields={
            "merchant_name": to_text(entities.get("company")),
            "receipt_date": to_date(entities.get("date")),
            "total": to_amount(entities.get("total")),
        }
    )


@dataclass(frozen=True)
class Dataset:
    name: str
    hf_id: str
    label: Callable[[dict[str, Any]], dict[str, Any]]  # a dataset row -> its stored label
    parse: Callable[[dict[str, Any]], Truth]


DATASETS = {
    "cord": Dataset(
        "cord", "naver-clova-ix/cord-v2", lambda row: json.loads(row["ground_truth"])["gt_parse"], parse
    ),
    "sroie": Dataset("sroie", "jsdnrs/ICDAR2019-SROIE", lambda row: row["entities"], parse_sroie),
}
