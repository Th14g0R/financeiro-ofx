from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from services.ofx import OfxBrParser
from services.ofx import OfxParseError


class Command(BaseCommand):
    help = "Lê um arquivo OFX e mostra um resumo sem gravar no banco."

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=str,
            help="Caminho para o arquivo .ofx ou .qfx.",
        )

    def handle(self, *args, **options):
        path = Path(options["file"]).expanduser().resolve()

        if not path.exists() or not path.is_file():
            raise CommandError(
                f"Arquivo não encontrado: {path}"
            )

        try:
            parsed = OfxBrParser().parse_bytes(
                path.read_bytes()
            )
        except OfxParseError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"OFX lido: versão={parsed.version} "
                f"encoding={parsed.encoding} "
                f"lançamentos={parsed.transaction_count}"
            )
        )

        for index, statement in enumerate(
            parsed.statements,
            start=1,
        ):
            self.stdout.write("")
            self.stdout.write(
                f"Extrato {index}: "
                f"BANKID={statement.bank_id or '-'} "
                f"agência={statement.branch_id or '-'} "
                f"ACCTID={statement.account_id or '-'} "
                f"moeda={statement.currency or '-'}"
            )
            self.stdout.write(
                f"  período={statement.start or '-'} "
                f"até {statement.end or '-'}"
            )
            self.stdout.write(
                f"  saldo={statement.ledger_balance} "
                f"créditos={statement.total_credits} "
                f"débitos={statement.total_debits}"
            )

            for transaction in statement.transactions:
                self.stdout.write(
                    "  "
                    f"{transaction.posted_at} | "
                    f"{transaction.fitid or '-'} | "
                    f"{transaction.transaction_type or '-'} | "
                    f"{transaction.amount} | "
                    f"{transaction.description}"
                )
