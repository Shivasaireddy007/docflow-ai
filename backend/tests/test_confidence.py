import pytest

from pipeline.confidence import Checks, consistency, grounded, score
from pipeline.schema import Receipt, coerce
from tests.conftest import RECEIPT_FIELDS, RECEIPT_TEXT


def receipt(**changes: object) -> Receipt:
    return coerce({**RECEIPT_FIELDS, **changes})


def test_a_correct_receipt_scores_high() -> None:
    fields, items, overall = score(receipt(), RECEIPT_TEXT)

    assert fields["total"]["checks"] == {"grounded": True, "valid": True, "consistent": True}
    assert fields["merchant_name"]["checks"]["grounded"] is True
    assert all(item["confidence"] == 1.0 for item in items)
    assert overall >= 0.9


def test_an_invented_total_is_caught_twice() -> None:
    fields, _, overall = score(receipt(total=99000), RECEIPT_TEXT)

    assert fields["total"]["checks"] == {"grounded": False, "valid": True, "consistent": False}
    assert fields["total"]["confidence"] == 0.25
    assert overall == 0.25, "the document is only as confident as its weakest field"


def test_a_misread_subtotal_is_flagged_by_the_arithmetic() -> None:
    checks = consistency(receipt(subtotal=50000))

    assert checks["subtotal"] is False
    assert checks["total"] is False


def test_without_a_total_nothing_is_auto_approvable() -> None:
    _, _, overall = score(receipt(total=None), RECEIPT_TEXT)

    assert overall == 0.0


def test_missing_fields_have_no_score() -> None:
    fields, _, _ = score(receipt(), RECEIPT_TEXT)

    assert fields["discount"] == {"value": None, "confidence": None, "checks": None}


@pytest.mark.parametrize(
    ("value", "text", "found"),
    [
        (56100.0, "TOTAL 56.100", True),
        (56100.0, "TOTAL 56,100", True),
        (56100.0, "TOTAL Rp56100", True),
        (12.5, "Total $12.50", True),
        (100.0, "TOTAL 56.100", False),  # inside another number
        (2500.0, "Qty 2\n500", False),  # numbers on separate lines
    ],
)
def test_amounts_are_found_however_they_are_printed(value: float, text: str, found: bool) -> None:
    assert grounded("total", value, text) is found


def test_text_tolerates_small_ocr_errors_but_not_inventions() -> None:
    assert grounded("merchant_name", "Kopi Kenangan", "KOPI KENANCAN\n12/03/2024")
    assert not grounded("merchant_name", "Starbucks", "KOPI KENANGAN\n12/03/2024")


def test_currencies_are_found_by_code_or_symbol() -> None:
    assert grounded("currency", "IDR", "TOTAL Rp 56.100")
    assert grounded("currency", "INR", "Grand Total ₹1,250")
    assert grounded("currency", "USD", "Total USD 12.50")
    assert not grounded("currency", "IDR", "TOTAL 56.100"), "inferred, not printed"


def test_an_inferred_currency_is_flagged_but_does_not_block_the_receipt() -> None:
    fields, _, overall = score(receipt(), RECEIPT_TEXT.replace("Rp ", ""))

    assert fields["currency"]["checks"]["grounded"] is False
    assert overall >= 0.9


def test_dates_are_found_in_local_formats() -> None:
    assert grounded("receipt_date", "2024-03-12", "Tgl 12/03/2024 10:41")
    assert grounded("receipt_date", "2024-03-12", "12-03-24")
    assert not grounded("receipt_date", "2024-03-13", "12/03/2024")


def test_future_dates_and_negative_amounts_are_invalid() -> None:
    fields, _, _ = score(receipt(receipt_date="2999-01-01", tax=-5100), RECEIPT_TEXT)

    assert fields["receipt_date"]["checks"]["valid"] is False
    assert fields["tax"]["checks"]["valid"] is False


def test_penalties_combine() -> None:
    assert Checks(grounded=True, valid=True, consistent=None).score() == 0.95
    assert Checks(grounded=False, valid=False, consistent=False).score() == 0.0
