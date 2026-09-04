from __future__ import annotations

import base64
import json
from decimal import Decimal
from decimal import InvalidOperation

from django import template


register = template.Library()


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return Decimal("0.00")


def _number_br(value: Decimal) -> str:
    absolute = abs(value)

    formatted = f"{absolute:,.2f}"
    return (
        formatted
        .replace(",", "#")
        .replace(".", ",")
        .replace("#", ".")
    )


@register.filter
def brl(value):
    amount = _decimal(value)

    if amount < 0:
        return f"-R$ {_number_br(amount)}"

    return f"R$ {_number_br(amount)}"


@register.filter
def brl_signed(value):
    amount = _decimal(value)

    if amount > 0:
        return (
            f"+ R$ {_number_br(amount)}"
        )

    if amount < 0:
        return (
            f"- R$ {_number_br(abs(amount))}"
        )

    return "R$ 0,00"



@register.filter
def json_b64(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return base64.urlsafe_b64encode(
        payload
    ).decode("ascii")
