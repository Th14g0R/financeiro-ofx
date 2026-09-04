from decimal import Decimal

from django.test import SimpleTestCase

from finance.templatetags.finance_extras import brl
from finance.templatetags.finance_extras import brl_signed


class BrlFormattingTests(SimpleTestCase):
    def test_positive_brl_format(self):
        self.assertEqual(
            brl(
                Decimal("8261.44")
            ),
            "R$ 8.261,44",
        )

    def test_negative_brl_format(self):
        self.assertEqual(
            brl(
                Decimal("-127.64")
            ),
            "-R$ 127,64",
        )

    def test_signed_debit_format(self):
        self.assertEqual(
            brl_signed(
                Decimal("-8.98")
            ),
            "- R$ 8,98",
        )
