"""Per-field confidence from checks anyone can verify, not from the model's own opinion.

Language models don't report calibrated confidence, so each extracted value is checked:

- grounded:   the value actually appears in the OCR text (catches invented values)
- valid:      it is well-formed (amounts not negative, dates real and not in the future)
- consistent: the arithmetic agrees (line items add up to the subtotal; subtotal + tax +
              service - discount = total). None when there is nothing to check against.

The weights below are a starting point; the evaluation harness measures how well the score
separates right from wrong values, and the auto-approve threshold is set from that.
"""

import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from pipeline.schema import AMOUNT_FIELDS, DATE_FIELDS, Receipt, Value, is_iso_date

UNGROUNDED_PENALTY = 0.45
INVALID_PENALTY = 0.35
INCONSISTENT_PENALTY = 0.30
UNCHECKED_PENALTY = 0.05
TEXT_MATCH_RATIO = 0.85
# Reported with their own confidence but not counted in the document's: models tend to infer a
# currency that isn't printed, which shouldn't hold back a receipt whose amounts all check out.
INFORMATIONAL_FIELDS = {"currency"}


@dataclass
class Checks:
    grounded: bool
    valid: bool
    consistent: bool | None

    def score(self) -> float:
        value = 1.0
        if not self.grounded:
            value -= UNGROUNDED_PENALTY
        if not self.valid:
            value -= INVALID_PENALTY
        if self.consistent is False:
            value -= INCONSISTENT_PENALTY
        elif self.consistent is None:
            value -= UNCHECKED_PENALTY
        return round(max(0.0, value), 2)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def amount_spellings(value: float) -> set[str]:
    """How an amount may be printed: 12500 -> 12500, 12,500, 12.500, 12 500; 12.5 -> 12.50, 12,50."""
    whole = int(value)
    cents = round((value - whole) * 100)
    grouped = f"{whole:,}"
    spellings = (
        {str(whole), grouped, grouped.replace(",", "."), grouped.replace(",", " ")} if cents == 0 else set()
    )
    if cents or value != whole:
        decimals = f"{cents:02d}"
        spellings |= {f"{whole}.{decimals}", f"{whole},{decimals}", f"{grouped}.{decimals}"}
        spellings.add(f"{grouped.replace(',', '.')},{decimals}")
    return spellings


def _amount_grounded(value: float, text: str) -> bool:
    # Whole numbers only: 500 isn't "found" inside 12,500, nor 36.000 glued to the 18.000 before it.
    for spelling in amount_spellings(value):
        if re.search(rf"(?<![\d.,]){re.escape(spelling)}(?![\d]|[.,]\d)", text):
            return True
    return False


def _text_grounded(value: str, text: str) -> bool:
    needle = _compact(value)
    haystack = _compact(text)
    if not needle:
        return False
    if needle in haystack:
        return True
    # OCR can misread a letter or two; compare against same-length windows.
    width = len(needle)
    best = max(
        (
            SequenceMatcher(None, needle, haystack[i : i + width]).ratio()
            for i in range(len(haystack) - width + 1)
        ),
        default=0.0,
    )
    return best >= TEXT_MATCH_RATIO


def _date_grounded(value: str, text: str) -> bool:
    day = date.fromisoformat(value)
    candidates = {
        day.strftime(fmt) for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"]
    }
    candidates |= {c.lstrip("0") for c in candidates}
    compact = _compact(text)
    return any(_compact(c) in compact for c in candidates) or _text_grounded(day.strftime("%d %b %Y"), text)


CURRENCY_SYMBOLS = {
    "IDR": ["rp"],
    "INR": ["₹", "rs.", "rs ", "inr"],
    "USD": ["$", "us$"],
    "EUR": ["€"],
    "GBP": ["£"],
    "MYR": ["rm"],
    "SGD": ["s$"],
}


def _currency_grounded(code: str, text: str) -> bool:
    """The ISO code or the currency's symbol is printed (receipts say Rp or ₹, rarely IDR or INR)."""
    lowered = text.lower()
    if re.search(rf"\b{re.escape(code.lower())}\b", lowered):
        return True
    return any(symbol in lowered for symbol in CURRENCY_SYMBOLS.get(code, []))


def grounded(name: str, value: Value, text: str) -> bool:
    if value is None:
        return False
    if isinstance(value, float):
        return _amount_grounded(value, text)
    if name in DATE_FIELDS:
        return _date_grounded(value, text)
    if name == "currency":
        return _currency_grounded(value, text)
    return _text_grounded(value, text)


def valid(name: str, value: Value) -> bool:
    if isinstance(value, float):
        return value >= 0
    if name in DATE_FIELDS:
        return is_iso_date(value) and date(2000, 1, 1) <= date.fromisoformat(str(value)) <= date.today()
    if name == "currency":
        return isinstance(value, str) and len(value) == 3 and value.isalpha()
    return isinstance(value, str) and bool(value.strip())


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, 0.01 * max(abs(a), abs(b)))


def consistency(receipt: Receipt) -> dict[str, bool | None]:
    """Amounts the receipt's own arithmetic confirms (True), contradicts (False) or can't check (None)."""
    f = receipt.fields
    result: dict[str, bool | None] = {name: None for name in AMOUNT_FIELDS}
    item_amounts = [amount for i in receipt.line_items if isinstance(amount := i.get("amount"), float)]
    items_sum = sum(item_amounts) if item_amounts else None

    subtotal = f.get("subtotal")
    if isinstance(subtotal, float) and items_sum is not None:
        result["subtotal"] = _close(items_sum, subtotal)

    total = f.get("total")
    base = subtotal if isinstance(subtotal, float) else items_sum
    if isinstance(total, float) and base is not None:
        extras = {name: f.get(name) for name in ("tax", "service_charge", "discount")}
        expected = base + sum(v for k, v in extras.items() if k != "discount" and isinstance(v, float))
        if isinstance(extras["discount"], float):
            expected -= extras["discount"]
        ok = _close(expected, total)
        result["total"] = ok
        for name, v in extras.items():
            if isinstance(v, float):
                result[name] = ok
        if result["subtotal"] is None and isinstance(subtotal, float):
            result["subtotal"] = ok
    return result


def score(receipt: Receipt, ocr_text: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], float]:
    """Scored fields, scored line items, and the document's confidence (its weakest found field)."""
    consistent = consistency(receipt)
    fields: dict[str, dict[str, Any]] = {}
    found: list[float] = []
    for name, value in receipt.fields.items():
        if value is None:
            fields[name] = {"value": None, "confidence": None, "checks": None}
            continue
        checks = Checks(grounded(name, value, ocr_text), valid(name, value), consistent.get(name))
        fields[name] = {"value": value, "confidence": checks.score(), "checks": checks.__dict__}
        if name not in INFORMATIONAL_FIELDS:
            found.append(checks.score())

    items: list[dict[str, Any]] = []
    for item in receipt.line_items:
        amount = item.get("amount")
        description = item.get("description")
        item_checks = Checks(
            grounded=(amount is None or grounded("amount", amount, ocr_text))
            and (description is None or grounded("description", description, ocr_text)),
            valid=amount is None or (isinstance(amount, float) and amount >= 0),
            consistent=consistent["subtotal"] if isinstance(amount, float) else None,
        )
        items.append({**item, "confidence": item_checks.score()})
        found.append(item_checks.score())

    # A receipt without a total can't be approved automatically, however confident the rest is.
    document_confidence = min(found) if found and receipt.fields.get("total") is not None else 0.0
    return fields, items, document_confidence
