from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.ofx import OfxBrParser
from services.ofx import OfxParseError
from services.ofx.models import ParsedOfxFile

from .mercado_pago_csv import MercadoPagoCsvParseError
from .mercado_pago_csv import MercadoPagoCsvParser
from .mercado_pago_pdf import MercadoPagoPdfParseError
from .mercado_pago_pdf import MercadoPagoPdfParser


class StatementParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedStatementDocument:
    parsed: ParsedOfxFile
    source_format: str
    provider: str


def parse_statement_bytes(
    *,
    content: bytes,
    filename: str,
) -> ParsedStatementDocument:
    extension = Path(
        filename
    ).suffix.lower()

    if extension in {".ofx", ".qfx"}:
        try:
            parsed = OfxBrParser().parse_bytes(
                content
            )
        except OfxParseError as exc:
            raise StatementParseError(
                str(exc)
            ) from exc

        return ParsedStatementDocument(
            parsed=parsed,
            source_format="OFX",
            provider="GENERIC",
        )

    if extension == ".pdf":
        parser = MercadoPagoPdfParser()

        if not parser.can_parse(content):
            raise StatementParseError(
                "PDF ainda não suportado. Nesta versão, "
                "o importador PDF reconhece extratos de "
                "conta do Mercado Pago. A arquitetura já "
                "permite adicionar outros bancos por parser."
            )

        try:
            parsed = parser.parse_bytes(
                content
            )
        except MercadoPagoPdfParseError as exc:
            raise StatementParseError(
                str(exc)
            ) from exc

        return ParsedStatementDocument(
            parsed=parsed,
            source_format="PDF",
            provider=parser.provider,
        )

    if extension == ".csv":
        parser = MercadoPagoCsvParser()

        if not parser.can_parse(content):
            raise StatementParseError(
                "CSV não reconhecido como relatório "
                "de movimentações do Mercado Pago."
            )

        try:
            parsed = parser.parse_bytes(
                content
            )
        except MercadoPagoCsvParseError as exc:
            raise StatementParseError(
                str(exc)
            ) from exc

        return ParsedStatementDocument(
            parsed=parsed,
            source_format="API_CSV",
            provider=parser.provider,
        )

    raise StatementParseError(
        "Formato não suportado. Use OFX, QFX, "
        "PDF compatível ou CSV de relatório."
    )
