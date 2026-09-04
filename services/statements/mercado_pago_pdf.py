from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re

import pymupdf

from services.ofx.models import ParsedOfxFile
from services.ofx.models import ParsedStatement
from services.ofx.models import ParsedTransaction


class MercadoPagoPdfParseError(ValueError):
    pass


_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_OPERATION_ID_RE = re.compile(r"^\d{8,24}$")
_MONEY_RE = re.compile(
    r"^R\$\s*(-?[\d.]+,\d{2})$"
)


def _decimal_br(value: str) -> Decimal:
    normalized = (
        value.replace("R$", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    return Decimal(normalized)


def _find_value_after_label(
    words,
    label: str,
) -> str:
    normalized_label = label.casefold()

    for word in words:
        text = str(word[4]).strip()

        if text.casefold() != normalized_label:
            continue

        x1 = float(word[2])
        center_y = (
            float(word[1]) + float(word[3])
        ) / 2

        candidates = []

        for candidate in words:
            candidate_text = str(
                candidate[4]
            ).strip()

            if not candidate_text:
                continue

            candidate_x0 = float(candidate[0])
            candidate_center_y = (
                float(candidate[1])
                + float(candidate[3])
            ) / 2

            if (
                candidate_x0 >= x1 - 1
                and abs(
                    candidate_center_y
                    - center_y
                ) <= 3.5
            ):
                candidates.append(candidate)

        if candidates:
            candidates.sort(
                key=lambda item: float(item[0])
            )
            return str(
                candidates[0][4]
            ).strip()

    return ""


class MercadoPagoPdfParser:
    provider = "MERCADO_PAGO"

    def can_parse(self, content: bytes) -> bool:
        try:
            with pymupdf.open(
                stream=content,
                filetype="pdf",
            ) as document:
                text = "\n".join(
                    page.get_text("text")
                    for page in document
                )
        except Exception:
            return False

        normalized = text.upper()

        # O logotipo da primeira página pode ser uma imagem e, portanto,
        # não aparecer na extração textual. A identificação considera o
        # rodapé institucional e a estrutura específica do extrato.
        has_mercado_pago_identity = (
            "MERCADO PAGO" in normalized
            or (
                "DINHEIRO RESERVADO COLCHÃO"
                in normalized
                and "DINHEIRO RETIRADO COLCHÃO"
                in normalized
            )
        )

        return (
            "EXTRATO DE CONTA" in normalized
            and "ID DA OPERAÇÃO" in normalized
            and has_mercado_pago_identity
        )

    def parse_bytes(
        self,
        content: bytes,
    ) -> ParsedOfxFile:
        try:
            document = pymupdf.open(
                stream=content,
                filetype="pdf",
            )
        except Exception as exc:
            raise MercadoPagoPdfParseError(
                "Não foi possível abrir o PDF."
            ) from exc

        try:
            if document.page_count == 0:
                raise MercadoPagoPdfParseError(
                    "O PDF não possui páginas."
                )

            page_texts = [
                page.get_text("text")
                for page in document
            ]

            full_text = "\n".join(
                page_texts
            )

            if not self.can_parse(content):
                raise MercadoPagoPdfParseError(
                    "O PDF não corresponde ao modelo de "
                    "extrato do Mercado Pago suportado."
                )

            first_page = document[0]
            first_words = first_page.get_text(
                "words"
            )

            agency = _find_value_after_label(
                first_words,
                "Agência:",
            )
            account = _find_value_after_label(
                first_words,
                "Conta:",
            )

            period_match = re.search(
                r"De\s+(\d{2}-\d{2}-\d{4})"
                r"\s+al\s+(\d{2}-\d{2}-\d{4})",
                full_text,
                flags=re.IGNORECASE,
            )

            start = None
            end = None

            if period_match:
                start = datetime.strptime(
                    period_match.group(1),
                    "%d-%m-%Y",
                )
                end = datetime.strptime(
                    period_match.group(2),
                    "%d-%m-%Y",
                )

            balance_match = re.search(
                r"Saldo final:\s*"
                r"R\$\s*(-?[\d.]+,\d{2})",
                full_text,
                flags=re.IGNORECASE,
            )

            ledger_balance = (
                _decimal_br(
                    balance_match.group(1)
                )
                if balance_match
                else None
            )

            transactions = tuple(
                self._parse_transactions(
                    page_texts
                )
            )

            if not transactions:
                raise MercadoPagoPdfParseError(
                    "O PDF foi reconhecido, mas nenhuma "
                    "movimentação pôde ser extraída."
                )

            statement = ParsedStatement(
                bank_id="",
                bank_name="Mercado Pago",
                branch_id=agency,
                account_id=account,
                account_type="PAYMENT",
                currency="BRL",
                start=start,
                end=end,
                ledger_balance=ledger_balance,
                transactions=transactions,
            )

            return ParsedOfxFile(
                version="MP-PDF-1",
                encoding="UTF-8",
                statements=(statement,),
            )
        finally:
            document.close()

    def _parse_transactions(
        self,
        page_texts: list[str],
    ):
        for page_number, page_text in enumerate(
            page_texts,
            start=1,
        ):
            lines = [
                line.strip()
                for line in page_text.splitlines()
                if line.strip()
            ]

            date_positions = [
                index
                for index, line in enumerate(
                    lines
                )
                if _DATE_RE.fullmatch(line)
            ]

            for position_index, start_index in enumerate(
                date_positions
            ):
                end_index = (
                    date_positions[
                        position_index + 1
                    ]
                    if (
                        position_index + 1
                        < len(date_positions)
                    )
                    else len(lines)
                )

                row = lines[
                    start_index:end_index
                ]

                parsed = self._parse_row(
                    row,
                    page_number=page_number,
                )

                if parsed is not None:
                    yield parsed

    def _parse_row(
        self,
        row: list[str],
        *,
        page_number: int,
    ) -> ParsedTransaction | None:
        if len(row) < 5:
            return None

        date_text = row[0]

        operation_index = None

        for index, value in enumerate(
            row[1:],
            start=1,
        ):
            if _OPERATION_ID_RE.fullmatch(
                value
            ):
                operation_index = index
                break

        if operation_index is None:
            return None

        money_values = []

        for value in row[
            operation_index + 1:
        ]:
            match = _MONEY_RE.fullmatch(
                value
            )

            if match:
                money_values.append(
                    match.group(1)
                )

        if not money_values:
            return None

        description_lines = [
            value
            for value in row[
                1:operation_index
            ]
            if value not in {
                "Data",
                "Descrição",
                "ID da operação",
                "Valor",
                "Saldo",
            }
        ]

        description = " ".join(
            description_lines
        ).strip()

        if not description:
            return None

        operation_id = row[
            operation_index
        ]

        amount = _decimal_br(
            money_values[0]
        )

        balance = (
            _decimal_br(
                money_values[1]
            )
            if len(money_values) > 1
            else None
        )

        posted_at = datetime.strptime(
            date_text,
            "%d-%m-%Y",
        )

        return ParsedTransaction(
            fitid=operation_id,
            posted_at=posted_at,
            amount=amount,
            transaction_type=(
                "CREDIT"
                if amount > 0
                else "DEBIT"
            ),
            memo=description,
            payee="",
            checknum="",
            reference=operation_id,
            posted_at_raw=date_text,
            posted_at_has_time=False,
            raw={
                "provider": "MERCADO_PAGO",
                "source_format": "PDF",
                "page": page_number,
                "operation_id": operation_id,
                "date": date_text,
                "description": description,
                "amount": str(amount),
                "balance": (
                    str(balance)
                    if balance is not None
                    else ""
                ),
            },
        )
