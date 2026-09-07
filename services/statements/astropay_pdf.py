from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import re
import unicodedata

import pymupdf

from services.ofx.models import ParsedOfxFile
from services.ofx.models import ParsedStatement
from services.ofx.models import ParsedTransaction


class AstroPayPdfParseError(ValueError):
    pass


_ROW_DATE_RE = re.compile(r"^\d{2}/\d{2}$")
_MONEY_RE = re.compile(r"^-?[\d.]+,\d{2}$")
_PERIOD_RE = re.compile(
    r"(?P<start_day>\d{1,2})\s+"
    r"(?P<start_month>[A-Za-zÀ-ÿ]+)\s+"
    r"(?P<start_year>\d{4})\s*-\s*"
    r"(?P<end_day>\d{1,2})\s+"
    r"(?P<end_month>[A-Za-zÀ-ÿ]+)\s+"
    r"(?P<end_year>\d{4})",
    flags=re.IGNORECASE,
)

_BALANCE_ROW_NAMES = {
    "SALDO INICIAL",
    "SALDO ANTERIOR",
    "SALDO FINAL",
}

_MONTHS = {
    "JANEIRO": 1,
    "FEVEREIRO": 2,
    "MARCO": 3,
    "ABRIL": 4,
    "MAIO": 5,
    "JUNHO": 6,
    "JULHO": 7,
    "AGOSTO": 8,
    "SETEMBRO": 9,
    "OUTUBRO": 10,
    "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value or "",
    )
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(
            character
        )
    )
    return " ".join(
        ascii_text.upper().split()
    )


def _decimal_br(value: str) -> Decimal:
    normalized = (
        value.replace(".", "")
        .replace(",", ".")
        .strip()
    )
    return Decimal(normalized)


def _value_after_label(
    full_text: str,
    label: str,
) -> str:
    match = re.search(
        rf"{re.escape(label)}\s*\n?\s*"
        r"(-?[\d.]+,\d{2})",
        full_text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return match.group(1)


def _extract_account_holder(
    full_text: str,
) -> str:
    match = re.search(
        r"Titular\s+da\s+conta\s*\n\s*([^\n]+)",
        full_text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return " ".join(
        match.group(1).split()
    ).strip()


def _parse_period(
    full_text: str,
) -> tuple[datetime, datetime]:
    match = _PERIOD_RE.search(
        full_text
    )

    if not match:
        raise AstroPayPdfParseError(
            "Não foi possível identificar o período do extrato AstroPay."
        )

    start_month_name = _normalize_text(
        match.group("start_month")
    )
    end_month_name = _normalize_text(
        match.group("end_month")
    )

    try:
        start_month = _MONTHS[
            start_month_name
        ]
        end_month = _MONTHS[
            end_month_name
        ]
    except KeyError as exc:
        raise AstroPayPdfParseError(
            "O período do extrato AstroPay possui um mês não reconhecido."
        ) from exc

    try:
        start = datetime(
            int(
                match.group(
                    "start_year"
                )
            ),
            start_month,
            int(
                match.group(
                    "start_day"
                )
            ),
        )
        end = datetime(
            int(
                match.group(
                    "end_year"
                )
            ),
            end_month,
            int(
                match.group(
                    "end_day"
                )
            ),
        )
    except ValueError as exc:
        raise AstroPayPdfParseError(
            "O período do extrato AstroPay possui uma data inválida."
        ) from exc

    if end < start:
        raise AstroPayPdfParseError(
            "O período do extrato AstroPay está invertido."
        )

    return start, end


def _stable_account_id(
    *,
    holder: str,
    currency: str,
) -> str:
    normalized_holder = _normalize_text(
        holder
    )

    payload = (
        f"ASTROPAY|{currency.upper()}|"
        f"{normalized_holder}"
    )

    digest = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:16].upper()

    return f"ASTROPAY-{currency.upper()}-{digest}"


def _stable_transaction_fitid(
    *,
    account_id: str,
    posted_at: datetime,
    description: str,
    amount: Decimal,
    balance: Decimal,
) -> str:
    """
    O PDF AstroPay não informa um identificador bancário da operação.

    Geramos um FITID determinístico com campos do próprio lançamento. O saldo
    posterior faz parte da chave para distinguir operações legítimas repetidas
    no mesmo dia com a mesma descrição e o mesmo valor.

    A chave NÃO inclui página, ordem física do PDF nem data de geração do
    arquivo. Assim, um novo download do mesmo extrato continua produzindo os
    mesmos identificadores e é reconhecido como duplicado pelo sistema.
    """
    payload = "|".join(
        [
            "ASTROPAY-PDF-V1",
            account_id,
            posted_at.strftime(
                "%Y-%m-%d"
            ),
            _normalize_text(
                description
            ),
            f"{amount:.2f}",
            f"{balance:.2f}",
        ]
    )

    digest = hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:32].upper()

    return f"ASTROPAY-{digest}"


def _date_from_short_row(
    date_text: str,
    *,
    period_start: datetime,
    period_end: datetime,
) -> datetime:
    try:
        month_text, day_text = (
            date_text.split(
                "/",
                1,
            )
        )
        month = int(
            month_text
        )
        day = int(
            day_text
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
    ) as exc:
        raise AstroPayPdfParseError(
            f'Data de movimentação AstroPay inválida: "{date_text}".'
        ) from exc

    candidate_years = []

    for year in (
        period_start.year,
        period_end.year,
    ):
        if year not in candidate_years:
            candidate_years.append(
                year
            )

    for year in candidate_years:
        try:
            candidate = datetime(
                year,
                month,
                day,
            )
        except ValueError:
            continue

        if (
            period_start.date()
            <= candidate.date()
            <= period_end.date()
        ):
            return candidate

    raise AstroPayPdfParseError(
        (
            f'A data "{date_text}" não pertence ao período '
            "declarado no extrato AstroPay."
        )
    )


def _split_transfer_description(
    description: str,
) -> tuple[str, str]:
    normalized = _normalize_text(
        description
    )

    marker = " TRANSFERENCIA PIX"

    if normalized.endswith(
        marker
    ):
        # Usamos o texto original para manter acentos/capitalização do nome.
        match = re.search(
            r"\s+Transfer[eê]ncia\s+Pix\s*$",
            description,
            flags=re.IGNORECASE,
        )

        if match:
            payee = description[
                : match.start()
            ].strip()
            operation = description[
                match.start() :
            ].strip()
            return payee, operation

    return "", description


class AstroPayPdfParser:
    provider = "ASTROPAY"

    def can_parse(
        self,
        content: bytes,
    ) -> bool:
        try:
            with pymupdf.open(
                stream=content,
                filetype="pdf",
            ) as document:
                text = "\n".join(
                    page.get_text(
                        "text"
                    )
                    for page in document
                )
        except Exception:
            return False

        normalized = _normalize_text(
            text
        )

        return (
            "ASTRO INSTITUICAO DE PAGAMENTO LTDA"
            in normalized
            and "SUPPORT@ASTROPAY.COM"
            in normalized
            and "HISTORICO DE TRANSACOES"
            in normalized
            and "QUANTIA"
            in normalized
            and "EQUILIBRIO"
            in normalized
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
            raise AstroPayPdfParseError(
                "Não foi possível abrir o PDF AstroPay."
            ) from exc

        try:
            if document.page_count == 0:
                raise AstroPayPdfParseError(
                    "O PDF AstroPay não possui páginas."
                )

            page_texts = [
                page.get_text(
                    "text"
                )
                for page in document
            ]
            full_text = "\n".join(
                page_texts
            )

            if not self.can_parse(
                content
            ):
                raise AstroPayPdfParseError(
                    "O PDF não corresponde ao modelo AstroPay suportado."
                )

            period_start, period_end = (
                _parse_period(
                    full_text
                )
            )

            holder = (
                _extract_account_holder(
                    full_text
                )
            )

            if not holder:
                raise AstroPayPdfParseError(
                    "Não foi possível identificar o titular da conta AstroPay."
                )

            currency = "BRL"
            account_id = (
                _stable_account_id(
                    holder=holder,
                    currency=currency,
                )
            )

            closing_balance_text = (
                _value_after_label(
                    full_text,
                    "Saldo Final",
                )
            )
            ledger_balance = (
                _decimal_br(
                    closing_balance_text
                )
                if closing_balance_text
                else None
            )

            transactions = tuple(
                self._parse_transactions(
                    document=document,
                    period_start=period_start,
                    period_end=period_end,
                    account_id=account_id,
                )
            )

            statement = ParsedStatement(
                bank_id="ASTROPAY",
                bank_name="AstroPay",
                branch_id="",
                account_id=account_id,
                account_type="PAYMENT",
                currency=currency,
                start=period_start,
                end=period_end,
                ledger_balance=(
                    ledger_balance
                ),
                transactions=(
                    transactions
                ),
            )

            return ParsedOfxFile(
                version="ASTROPAY-PDF-1",
                encoding="UTF-8",
                statements=(
                    statement,
                ),
            )
        finally:
            document.close()

    def _parse_transactions(
        self,
        *,
        document,
        period_start: datetime,
        period_end: datetime,
        account_id: str,
    ):
        seen_fitids: set[str] = set()

        for page_number, page in enumerate(
            document,
            start=1,
        ):
            blocks = page.get_text(
                "blocks",
                sort=True,
            )

            for block in blocks:
                block_text = str(
                    block[4]
                )

                parsed = (
                    self._parse_transaction_block(
                        block_text,
                        page_number=page_number,
                        block_number=(
                            int(block[5])
                            if len(block) > 5
                            else 0
                        ),
                        period_start=period_start,
                        period_end=period_end,
                        account_id=account_id,
                    )
                )

                if parsed is None:
                    continue

                if parsed.fitid in seen_fitids:
                    # Duplicação visual de um mesmo bloco no PDF não deve
                    # virar uma segunda movimentação financeira.
                    continue

                seen_fitids.add(
                    parsed.fitid
                )
                yield parsed

    def _parse_transaction_block(
        self,
        block_text: str,
        *,
        page_number: int,
        block_number: int,
        period_start: datetime,
        period_end: datetime,
        account_id: str,
    ) -> ParsedTransaction | None:
        lines = [
            line.strip()
            for line in (
                block_text or ""
            ).splitlines()
            if line.strip()
        ]

        if len(lines) < 4:
            return None

        date_text = lines[0]

        if not _ROW_DATE_RE.fullmatch(
            date_text
        ):
            return None

        if not (
            _MONEY_RE.fullmatch(
                lines[-2]
            )
            and _MONEY_RE.fullmatch(
                lines[-1]
            )
        ):
            return None

        description = " ".join(
            lines[1:-2]
        ).strip()

        if not description:
            return None

        normalized_description = (
            _normalize_text(
                description
            )
        )

        if normalized_description in (
            _BALANCE_ROW_NAMES
        ):
            # Saldo anterior/inicial e saldo final são metadados do extrato,
            # não movimentações. Isso evita crédito/débito artificial e
            # duplicidade entre o fechamento de um mês e a abertura do outro.
            return None

        amount = _decimal_br(
            lines[-2]
        )
        balance = _decimal_br(
            lines[-1]
        )

        if amount == Decimal(
            "0.00"
        ):
            return None

        posted_at = (
            _date_from_short_row(
                date_text,
                period_start=period_start,
                period_end=period_end,
            )
        )

        fitid = (
            _stable_transaction_fitid(
                account_id=account_id,
                posted_at=posted_at,
                description=description,
                amount=amount,
                balance=balance,
            )
        )

        payee, operation = (
            _split_transfer_description(
                description
            )
        )

        source_type = (
            "XFER"
            if "TRANSFERENCIA PIX"
            in normalized_description
            else (
                "CREDIT"
                if amount > 0
                else "DEBIT"
            )
        )

        # Para preservar a descrição bancária original no campo canônico,
        # deixamos memo com o texto integral. O payee separado é guardado em
        # raw_data e utilizado pela associação de contrapartes.
        return ParsedTransaction(
            fitid=fitid,
            posted_at=posted_at,
            amount=amount,
            transaction_type=(
                source_type
            ),
            memo=description,
            payee="",
            checknum="",
            reference=fitid,
            posted_at_raw=(
                date_text
            ),
            posted_at_has_time=False,
            raw={
                "provider": "ASTROPAY",
                "source_format": "PDF",
                "fitid_source": (
                    "SYNTHETIC_ROW_HASH_V1"
                ),
                "page": page_number,
                "block": block_number,
                "date": date_text,
                "description": (
                    description
                ),
                "counterparty": payee,
                "operation": operation,
                "amount": str(
                    amount
                ),
                "balance": str(
                    balance
                ),
            },
        )
