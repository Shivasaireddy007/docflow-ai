"""The receipt fields we extract, as a JSON schema for the model and as plain Python values after."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

AMOUNT_FIELDS = ["subtotal", "tax", "service_charge", "discount", "total", "cash_paid", "change"]
TEXT_FIELDS = ["merchant_name", "currency"]
DATE_FIELDS = ["receipt_date"]
SCALAR_FIELDS = TEXT_FIELDS + DATE_FIELDS + AMOUNT_FIELDS
ITEM_FIELDS = ["description", "quantity", "unit_price", "amount"]


def _nullable(kind: str) -> dict[str, Any]:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "merchant_name": _nullable("string"),
        "receipt_date": _nullable("string"),
        "currency": _nullable("string"),
        **{name: _nullable("number") for name in AMOUNT_FIELDS},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": _nullable("string"),
                    "quantity": _nullable("number"),
                    "unit_price": _nullable("number"),
                    "amount": _nullable("number"),
                },
                "required": ITEM_FIELDS,
            },
        },
    },
    "required": [*SCALAR_FIELDS, "line_items"],
}

Value = str | float | None


@dataclass
class Receipt:
    fields: dict[str, Value]
    line_items: list[dict[str, Value]] = field(default_factory=list)


_THOUSANDS = re.compile(r"^\d{1,3}([.,\s]\d{3})+$")


def to_amount(value: object) -> float | None:
    """12500, "12,500", "12.500", "Rp 12.500", "12.50" -> a number; models don't always follow the rules."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    # Receipts print negatives as -19.400 or (19,400); read the sign, then the number.
    negative = "-" in value or bool(re.search(r"\(\s*[\d.,\s]+\)", value))
    text = re.sub(r"[^\d.,\s]", "", value).strip()
    if not text:
        return None
    if _THOUSANDS.match(text):  # 12.500 / 12,500 / 1 250 000: separators, not decimals
        number = float(re.sub(r"[.,\s]", "", text))
    else:
        try:
            number = float(text.replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return -number if negative else number


_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
]


def to_date(value: object) -> str | None:
    """A date in any common receipt format -> ISO YYYY-MM-DD, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def coerce(raw: dict[str, Any]) -> Receipt:
    """The model's JSON -> typed values. Anything unusable becomes None instead of failing the document."""
    fields: dict[str, Value] = {}
    for name in TEXT_FIELDS:
        fields[name] = to_text(raw.get(name))
    if isinstance(fields["currency"], str):
        fields["currency"] = fields["currency"].upper()[:3]
    fields["receipt_date"] = to_date(raw.get("receipt_date"))
    for name in AMOUNT_FIELDS:
        fields[name] = to_amount(raw.get(name))
    if isinstance(fields["discount"], float):
        fields["discount"] = abs(fields["discount"])  # printed as -19.400; it is subtracted either way

    items: list[dict[str, Value]] = []
    raw_items = raw.get("line_items")
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        parsed: dict[str, Value] = {
            "description": to_text(item.get("description")),
            "quantity": to_amount(item.get("quantity")),
            "unit_price": to_amount(item.get("unit_price")),
            "amount": to_amount(item.get("amount")),
        }
        if any(v is not None for v in parsed.values()):
            items.append(parsed)
    return Receipt(fields=fields, line_items=items)


def is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
