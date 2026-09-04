from decimal import Decimal
from django.conf import settings
from django.test import SimpleTestCase
from django.test import TestCase
from django.urls import reverse


class HomeAuthenticationTests(TestCase):
    def test_home_requires_authentication(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)



class DashboardTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            username="dashboard-user",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

    def test_dashboard_contains_chart_payloads(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "dashboardData",
        )
        self.assertContains(
            response,
            "periodMovementChart",
        )
        # Sem saídas no período, o template mostra a mensagem de vazio
        # e não renderiza o canvas expenseChart. O payload, entretanto,
        # deve sempre existir para o JavaScript do Dashboard.
        self.assertContains(
            response,
            "data-expense-chart",
        )
        self.assertContains(
            response,
            "Ocultar valores",
        )



class DashboardPeriodTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            username="dashboard-period-user",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

    def test_dashboard_accepts_month_filter(self):
        response = self.client.get(
            reverse("home"),
            data={"month": "2026-05"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["period_start"],
            "2026-05-01",
        )
        self.assertEqual(
            response.context["period_end"],
            "2026-05-31",
        )
        self.assertEqual(
            response.context["selected_month"],
            "2026-05",
        )

    def test_dashboard_accepts_custom_period(self):
        response = self.client.get(
            reverse("home"),
            data={
                "date_from": "2026-02-15",
                "date_to": "2026-03-05",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["period_start"],
            "2026-02-15",
        )
        self.assertEqual(
            response.context["period_end"],
            "2026-03-05",
        )
        self.assertEqual(
            response.context["selected_month"],
            "",
        )



class DashboardYearTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            username="dashboard-year-user",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

    def test_dashboard_accepts_year_filter(self):
        response = self.client.get(
            reverse("home"),
            data={"year": "2026"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["period_start"],
            "2026-01-01",
        )
        self.assertEqual(
            response.context["period_end"],
            "2026-12-31",
        )
        self.assertEqual(
            response.context["period_mode"],
            "year",
        )
        self.assertEqual(
            len(
                response.context[
                    "month_drilldown"
                ]
            ),
            12,
        )

    def test_annual_chart_has_month_drilldown_urls(self):
        response = self.client.get(
            reverse("home"),
            data={"year": "2026"},
        )

        chart = response.context[
            "period_chart"
        ]

        self.assertEqual(
            chart["grouping"],
            "month",
        )
        self.assertEqual(
            len(
                chart[
                    "drilldown_urls"
                ]
            ),
            12,
        )
        self.assertEqual(
            chart[
                "drilldown_urls"
            ][0],
            "?month=2026-01",
        )



class DashboardBankFilterTests(TestCase):
    def setUp(self):
        from datetime import datetime
        from decimal import Decimal

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from finance.models import Account
        from finance.models import Bank
        from finance.models import Transaction

        self.user = get_user_model().objects.create_user(
            username="dashboard-bank-user",
            password="safe-password-123",
        )
        self.client.force_login(self.user)

        self.bank_a = Bank.objects.create(
            name="Banco A",
            code="901",
        )
        self.bank_b = Bank.objects.create(
            name="Banco B",
            code="902",
        )

        self.account_a = Account.objects.create(
            bank=self.bank_a,
            nickname="Conta A",
            branch="1",
            number="100",
        )
        self.account_b = Account.objects.create(
            bank=self.bank_b,
            nickname="Conta B",
            branch="1",
            number="200",
        )

        posted_at = timezone.make_aware(
            datetime(
                2026,
                8,
                10,
                10,
                0,
            )
        )

        Transaction.objects.create(
            account=self.account_a,
            posted_at=posted_at,
            amount=Decimal("100.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            raw_description="Entrada A",
        )
        Transaction.objects.create(
            account=self.account_a,
            posted_at=posted_at,
            amount=Decimal("30.00"),
            direction=Transaction.Direction.DEBIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            raw_description="Saída A",
        )
        Transaction.objects.create(
            account=self.account_b,
            posted_at=posted_at,
            amount=Decimal("500.00"),
            direction=Transaction.Direction.CREDIT,
            transaction_type=Transaction.TransactionType.PIX,
            source_type=Transaction.SourceType.OFX,
            raw_description="Entrada B",
        )

    def test_dashboard_filters_everything_by_bank(self):
        response = self.client.get(
            reverse("home"),
            data={
                "month": "2026-08",
                "bank": str(
                    self.bank_a.pk
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.context[
                "selected_bank"
            ].pk,
            self.bank_a.pk,
        )
        self.assertEqual(
            response.context[
                "period_credit"
            ],
            Decimal("100.00"),
        )
        self.assertEqual(
            response.context[
                "period_debit"
            ],
            Decimal("30.00"),
        )
        self.assertEqual(
            response.context[
                "transaction_count"
            ],
            2,
        )
        self.assertEqual(
            response.context[
                "expense_chart_title"
            ],
            "Saídas por conta",
        )
        self.assertContains(
            response,
            'id="expenseChart"',
        )

    def test_dashboard_all_banks_keeps_consolidated_view(self):
        response = self.client.get(
            reverse("home"),
            data={
                "month": "2026-08",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertIsNone(
            response.context[
                "selected_bank"
            ]
        )
        self.assertEqual(
            response.context[
                "transaction_count"
            ],
            3,
        )
        self.assertEqual(
            response.context[
                "expense_chart_title"
            ],
            "Saídas por banco",
        )

    def test_annual_drilldown_preserves_bank(self):
        response = self.client.get(
            reverse("home"),
            data={
                "year": "2026",
                "bank": str(
                    self.bank_a.pk
                ),
            },
        )

        chart = response.context[
            "period_chart"
        ]

        self.assertEqual(
            chart[
                "drilldown_urls"
            ][0],
            (
                "?month=2026-01&bank="
                f"{self.bank_a.pk}"
            ),
        )


class SecureLoginThrottleTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            username="secure-login-user",
            password="correct-password-123",
        )

    def test_repeated_invalid_login_is_throttled(self):
        from django.test import override_settings

        with override_settings(
            LOGIN_THROTTLE_USERNAME_MAX=2,
            LOGIN_THROTTLE_IP_MAX=20,
            LOGIN_THROTTLE_WINDOW_SECONDS=900,
            LOGIN_THROTTLE_LOCK_SECONDS=900,
        ):
            first = self.client.post(
                reverse("login"),
                {
                    "username": "secure-login-user",
                    "password": "wrong-password",
                },
                REMOTE_ADDR="127.0.0.55",
            )
            second = self.client.post(
                reverse("login"),
                {
                    "username": "secure-login-user",
                    "password": "wrong-password",
                },
                REMOTE_ADDR="127.0.0.55",
            )
            blocked = self.client.post(
                reverse("login"),
                {
                    "username": "secure-login-user",
                    "password": "correct-password-123",
                },
                REMOTE_ADDR="127.0.0.55",
            )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        self.assertEqual(
            blocked.status_code,
            429,
        )
        self.assertContains(
            blocked,
            "Usuário ou senha inválidos",
            status_code=429,
        )



class StaticFilesTestConfigurationTests(SimpleTestCase):
    def test_test_suite_does_not_use_manifest_static_storage(self):
        self.assertEqual(
            settings.STORAGES[
                "staticfiles"
            ][
                "BACKEND"
            ],
            (
                "django.contrib.staticfiles.storage."
                "StaticFilesStorage"
            ),
        )
