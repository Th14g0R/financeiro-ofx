from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse


class HealthCheckTests(SimpleTestCase):
    def test_health_signature_and_no_store(self):
        response = self.client.get(
            reverse("health_check")
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["application"],
            "financeiro-ofx",
        )
        self.assertEqual(
            response.json()["status"],
            "ok",
        )
        self.assertIn(
            "no-store",
            response.headers[
                "Cache-Control"
            ],
        )

    @patch(
        "core.health.os.getpid",
        return_value=43210,
    )
    def test_loopback_health_exposes_pid_to_local_manager(
        self,
        mocked_getpid,
    ):
        response = self.client.get(
            reverse("health_check"),
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertEqual(
            response.json()["pid"],
            43210,
        )
        mocked_getpid.assert_called_once()

    def test_lan_health_does_not_expose_pid(self):
        response = self.client.get(
            reverse("health_check"),
            REMOTE_ADDR="192.168.1.25",
        )

        self.assertNotIn(
            "pid",
            response.json(),
        )
