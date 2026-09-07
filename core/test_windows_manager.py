from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import SimpleTestCase

import windows_manager


class WindowsManagerProcessTests(
    SimpleTestCase
):
    @patch(
        "windows_manager._health_info",
        return_value={
            "application": "financeiro-ofx",
            "status": "ok",
            "pid": 1234,
        },
    )
    def test_server_running_uses_signed_health_endpoint(
        self,
        mocked_health,
    ):
        self.assertTrue(
            windows_manager.server_running()
        )
        mocked_health.assert_called()

    @patch(
        "windows_manager._elevated_stop_server_process"
    )
    @patch(
        "windows_manager._wait_server_stopped",
        side_effect=[
            False,
            True,
        ],
    )
    @patch(
        "windows_manager.run_command"
    )
    @patch(
        "windows_manager.running_server_pid",
        return_value=4321,
    )
    def test_stop_server_escalates_only_when_normal_kill_does_not_stop(
        self,
        mocked_pid,
        mocked_run,
        mocked_wait,
        mocked_elevated,
    ):
        mocked_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Acesso negado.",
        )

        with patch.object(
            windows_manager,
            "PID_FILE",
            MagicMock(),
        ):
            windows_manager.stop_server()

        mocked_elevated.assert_called_once_with(
            4321
        )
        self.assertEqual(
            mocked_wait.call_count,
            2,
        )

    @patch(
        "windows_manager.task_is_configured_for_autostart",
        return_value=True,
    )
    @patch(
        "windows_manager.task_exists",
        return_value=True,
    )
    @patch(
        "windows_manager._startup_task_elevated_action"
    )
    def test_install_startup_task_uses_elevated_registration_but_limited_task(
        self,
        mocked_action,
        mocked_exists,
        mocked_configured,
    ):
        mocked_pythonw = MagicMock()
        mocked_pythonw.exists.return_value = True

        with patch.object(
            windows_manager,
            "PYTHONW",
            mocked_pythonw,
        ):
            windows_manager.install_startup_task()

        mocked_action.assert_called_once_with(
            "Install"
        )
        mocked_exists.assert_called()
        mocked_configured.assert_called_once()
