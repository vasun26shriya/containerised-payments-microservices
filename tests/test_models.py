import pytest
from pydantic import ValidationError
from services.common import PaymentInput, OrderInput


@pytest.mark.parametrize("amount", [0, -1, 1.2, True, "100", 100_000_001])
def test_invalid_amount(amount):
    with pytest.raises(ValidationError):
        OrderInput(amount=amount, currency="USD")


def test_explicit_currency_and_no_card_data():
    with pytest.raises(ValidationError):
        PaymentInput(order_id="x", amount=100, currency="usd")
    with pytest.raises(ValidationError):
        OrderInput(amount=100, currency="USD", card_number="123")
