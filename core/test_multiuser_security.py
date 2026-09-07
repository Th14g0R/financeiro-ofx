from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from core.models import AuditEvent
from core.models import SecurityEvent
from core.models import UserAccessProfile


class PageTitleConventionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="title-user",
            password="Strong-password-2026!",
        )
        self.user.access_profile.role = UserAccessProfile.Role.ADMIN
        self.user.access_profile.save(
            update_fields=["role", "updated_at"]
        )
        self.client.force_login(self.user)

    def test_dashboard_title_starts_with_system_name(self):
        response = self.client.get(reverse("home"))
        self.assertIn(
            b"<title>Financeiro | Dashboard</title>",
            response.content,
        )


    def test_main_pages_render_expected_browser_titles(self):
        cases = [
            (reverse("home"), "Financeiro | Dashboard"),
            (reverse("finance:transaction-list"), "Financeiro | Extrato"),
            (reverse("finance:counterparty-list"), "Financeiro | Pessoas"),
            (reverse("imports:history"), "Financeiro | Histórico de importações"),
            (reverse("finance:bank-list"), "Financeiro | Bancos"),
            (reverse("finance:account-list"), "Financeiro | Contas"),
            (reverse("finance:internal-transfer-list"), "Financeiro | Transferências internas"),
            (reverse("integrations:list"), "Financeiro | Integrações"),
            (reverse("system_user_list"), "Financeiro | Usuários"),
            (reverse("audit_list"), "Financeiro | Auditoria"),
        ]

        for url, title in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f"<title>{title}</title>",
                    html=True,
                )

    def test_all_templates_use_new_title_convention(self):
        template_dir = Path(settings.BASE_DIR) / "templates"
        contents = "\n".join(
            path.read_text(encoding="utf-8")
            for path in template_dir.rglob("*.html")
        )
        self.assertNotIn("| Financeiro OFX", contents)
        base = (template_dir / "base.html").read_text(encoding="utf-8")
        self.assertIn(
            "<title>Financeiro | {% block title %}Dashboard{% endblock %}</title>",
            base,
        )


class MultiUserAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="owner-user",
            password="Strong-password-2026!",
            email="owner@example.com",
        )
        self.admin.access_profile.role = UserAccessProfile.Role.ADMIN
        self.admin.access_profile.save(update_fields=["role", "updated_at"])

        self.operator = user_model.objects.create_user(
            username="trusted-operator",
            password="Strong-password-2026!",
            email="operator@example.com",
        )

    def test_operator_can_use_shared_financial_pages(self):
        self.client.force_login(self.operator)
        allowed_urls = [
            reverse("home"),
            reverse("finance:transaction-list"),
            reverse("imports:history"),
            reverse("finance:counterparty-list"),
            reverse("integrations:list"),
        ]

        for url in allowed_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_operator_cannot_manage_users_or_view_audit(self):
        self.client.force_login(self.operator)
        self.assertEqual(
            self.client.get(reverse("system_user_list")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("audit_list")).status_code,
            403,
        )


    def test_operator_denied_admin_page_is_audited(self):
        self.client.force_login(self.operator)
        response = self.client.get(
            reverse("system_user_list")
        )
        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.operator,
                status_code=403,
                success=False,
                method="GET",
            ).exists()
        )

    def test_operator_cannot_change_integration_credentials(self):
        self.client.force_login(self.operator)
        response = self.client.get(reverse("integrations:create"))
        self.assertEqual(response.status_code, 403)


    def test_user_management_write_flow_is_blocked_on_remote_http(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("system_user_create"),
            REMOTE_ADDR="192.168.1.25",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("system_user_list"),
        )

    def test_admin_can_create_trusted_operator(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system_user_create"),
            {
                "administrator_password": "Strong-password-2026!",
                "username": "spouse-user",
                "first_name": "Pessoa",
                "last_name": "Confiável",
                "email": "spouse@example.com",
                "role": UserAccessProfile.Role.OPERATOR,
                "password1": "Another-strong-pass-2026!",
                "password2": "Another-strong-pass-2026!",
            },
        )
        self.assertEqual(response.status_code, 302)
        created = get_user_model().objects.get(username="spouse-user")
        self.assertEqual(
            created.access_profile.role,
            UserAccessProfile.Role.OPERATOR,
        )
        self.assertFalse(created.is_superuser)
        self.assertFalse(created.is_staff)

    def test_deactivating_user_invalidates_existing_session(self):
        operator_client = Client()
        self.assertTrue(
            operator_client.login(
                username=self.operator.username,
                password="Strong-password-2026!",
            )
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system_user_update", args=[self.operator.pk]),
            {
                "administrator_password": "Strong-password-2026!",
                "first_name": self.operator.first_name,
                "last_name": self.operator.last_name,
                "email": self.operator.email,
                "role": UserAccessProfile.Role.OPERATOR,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.operator.refresh_from_db()
        self.assertFalse(self.operator.is_active)

        blocked = operator_client.get(reverse("home"))
        self.assertEqual(blocked.status_code, 302)
        self.assertIn(reverse("login"), blocked.url)

    def test_system_keeps_at_least_one_active_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system_user_update", args=[self.admin.pk]),
            {
                "administrator_password": "Strong-password-2026!",
                "first_name": self.admin.first_name,
                "last_name": self.admin.last_name,
                "email": self.admin.email,
                "role": UserAccessProfile.Role.OPERATOR,
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.admin.access_profile.refresh_from_db()
        self.assertEqual(
            self.admin.access_profile.role,
            UserAccessProfile.Role.ADMIN,
        )


class OperationAuditTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="audit-user",
            password="Strong-password-2026!",
            email="audit-old@example.com",
        )
        self.client.force_login(self.user)

    def test_authenticated_post_is_attributed_to_user(self):
        response = self.client.post(
            reverse("account_profile"),
            {
                "email": "audit-new@example.com",
                "current_password": "Strong-password-2026!",
            },
        )
        self.assertEqual(response.status_code, 302)

        event = AuditEvent.objects.filter(
            actor=self.user,
            action="account_profile",
            method="POST",
        ).latest("created_at")

        self.assertTrue(event.success)
        self.assertEqual(event.status_code, 302)
        serialized = str(event.detail)
        self.assertNotIn("Strong-password-2026!", serialized)
        self.assertNotIn("current_password", event.detail.get("form_fields", []))

    def test_response_contains_request_id(self):
        response = self.client.get(reverse("home"))
        self.assertIn("X-Request-ID", response.headers)


class AuthenticationSecurityEventTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="auth-event-user",
            password="Strong-password-2026!",
        )

    def test_invalid_login_creates_security_event_without_password(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": "wrong-secret-password",
            },
        )
        self.assertEqual(response.status_code, 200)
        event = SecurityEvent.objects.filter(
            event_type=SecurityEvent.EventType.LOGIN_FAILURE,
            success=False,
        ).latest("created_at")
        self.assertNotIn(
            "wrong-secret-password",
            str(event.detail),
        )


class WebSecurityRegressionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="security-regression-user",
            password="Strong-password-2026!",
        )

    def test_remote_http_admin_surface_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/admin/",
            REMOTE_ADDR="192.168.1.25",
        )
        self.assertEqual(response.status_code, 403)

    def test_remote_http_password_change_is_blocked(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("password_change"),
            REMOTE_ADDR="192.168.1.25",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("account_profile"),
        )

    def test_remote_http_recovery_email_change_is_blocked(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account_profile"),
            {
                "email": "changed@example.com",
                "current_password": "Strong-password-2026!",
            },
            REMOTE_ADDR="192.168.1.25",
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertNotEqual(
            self.user.email,
            "changed@example.com",
        )

    def test_login_post_without_csrf_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": "Strong-password-2026!",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_login_does_not_reflect_raw_script(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "<script>alert(1)</script>",
                "password": "invalid-password",
            },
        )
        body = response.content.decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)

    @override_settings(
        ALLOWED_HOSTS=[
            "testserver",
            "127.0.0.1",
            "localhost",
        ]
    )
    def test_untrusted_host_header_is_rejected(self):
        response = self.client.get(
            reverse("login"),
            HTTP_HOST="attacker.invalid",
        )
        self.assertEqual(response.status_code, 400)

    def test_unauthenticated_financial_pages_require_login(self):
        protected_urls = [
            reverse("home"),
            reverse("finance:transaction-list"),
            reverse("imports:history"),
            reverse("finance:counterparty-list"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_sql_like_search_payload_does_not_bypass_or_error(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("finance:transaction-list"),
            {"q": "' OR 1=1 --"},
        )
        self.assertEqual(response.status_code, 200)

    def test_search_payload_is_html_escaped(self):
        self.client.force_login(self.user)
        payload = "<img src=x onerror=alert(1)>"
        response = self.client.get(
            reverse("finance:transaction-list"),
            {"q": payload},
        )
        body = response.content.decode("utf-8")
        self.assertNotIn(payload, body)
        self.assertIn("&lt;img", body)

    def test_authenticated_pages_are_not_browser_cached(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache_control)
        self.assertIn("private", cache_control)

    def test_uploaded_media_is_not_exposed_by_django_routes(self):
        response = self.client.get("/media/private-bank-statement.pdf")
        self.assertEqual(response.status_code, 404)

    def test_security_headers_are_present(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            response.headers.get("X-Content-Type-Options"),
            "nosniff",
        )
        self.assertIn(
            "default-src 'self'",
            response.headers.get("Content-Security-Policy", ""),
        )
        self.assertIn(
            "frame-ancestors 'none'",
            response.headers.get("Content-Security-Policy", ""),
        )
