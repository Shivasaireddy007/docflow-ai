"""CORD's labels, turned into the same fields the pipeline extracts.

CORD labels each receipt as nested groups ("total", "sub_total", "menu") whose values are printed
strings like "60.000" or "-19,400"; a group or item can also be a list when a receipt repeats it.
"""

from dataclasses import dataclass, field
from typing import Any

from pipeline.schema import to_amount

# (our field, CORD group, CORD key)
FIELD_MAP = [
    ("total", "total", "total_price"),
    ("subtotal", "sub_total", "subtotal_price"),
    ("tax", "sub_total", "tax_price"),
    ("service_charge", "sub_total", "service_price"),
    ("discount", "sub_total", "discount_price"),
]
EVALUATED_FIELDS = [name for name, _, _ in FIELD_MAP]


@dataclass
class Truth:
    fields: dict[str, float | None]
    item_amounts: list[float] = field(default_factory=list)


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _amount(raw: Any) -> float | None:
    value = to_amount(_first(raw)) if raw is not None else None
    return abs(value) if value is not None else None


def parse(gt: dict[str, Any]) -> Truth:
    fields: dict[str, float | None] = {}
    for name, group, key in FIELD_MAP:
        section = _first(gt.get(group))
        fields[name] = _amount(section.get(key)) if isinstance(section, dict) else None

    menu = gt.get("menu") or []
    items = menu if isinstance(menu, list) else [menu]
    amounts = [
        a for item in items if isinstance(item, dict) and (a := _amount(item.get("price"))) is not None
    ]
    return Truth(fields=fields, item_amounts=amounts)
