from django.core.management.base import BaseCommand

from services.counterparties import rebuild_counterparty_links


class Command(BaseCommand):
    help = (
        "Reanalisa todas as movimentações bancárias, saneia nomes legados "
        "e cria/vincula contrapartes usando os padrões atuais de PIX/transferência."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair-bank-groups", action="store_true",
            help="Isola agrupamentos por ISPB e refaz os vínculos pelos dados originais.",
        )

    def handle(self, *args, **options):
        result = rebuild_counterparty_links(repair_bank_groups=options["repair_bank_groups"])

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Contrapartes reconstruídas: "
                    f"{result['linked']} vínculo(s) em {result['total']} movimentação(ões); "
                    f"{result['reassigned']} reatribuição(ões); "
                    f"{result['unlinked']} sem contraparte reconhecível; "
                    f"{result['renamed']} nome(s) legado(s) saneado(s); "
                    f"{result['merged']} duplicidade(s) exata(s)/por identificador mesclada(s); "
                    f"{result['truncated_merged']} nome(s) truncado(s) mesclado(s); "
                    f"{result['quarantined']} agrupamento(s) bancário(s) isolado(s); "
                    f"{result['orphaned']} cadastro(s) órfão(s) desativado(s)."
                )
            )
        )
