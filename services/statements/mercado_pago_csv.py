from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from io import StringIO

from services.ofx.models import ParsedOfxFile
from services.ofx.models import ParsedStatement
from services.ofx.models import ParsedTransaction


class MercadoPagoCsvParseError(ValueError):
    pass


def _decimal(value: str) -> Decimal:
    value = (value or "").strip()

    if not value:
        return Decimal("0.00")

    return Decimal(
        value.replace(",", ".")
    )


def _parse_datetime(value: str) -> datetime:
    cleaned = (value or "").strip()

    if not cleaned:
        raise MercadoPagoCsvParseError(
            "Relatório sem data da transação."
        )

    # ISO 8601 do Mercado Pago.
    return datetime.fromisoformat(
        cleaned.replace("Z", "+00:00")
    )


class MercadoPagoCsvParser:
    provider = "MERCADO_PAGO"

    def can_parse(self, content: bytes) -> bool:
        try:
            text = content.decode(
                "utf-8-sig"
            )
        except UnicodeDecodeError:
            return False

        header = text.splitlines()[0] if text else ""

        return (
            "SOURCE_ID" in header
            and (
                "TRANSACTION_DATE" in header
                or "SETTLEMENT_DATE" in header
            )
        )

    def parse_bytes(
        self,
        content: bytes,
    ) -> ParsedOfxFile:
        try:
            text = content.decode(
                "utf-8-sig"
            )
        except UnicodeDecodeError as exc:
            raise MercadoPagoCsvParseError(
                "O relatório CSV do Mercado Pago "
                "deve estar em UTF-8."
            ) from exc

        sample = text[:4096]

        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters=";,\t",
            )
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"

        reader = csv.DictReader(
            StringIO(text),
            dialect=dialect,
        )

        transactions = []

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            source_id = (
                row.get("SOURCE_ID")
                or row.get("EXTERNAL_REFERENCE")
                or ""
            ).strip()

            date_text = (
                row.get("TRANSACTION_DATE")
                or row.get("SETTLEMENT_DATE")
                or ""
            ).strip()

            if not source_id or not date_text:
                continue

            amount = _decimal(
                row.get(
                    "SETTLEMENT_NET_AMOUNT",
                    "",
                )
            )

            if amount == 0:
                amount = _decimal(
                    row.get(
                        "REAL_AMOUNT",
                        "",
                    )
                )

            if amount == 0:
                amount = _decimal(
                    row.get(
                        "TRANSACTION_AMOUNT",
                        "",
                    )
                )

            transaction_type = (
                row.get("TRANSACTION_TYPE")
                or "OTHER"
            ).strip()

            description_parts = [
                transaction_type,
                (
                    row.get(
                        "DESCRIPTION"
                    )
                    or ""
                ).strip(),
                (
                    row.get(
                        "EXTERNAL_REFERENCE"
                    )
                    or ""
                ).strip(),
                (
                    row.get(
                        "PAYMENT_METHOD"
                    )
                    or ""
                ).strip(),
                (
                    row.get(
                        "POI_BANK_NAME"
                    )
                    or ""
                ).strip(),
                (
                    row.get(
                        "POI_WALLET_NAME"
                    )
                    or ""
                ).strip(),
            ]

            description = " - ".join(
                part
                for part in description_parts
                if part
            )

            posted_at = _parse_datetime(
                date_text
            )

            transactions.append(
                ParsedTransaction(
                    fitid=source_id,
                    posted_at=posted_at,
                    amount=amount,
                    transaction_type=(
                        "CREDIT"
                        if amount >= 0
                        else "DEBIT"
                    ),
                    memo=description,
                    payee="",
                    checknum="",
                    reference=(
                        row.get(
                            "EXTERNAL_REFERENCE"
                        )
                        or ""
                    ).strip(),
                    posted_at_raw=date_text,
                    posted_at_has_time=True,
                    raw={
                        "provider": "MERCADO_PAGO",
                        "source_format": "API_CSV",
                        "row": row_number,
                        "report": row,
                    },
                )
            )

        if not transactions:
            raise MercadoPagoCsvParseError(
                "Nenhuma movimentação válida foi encontrada "
                "no relatório CSV do Mercado Pago."
            )

        dates = [
            transaction.posted_at
            for transaction in transactions
        ]

        return ParsedOfxFile(
            version="MP-API-1",
            encoding="UTF-8",
            statements=(
                ParsedStatement(
                    bank_id="",
                    bank_name="Mercado Pago",
                    branch_id="",
                    account_id="",
                    account_type="PAYMENT",
                    currency="BRL",
                    start=min(dates),
                    end=max(dates),
                    ledger_balance=None,
                    transactions=tuple(
                        transactions
                    ),
                ),
            ),
        )
