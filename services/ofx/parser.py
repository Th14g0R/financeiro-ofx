from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import Any
from typing import Iterator

from .models import ParsedOfxFile
from .models import ParsedStatement
from .models import ParsedTransaction
from .text import normalize_display_text


class OfxParseError(ValueError):
    """Erro controlado ao interpretar um arquivo OFX."""


class OfxBrParser:
    """
    Adapter do pacote ofx-br.

    O modelo interno mantém tanto o datetime interpretado quanto o valor bruto
    de DTPOSTED. Isso permite distinguir:

    - OFX que realmente informa hora;
    - OFX que fornece somente YYYYMMDD e acaba aparecendo como 00:00.
    """

    _TRANSACTION_BLOCK_RE = re.compile(
        r"<STMTTRN\b[^>]*>(.*?)</STMTTRN>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def parse_bytes(self, content: bytes) -> ParsedOfxFile:
        if not content:
            raise OfxParseError("O arquivo OFX está vazio.")

        try:
            import ofxbr
        except ImportError as exc:
            raise OfxParseError(
                "A dependência 'ofx-br' não está instalada. "
                "Execute: python -m pip install -r requirements.txt"
            ) from exc

        try:
            document = ofxbr.parse(content)
        except Exception as exc:
            raise OfxParseError(
                f"Não foi possível interpretar o arquivo OFX: {exc}"
            ) from exc

        encoding = str(
            getattr(document, "encoding", "") or "cp1252"
        )

        raw_transactions = iter(
            self._extract_raw_transaction_metadata(
                content,
                encoding=encoding,
            )
        )

        statements = tuple(
            self._convert_statement(
                statement,
                raw_transactions=raw_transactions,
            )
            for statement in getattr(document, "statements", ())
        )

        if not statements:
            raise OfxParseError(
                "O arquivo foi lido, mas nenhum extrato bancário "
                "ou de cartão foi encontrado."
            )

        return ParsedOfxFile(
            version=getattr(document, "version", None),
            encoding=encoding,
            statements=statements,
        )

    def _convert_statement(
        self,
        statement: Any,
        *,
        raw_transactions: Iterator[dict[str, str]],
    ) -> ParsedStatement:
        account = getattr(statement, "account", None)

        source_transactions = getattr(
            statement,
            "transactions",
            None,
        )

        if source_transactions is None:
            try:
                source_transactions = tuple(statement)
            except TypeError:
                source_transactions = ()

        transactions = tuple(
            self._convert_transaction(
                transaction,
                raw_metadata=next(
                    raw_transactions,
                    {},
                ),
            )
            for transaction in source_transactions
        )

        return ParsedStatement(
            bank_id=self._string_attr(account, "bank_id"),
            bank_name=self._string_attr(account, "bank_name"),
            branch_id=self._string_attr(account, "branch_id"),
            account_id=self._string_attr(account, "account_id"),
            account_type=self._first_string_attr(
                account,
                "account_type",
                "type",
                "acct_type",
            ),
            currency=self._string_attr(statement, "currency").upper(),
            start=self._datetime_attr(statement, "start"),
            end=self._datetime_attr(statement, "end"),
            ledger_balance=self._decimal_or_none(
                getattr(statement, "ledger_balance", None)
            ),
            transactions=transactions,
        )

    def _convert_transaction(
        self,
        transaction: Any,
        *,
        raw_metadata: dict[str, str],
    ) -> ParsedTransaction:
        posted_at = getattr(transaction, "posted_at", None)

        if not isinstance(posted_at, datetime):
            raise OfxParseError(
                "Foi encontrado um lançamento sem data válida."
            )

        amount = self._decimal_or_none(
            getattr(transaction, "amount", None)
        )

        if amount is None:
            raise OfxParseError(
                "Foi encontrado um lançamento sem valor válido."
            )

        source_fitid = self._raw_string_attr(transaction, "fitid")
        source_type = self._raw_string_attr(transaction, "type")
        source_memo = self._raw_string_attr(transaction, "memo")
        source_payee = self._raw_string_attr(transaction, "payee")
        source_checknum = self._raw_string_attr(transaction, "checknum")
        source_reference = self._first_raw_string_attr(
            transaction,
            "reference",
            "refnum",
        )

        fitid = normalize_display_text(source_fitid)
        transaction_type = normalize_display_text(source_type)
        memo = normalize_display_text(source_memo)
        payee = normalize_display_text(source_payee)
        checknum = normalize_display_text(source_checknum)
        reference = normalize_display_text(source_reference)

        dtposted_raw = raw_metadata.get("dtposted", "").strip()
        dtuser_raw = raw_metadata.get("dtuser", "").strip()
        has_time = self._ofx_datetime_has_time(dtposted_raw)

        raw = {
            "fitid": fitid,
            "posted_at": posted_at.isoformat(),
            "amount": str(amount),
            "type": transaction_type,
            "memo": memo,
            "payee": payee,
            "checknum": checknum,
            "reference": reference,
            "_ofx_datetime": {
                "dtposted": dtposted_raw,
                "dtuser": dtuser_raw,
                "has_time": has_time,
            },
            "_source_text": {
                "fitid": source_fitid,
                "type": source_type,
                "memo": source_memo,
                "payee": source_payee,
                "checknum": source_checknum,
                "reference": source_reference,
            },
        }

        return ParsedTransaction(
            fitid=fitid,
            posted_at=posted_at,
            amount=amount,
            transaction_type=transaction_type,
            memo=memo,
            payee=payee,
            checknum=checknum,
            reference=reference,
            raw=raw,
            posted_at_raw=dtposted_raw,
            posted_at_has_time=has_time,
            user_at_raw=dtuser_raw,
        )

    @classmethod
    def _extract_raw_transaction_metadata(
        cls,
        content: bytes,
        *,
        encoding: str,
    ) -> tuple[dict[str, str], ...]:
        codecs_to_try = [
            encoding,
            "cp1252",
            "utf-8",
            "latin-1",
        ]

        decoded = None

        for codec in codecs_to_try:
            if not codec:
                continue

            try:
                decoded = content.decode(codec)
                break
            except (LookupError, UnicodeDecodeError):
                continue

        if decoded is None:
            decoded = content.decode(
                "cp1252",
                errors="replace",
            )

        metadata = []

        for block in cls._TRANSACTION_BLOCK_RE.findall(decoded):
            metadata.append(
                {
                    "dtposted": cls._extract_leaf_value(
                        block,
                        "DTPOSTED",
                    ),
                    "dtuser": cls._extract_leaf_value(
                        block,
                        "DTUSER",
                    ),
                }
            )

        return tuple(metadata)

    @staticmethod
    def _extract_leaf_value(block: str, tag: str) -> str:
        match = re.search(
            rf"<{re.escape(tag)}\b[^>]*>\s*([^<\r\n]+)",
            block,
            flags=re.IGNORECASE,
        )

        if not match:
            return ""

        return match.group(1).strip()

    @staticmethod
    def _ofx_datetime_has_time(value: str) -> bool:
        """
        OFX datetime começa por YYYYMMDD e pode continuar com HHMMSS.

        Quando somente os 8 dígitos da data estão presentes, 00:00 é
        consequência da conversão para datetime e NÃO um horário informado
        pelo banco.
        """
        match = re.match(r"^\s*(\d{8})(\d{6})?", value or "")

        if not match:
            # Para dados legados/sem captura bruta, não afirmamos que faltou.
            return True

        return bool(match.group(2))

    @classmethod
    def _string_attr(cls, obj: Any, name: str) -> str:
        return normalize_display_text(
            cls._raw_string_attr(obj, name)
        )

    @staticmethod
    def _raw_string_attr(obj: Any, name: str) -> str:
        if obj is None:
            return ""

        value = getattr(obj, name, "")

        if value is None:
            return ""

        return str(value).strip()

    def _first_string_attr(
        self,
        obj: Any,
        *names: str,
    ) -> str:
        return normalize_display_text(
            self._first_raw_string_attr(
                obj,
                *names,
            )
        )

    def _first_raw_string_attr(
        self,
        obj: Any,
        *names: str,
    ) -> str:
        for name in names:
            value = self._raw_string_attr(obj, name)

            if value:
                return value

        return ""

    @staticmethod
    def _datetime_attr(
        obj: Any,
        name: str,
    ) -> datetime | None:
        value = getattr(obj, name, None)

        if isinstance(value, datetime):
            return value

        return None

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        if value is None:
            return None

        if isinstance(value, Decimal):
            return value

        try:
            return Decimal(str(value))
        except Exception:
            return None
