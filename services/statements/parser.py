from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.ofx import OfxBrParser
from services.ofx import OfxParseError
from services.ofx.models import ParsedOfxFile

from .astropay_pdf import AstroPayPdfParseError
from .astropay_pdf import AstroPayPdfParser
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
        pdf_parsers = (
            MercadoPagoPdfParser(),
            AstroPayPdfParser(),
        )

        parser = next(
            (
                candidate
                for candidate in pdf_parsers
                if candidate.can_parse(
                    content
                )
            ),
            None,
        )

        if parser is None:
            raise StatementParseError(
                "PDF ainda não suportado. Nesta versão, "
                "o importador reconhece extratos PDF de "
                "Mercado Pago e AstroPay."
            )

        try:
            parsed = parser.parse_bytes(
                content
            )
        except (
            MercadoPagoPdfParseError,
            AstroPayPdfParseError,
        ) as exc:
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
