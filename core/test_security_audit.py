from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from core.management.commands.security_audit import Command


class SecurityAuditSettingsTests(
    SimpleTestCase
):
    @override_settings(
        SECRET_KEY="Ab3$xY9!" * 10,
        DEBUG=False,
        ALLOWED_HOSTS=[
            "127.0.0.1",
            "localhost",
        ],
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        X_FRAME_OPTIONS="DENY",
        SECURE_MODE=False,
    )
    def test_strong_secret_key_is_not_high_finding(self):
        findings = (
            Command()
            ._settings_findings()
        )

        self.assertFalse(
            any(
                item.code == "CFG004"
                and item.severity == "HIGH"
                for item in findings
            )
        )

    @override_settings(
        SECRET_KEY=(
            "django-insecure-"
            + "x" * 60
        ),
        DEBUG=False,
        ALLOWED_HOSTS=[
            "127.0.0.1",
            "localhost",
        ],
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        X_FRAME_OPTIONS="DENY",
        SECURE_MODE=False,
    )
    def test_legacy_django_insecure_key_is_high_finding(self):
        findings = (
            Command()
            ._settings_findings()
        )

        self.assertTrue(
            any(
                item.code == "CFG004"
                and item.severity == "HIGH"
                for item in findings
            )
        )

    @override_settings(
        SECRET_KEY="Ab3$xY9!" * 10,
        DEBUG=False,
        ALLOWED_HOSTS=[
            "127.0.0.1",
            "localhost",
            "192.168.1.10",
        ],
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        X_FRAME_OPTIONS="DENY",
        SECURE_MODE=False,
    )
    @patch.dict(
        "os.environ",
        {
            "FINANCEIRO_HOST": "0.0.0.0",
            "FINANCEIRO_ALLOW_NETWORK": "True",
            "FINANCEIRO_LAN_MODE": "True",
        },
        clear=False,
    )
    def test_private_lan_warning_is_not_high(self):
        findings = (
            Command()
            ._django_check_findings()
        )

        lan_findings = [
            item
            for item in findings
            if (
                item.code
                == (
                    "DJANGO-"
                    "financeiro_security.W003"
                )
            )
        ]

        self.assertTrue(
            lan_findings
        )
        self.assertTrue(
            all(
                item.severity != "HIGH"
                for item in lan_findings
            )
        )
