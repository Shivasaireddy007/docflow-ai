import pytest

from pipeline.schema import coerce, to_amount, to_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (56100, 56100.0),
        ("56.100", 56100.0),
        ("56,100", 56100.0),
        ("Rp 56.100", 56100.0),
        ("1 250 000", 1250000.0),
        ("12.50", 12.5),
        ("12,5", 12.5),
        ("", None),
        ("n/a", None),
        (True, None),
        (None, None),
    ],
)
def test_amounts(raw: object, expected: float | None) -> None:
    assert to_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024-03-12", "2024-03-12"),
        ("12/03/2024", "2024-03-12"),
        ("12.03.2024", "2024-03-12"),
        ("12 Mar 2024", "2024-03-12"),
        ("12/03/24", "2024-03-12"),
        ("yesterday", None),
        (20240312, None),
    ],
)
def test_dates(raw: object, expected: str | None) -> None:
    assert to_date(raw) == expected


def test_garbage_from_the_model_becomes_missing_values_not_errors() -> None:
    receipt = coerce({"total": "lots", "currency": "rupiah", "line_items": ["x", {"amount": "5.000"}, {}]})

    assert receipt.fields["total"] is None
    assert receipt.fields["currency"] == "RUP"
    assert receipt.line_items == [
        {"description": None, "quantity": None, "unit_price": None, "amount": 5000.0}
    ]
