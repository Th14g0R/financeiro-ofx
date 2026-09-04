from django.core.management.base import BaseCommand

from services.internal_transfers import analyze_internal_transfers


class Command(BaseCommand):
    help = (
        "Analisa movimentações entre contas próprias e cria "
        "vínculos confirmados ou sugestões para revisão."
    )

    def handle(
        self,
        *args,
        **options,
    ):
        result = (
            analyze_internal_transfers()
        )

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Análise de transferências internas concluída: "
                    f"{result['confirmed']} confirmada(s), "
                    f"{result['possible']} possível(is), "
                    f"{result['skipped_ambiguous']} ambígua(s)."
                )
            )
        )
