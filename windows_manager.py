from __future__ import annotations

import base64
import os
import secrets
import shutil
import socket
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox
from tkinter import scrolledtext
import urllib.request
import webbrowser

from github_sync import GitSyncError
from github_sync import download_fast_forward
from github_sync import format_status as format_github_status
from github_sync import repository_status as github_repository_status


BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
PYTHON = VENV_DIR / "Scripts" / "python.exe"
PYTHONW = VENV_DIR / "Scripts" / "pythonw.exe"
SERVER_SCRIPT = BASE_DIR / "serve_waitress.py"
PID_FILE = BASE_DIR / "run" / "financeiro_ofx.pid"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "manager.log"
BACKUP_DIR = BASE_DIR / "backups"
TASK_NAME = "FinanceiroOFX"
TASK_LAUNCHER = BASE_DIR / "windows" / "start_hidden.vbs"
FIREWALL_SCRIPT = BASE_DIR / "windows" / "network_access.ps1"
FIREWALL_RULE_NAME = "Financeiro OFX - Rede Local"
APP_URL = "http://127.0.0.1:8000/"


def ensure_env_file():
    env_path = BASE_DIR / ".env"

    credential_key = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode("ascii")

    if not env_path.exists():
        secret = (
            "django-insecure-"
            + secrets.token_urlsafe(48)
        )

        env_path.write_text(
            (
                f"DJANGO_SECRET_KEY={secret}\n"
                "DJANGO_DEBUG=False\n"
                "DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost\n"
                "DJANGO_SECURE_MODE=False\n"
                "DJANGO_TRUST_PROXY_SSL_HEADER=False\n"
                "DJANGO_CSRF_TRUSTED_ORIGINS=\n"
                "FINANCEIRO_HOST=127.0.0.1\n"
                "FINANCEIRO_PORT=8000\n"
                "FINANCEIRO_ALLOW_NETWORK=False\n"
                "FINANCEIRO_LAN_MODE=False\n"
                f"FINANCEIRO_CREDENTIAL_KEY={credential_key}\n"
            ),
            encoding="utf-8",
        )
        return

    current = env_path.read_text(
        encoding="utf-8"
    )

    defaults = {
        "DJANGO_SECURE_MODE": "False",
        "DJANGO_TRUST_PROXY_SSL_HEADER": "False",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "",
        "FINANCEIRO_ALLOW_NETWORK": "False",
        "FINANCEIRO_LAN_MODE": "False",
        "FINANCEIRO_CREDENTIAL_KEY": credential_key,
    }

    existing_keys = {
        line.split("=", 1)[0].strip()
        for line in current.splitlines()
        if "=" in line
        and not line.lstrip().startswith("#")
    }

    missing_lines = [
        f"{key}={value}"
        for key, value in defaults.items()
        if key not in existing_keys
    ]

    if missing_lines:
        with env_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            if current and not current.endswith("\n"):
                file.write("\n")

            for line in missing_lines:
                file.write(line + "\n")


def read_env_values() -> dict[str, str]:
    env_path = BASE_DIR / ".env"

    if not env_path.exists():
        return {}

    values: dict[str, str] = {}

    for raw_line in env_path.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split(
            "=",
            1,
        )
        values[
            key.strip()
        ] = value.strip()

    return values


def update_env_values(
    updates: dict[str, str],
):
    env_path = BASE_DIR / ".env"

    if not env_path.exists():
        ensure_env_file()

    original_lines = env_path.read_text(
        encoding="utf-8"
    ).splitlines()

    pending = dict(
        updates
    )
    output_lines: list[str] = []

    for raw_line in original_lines:
        stripped = raw_line.strip()

        if (
            not stripped
            or stripped.startswith("#")
            or "=" not in raw_line
        ):
            output_lines.append(
                raw_line
            )
            continue

        key = raw_line.split(
            "=",
            1,
        )[0].strip()

        if key in pending:
            output_lines.append(
                f"{key}={pending.pop(key)}"
            )
        else:
            output_lines.append(
                raw_line
            )

    if pending:
        if (
            output_lines
            and output_lines[-1] != ""
        ):
            output_lines.append("")

        for key, value in pending.items():
            output_lines.append(
                f"{key}={value}"
            )

    temp_path = env_path.with_name(
        ".env.tmp"
    )
    temp_path.write_text(
        "\n".join(output_lines).rstrip()
        + "\n",
        encoding="utf-8",
    )
    os.replace(
        temp_path,
        env_path,
    )


def env_flag(
    name: str,
    default: bool = False,
) -> bool:
    value = read_env_values().get(
        name,
        str(default),
    )

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def server_port() -> int:
    value = read_env_values().get(
        "FINANCEIRO_PORT",
        "8000",
    )

    try:
        port = int(value)
    except ValueError:
        return 8000

    if not 1 <= port <= 65535:
        return 8000

    return port


def local_network_enabled() -> bool:
    return (
        env_flag(
            "FINANCEIRO_LAN_MODE",
            False,
        )
        and env_flag(
            "FINANCEIRO_ALLOW_NETWORK",
            False,
        )
    )


def detect_lan_ipv4() -> str:
    candidates: list[str] = []

    try:
        hostname = socket.gethostname()

        for address in socket.gethostbyname_ex(
            hostname
        )[2]:
            candidates.append(
                address
            )
    except OSError:
        pass

    # Consulta somente a tabela de rotas do Windows; não envia dados úteis.
    try:
        probe = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )
        probe.settimeout(0.5)
        probe.connect(
            (
                "1.1.1.1",
                80,
            )
        )
        candidates.insert(
            0,
            probe.getsockname()[0],
        )
        probe.close()
    except OSError:
        pass

    for address in candidates:
        parts = address.split(".")

        if len(parts) != 4:
            continue

        try:
            numbers = [
                int(part)
                for part in parts
            ]
        except ValueError:
            continue

        if not all(
            0 <= number <= 255
            for number in numbers
        ):
            continue

        if (
            numbers[0] == 10
            or (
                numbers[0] == 172
                and 16 <= numbers[1] <= 31
            )
            or (
                numbers[0] == 192
                and numbers[1] == 168
            )
        ):
            return address

    raise RuntimeError(
        (
            "Não foi possível identificar um IPv4 "
            "de rede local privada (10.x, 172.16-31.x ou 192.168.x)."
        )
    )


def lan_url() -> str | None:
    if not local_network_enabled():
        return None

    try:
        ip_address = detect_lan_ipv4()
    except RuntimeError:
        return None

    return (
        f"http://{ip_address}:"
        f"{server_port()}/"
    )


def _powershell_single_quote(
    value: str,
) -> str:
    return (
        "'"
        + value.replace(
            "'",
            "''",
        )
        + "'"
    )


def run_firewall_action(
    action: str,
):
    if action not in {
        "Open",
        "Close",
    }:
        raise ValueError(
            "Ação de firewall inválida."
        )

    if not FIREWALL_SCRIPT.exists():
        raise RuntimeError(
            f"Script de firewall não encontrado: {FIREWALL_SCRIPT}"
        )

    port = server_port()
    argument_line = (
        "-NoProfile "
        "-ExecutionPolicy Bypass "
        f'-File "{FIREWALL_SCRIPT}" '
        f"-Action {action} "
        f"-Port {port}"
    )
    quoted_arguments = (
        _powershell_single_quote(
            argument_line
        )
    )

    elevated_command = (
        "$process = Start-Process "
        "-FilePath 'powershell.exe' "
        f"-ArgumentList {quoted_arguments} "
        "-Verb RunAs "
        "-Wait "
        "-PassThru;"
        "exit $process.ExitCode"
    )

    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            elevated_command,
        ],
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        creationflags=creation_flags(),
    )

    if result.returncode != 0:
        detail = (
            result.stderr
            or result.stdout
            or (
                "A operação foi cancelada ou o "
                "Windows Firewall recusou a alteração."
            )
        ).strip()

        raise RuntimeError(
            (
                "Não foi possível alterar o Windows Firewall. "
                "Aceite a solicitação de administrador do Windows.\n\n"
                + detail
            )
        )


def refresh_lan_allowed_hosts():
    if not local_network_enabled():
        return

    try:
        ip_address = detect_lan_ipv4()
    except RuntimeError:
        return

    hostname = (
        socket.gethostname()
        .strip()
        .lower()
    )

    allowed_hosts = [
        "127.0.0.1",
        "localhost",
        ip_address,
    ]

    if hostname:
        allowed_hosts.append(
            hostname
        )

    update_env_values(
        {
            "DJANGO_ALLOWED_HOSTS": (
                ",".join(
                    dict.fromkeys(
                        allowed_hosts
                    )
                )
            ),
        }
    )


def open_local_network():
    ensure_env_file()

    ip_address = detect_lan_ipv4()
    hostname = (
        socket.gethostname()
        .strip()
        .lower()
    )

    allowed_hosts = [
        "127.0.0.1",
        "localhost",
        ip_address,
    ]

    if hostname:
        allowed_hosts.append(
            hostname
        )

    run_firewall_action(
        "Open"
    )

    update_env_values(
        {
            "DJANGO_DEBUG": "False",
            "DJANGO_ALLOWED_HOSTS": (
                ",".join(
                    dict.fromkeys(
                        allowed_hosts
                    )
                )
            ),
            "FINANCEIRO_HOST": "0.0.0.0",
            "FINANCEIRO_ALLOW_NETWORK": "True",
            "FINANCEIRO_LAN_MODE": "True",
        }
    )

    return (
        f"http://{ip_address}:"
        f"{server_port()}/"
    )


def close_local_network():
    ensure_env_file()

    firewall_error = None

    try:
        run_firewall_action(
            "Close"
        )
    except Exception as exc:
        # Mesmo que a regra do Firewall não possa ser removida,
        # o servidor é imediatamente reconfigurado para 127.0.0.1.
        # Assim não haverá serviço escutando pela rede.
        firewall_error = exc

    update_env_values(
        {
            "DJANGO_DEBUG": "False",
            "DJANGO_ALLOWED_HOSTS": (
                "127.0.0.1,localhost"
            ),
            "FINANCEIRO_HOST": "127.0.0.1",
            "FINANCEIRO_ALLOW_NETWORK": "False",
            "FINANCEIRO_LAN_MODE": "False",
        }
    )

    return firewall_error


def backup_database():
    database_path = BASE_DIR / "db.sqlite3"

    if not database_path.exists():
        return None

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = time.strftime(
        "%Y%m%d-%H%M%S"
    )

    backup_path = (
        BACKUP_DIR
        / f"db-before-update-{timestamp}.sqlite3"
    )

    shutil.copy2(
        database_path,
        backup_path,
    )

    return backup_path


def creation_flags():
    if os.name != "nt":
        return 0

    return (
        getattr(
            subprocess,
            "CREATE_NO_WINDOW",
            0,
        )
    )


def run_command(
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args,
        cwd=BASE_DIR,
        text=True,
        capture_output=True,
        creationflags=creation_flags(),
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            (
                result.stderr
                or result.stdout
                or f"Comando falhou: {args}"
            ).strip()
        )

    return result


def read_pid() -> int | None:
    try:
        value = PID_FILE.read_text(
            encoding="ascii"
        ).strip()
        return int(value)
    except (OSError, ValueError):
        return None


def is_process_running(pid: int) -> bool:
    if os.name != "nt":
        return False

    result = subprocess.run(
        [
            "tasklist",
            "/FI",
            f"PID eq {pid}",
            "/NH",
        ],
        text=True,
        capture_output=True,
        creationflags=creation_flags(),
    )

    return str(pid) in result.stdout


def server_running() -> bool:
    pid = read_pid()

    if pid and is_process_running(pid):
        return True

    try:
        with urllib.request.urlopen(
            APP_URL,
            timeout=1.0,
        ):
            return True
    except Exception:
        return False


def stop_server():
    pid = read_pid()

    if pid and is_process_running(pid):
        run_command(
            [
                "taskkill",
                "/PID",
                str(pid),
                "/T",
                "/F",
            ],
            check=False,
        )

    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def start_server():
    if server_running():
        return

    ensure_env_file()
    update_env_values(
        {
            "DJANGO_DEBUG": "False",
        }
    )
    refresh_lan_allowed_hosts()

    if not PYTHONW.exists():
        raise RuntimeError(
            "Ambiente virtual não encontrado. "
            "Use primeiro Instalar/Atualizar."
        )

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOG_FILE.open(
        "a",
        encoding="utf-8",
    ) as log:
        subprocess.Popen(
            [
                str(PYTHONW),
                str(SERVER_SCRIPT),
            ],
            cwd=BASE_DIR,
            stdout=log,
            stderr=log,
            creationflags=creation_flags(),
            close_fds=True,
        )

    for _ in range(30):
        if server_running():
            return

        time.sleep(0.2)

    raise RuntimeError(
        (
            "O processo foi iniciado, mas o servidor não respondeu em "
            f"{APP_URL}. Consulte: {LOG_FILE}"
        )
    )


def build_task_command() -> str:
    return (
        f'wscript.exe "{TASK_LAUNCHER}"'
    )


def task_exists() -> bool:
    result = run_command(
        [
            "schtasks",
            "/Query",
            "/TN",
            TASK_NAME,
        ],
        check=False,
    )
    return result.returncode == 0


def install_startup_task():
    if not TASK_LAUNCHER.exists():
        raise RuntimeError(
            f"Launcher não encontrado: {TASK_LAUNCHER}"
        )

    run_command(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            build_task_command(),
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ]
    )


def remove_startup_task():
    run_command(
        [
            "schtasks",
            "/Delete",
            "/TN",
            TASK_NAME,
            "/F",
        ],
        check=False,
    )


class ManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(
            "Financeiro OFX - Gerenciador"
        )
        self.geometry("760x660")
        self.minsize(720, 620)

        self.status_var = tk.StringVar()

        self._build_ui()
        self.refresh_status()

    def _build_ui(self):
        header = tk.Frame(self)
        header.pack(
            fill="x",
            padx=20,
            pady=(20, 10),
        )

        tk.Label(
            header,
            text="Financeiro OFX",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")

        tk.Label(
            header,
            text=(
                "Gerencie instalação, atualização e "
                "execução automática sem PowerShell."
            ),
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        status_frame = tk.LabelFrame(
            self,
            text="Status",
            padx=12,
            pady=10,
        )
        status_frame.pack(
            fill="x",
            padx=20,
            pady=10,
        )

        tk.Label(
            status_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 10, "bold"),
            justify="left",
        ).pack(anchor="w")

        buttons = tk.Frame(self)
        buttons.pack(
            fill="x",
            padx=20,
            pady=10,
        )

        options = [
            (
                "Instalar / Atualizar",
                self.install_update,
            ),
            (
                "Verificar / baixar GitHub",
                self.github_update_action,
            ),
            (
                "Iniciar servidor",
                self.start_action,
            ),
            (
                "Parar servidor",
                self.stop_action,
            ),
            (
                "Reiniciar servidor",
                self.restart_action,
            ),
            (
                "Abrir sistema",
                self.open_action,
            ),
            (
                "Abrir para rede local",
                self.open_lan_action,
            ),
            (
                "Fechar acesso de rede",
                self.close_lan_action,
            ),
            (
                "Ativar início automático",
                self.install_task_action,
            ),
            (
                "Remover início automático",
                self.remove_task_action,
            ),
        ]

        for index, (label, command) in enumerate(options):
            row = index // 2
            column = index % 2

            button = tk.Button(
                buttons,
                text=label,
                command=command,
                height=2,
            )
            button.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=5,
                pady=5,
            )

        buttons.columnconfigure(
            0,
            weight=1,
        )
        buttons.columnconfigure(
            1,
            weight=1,
        )

        log_frame = tk.LabelFrame(
            self,
            text="Log",
            padx=8,
            pady=8,
        )
        log_frame.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=(10, 20),
        )

        self.log_box = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            state="disabled",
            font=("Consolas", 9),
        )
        self.log_box.pack(
            fill="both",
            expand=True,
        )

    def log(self, message: str):
        self.log_box.configure(
            state="normal"
        )
        self.log_box.insert(
            "end",
            message.rstrip() + "\n",
        )
        self.log_box.see("end")
        self.log_box.configure(
            state="disabled"
        )
        self.update_idletasks()

    def refresh_status(self):
        running = server_running()
        automatic = task_exists()

        network_open = (
            local_network_enabled()
        )
        network_address = (
            lan_url()
            if network_open
            else None
        )

        self.status_var.set(
            (
                "Servidor: "
                + ("ATIVO" if running else "PARADO")
                + "\nInicialização automática: "
                + ("ATIVA" if automatic else "DESATIVADA")
                + "\nRede local: "
                + (
                    "ABERTA"
                    if network_open
                    else "FECHADA"
                )
                + f"\nEndereço local: {APP_URL}"
                + (
                    f"\nEndereço na rede: {network_address}"
                    if network_address
                    else ""
                )
            )
        )

    def _run_python_step(
        self,
        description: str,
        args: list[str],
    ):
        self.log(description + "...")

        result = run_command(
            [
                str(PYTHON),
                *args,
            ]
        )

        if result.stdout.strip():
            self.log(result.stdout)

    def _github_check(
        self,
        *,
        offer_download: bool,
        allow_continue_local: bool = False,
        installing: bool = False,
    ) -> bool:
        self.log(
            "Verificando atualizações no GitHub..."
        )

        try:
            status = (
                github_repository_status(
                    fetch=True
                )
            )
        except GitSyncError as exc:
            self.log(
                "GitHub: " + str(exc)
            )

            if allow_continue_local:
                return messagebox.askyesno(
                    "GitHub",
                    (
                        "Não foi possível verificar o GitHub:\n\n"
                        f"{exc}\n\n"
                        "Deseja continuar somente com os arquivos "
                        "locais atuais?"
                    ),
                )

            messagebox.showerror(
                "GitHub",
                str(exc),
            )
            return False

        self.log(
            format_github_status(
                status
            )
        )

        if status.initialized_now:
            messagebox.showinfo(
                "GitHub",
                (
                    "Esta pasta foi conectada ao repositório "
                    "do Financeiro OFX sem substituir arquivos locais.\n\n"
                    "Se aparecerem arquivos locais modificados, "
                    "revise-os ou envie-os ao GitHub antes de baixar."
                ),
            )

        if status.diverged:
            messagebox.showerror(
                "GitHub",
                (
                    "O histórico local e o GitHub divergiram.\n\n"
                    "Nenhum merge ou rebase será executado "
                    "automaticamente. Resolva a divergência antes "
                    "de atualizar."
                ),
            )
            return False

        if status.dirty:
            preview = "\n".join(
                status.changes[:12]
            )

            if len(status.changes) > 12:
                preview += (
                    "\n..."
                )

            messagebox.showwarning(
                "GitHub",
                (
                    "Existem arquivos locais alterados. "
                    "Por segurança, o download automático não "
                    "irá sobrescrevê-los.\n\n"
                    f"{preview}\n\n"
                    "Use Atualizar-GitHub.bat para enviar "
                    "alterações válidas ou revise-as manualmente."
                ),
            )

            if status.behind > 0:
                if allow_continue_local:
                    return messagebox.askyesno(
                        "Atualização local",
                        (
                            "Há atualização no GitHub, mas os arquivos "
                            "locais também foram alterados. O download "
                            "automático foi bloqueado.\n\n"
                            "Deseja continuar a instalação usando somente "
                            "os arquivos locais atuais?"
                        ),
                    )

                return False

            return True

        if status.local_ahead_only:
            messagebox.showwarning(
                "GitHub",
                (
                    f"Existem {status.ahead} commit(s) local(is) "
                    "ainda não enviados ao GitHub.\n\n"
                    "Envie-os antes de baixar novas alterações."
                ),
            )
            return True

        if not status.update_available:
            messagebox.showinfo(
                "GitHub",
                (
                    "Nenhuma atualização nova foi encontrada "
                    "no GitHub."
                ),
            )
            return True

        if not offer_download:
            messagebox.showinfo(
                "GitHub",
                (
                    f"Há {status.behind} commit(s) novo(s) "
                    "disponível(is) no GitHub."
                ),
            )
            return True

        confirm = messagebox.askyesno(
            "Atualização disponível",
            (
                f"Há {status.behind} commit(s) novo(s) no GitHub.\n\n"
                "O download usa fast-forward somente. "
                "Se houver divergência, a operação será cancelada.\n\n"
                "Deseja baixar agora?"
            ),
        )

        if not confirm:
            return True

        server_was_running = (
            server_running()
        )

        if server_was_running:
            self.log(
                (
                    "Parando servidor antes de substituir "
                    "arquivos do projeto..."
                )
            )
            stop_server()

        try:
            updated = (
                download_fast_forward()
            )
        except GitSyncError as exc:
            self.log(
                "ERRO GitHub: " + str(exc)
            )

            if server_was_running:
                try:
                    start_server()
                except Exception:
                    pass

            messagebox.showerror(
                "GitHub",
                str(exc),
            )
            return False

        self.log(
            "Download do GitHub concluído."
        )
        self.log(
            format_github_status(
                updated
            )
        )

        if installing:
            self.log(
                (
                    "GitHub atualizado. Continuando com validação, "
                    "testes e instalação local."
                )
            )
        else:
            messagebox.showinfo(
                "GitHub",
                (
                    "Arquivos atualizados pelo GitHub.\n\n"
                    "Execute Instalar / Atualizar para validar "
                    "dependências, testes, migrations e arquivos estáticos."
                ),
            )

        # O servidor fica parado até a instalação validar o novo código.
        return True

    def github_update_action(self):
        try:
            self._github_check(
                offer_download=True,
                allow_continue_local=False,
                installing=False,
            )
        finally:
            self.refresh_status()

    def install_update(self):
        try:
            github_choice = (
                messagebox.askyesnocancel(
                    "Atualização",
                    (
                        "Deseja verificar o GitHub antes da "
                        "instalação/atualização?\n\n"
                        "Sim = verificar e oferecer download\n"
                        "Não = usar somente os arquivos locais\n"
                        "Cancelar = não executar a atualização"
                    ),
                )
            )

            if github_choice is None:
                return

            if github_choice:
                if not self._github_check(
                    offer_download=True,
                    allow_continue_local=True,
                    installing=True,
                ):
                    return

            ensure_env_file()
            update_env_values(
                {
                    "DJANGO_DEBUG": "False",
                }
            )

            if not PYTHON.exists():
                messagebox.showerror(
                    "Ambiente virtual",
                    (
                        "A pasta .venv não existe. "
                        "Nesta instalação existente, execute uma vez "
                        "o setup.ps1 para criar o ambiente. "
                        "Depois disso este gerenciador substitui o "
                        "uso cotidiano do PowerShell."
                    ),
                )
                return

            self.log(
                "Iniciando atualização do Financeiro OFX."
            )

            self._run_python_step(
                "Atualizando dependências",
                [
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    "requirements.txt",
                ],
            )
            self._run_python_step(
                "Validando Django",
                [
                    "manage.py",
                    "check",
                ],
            )
            self._run_python_step(
                "Conferindo models e migrations",
                [
                    "manage.py",
                    "makemigrations",
                    "--check",
                    "--dry-run",
                ],
            )
            # A suíte roda ANTES de alterar o banco de dados local.
            # Assim uma atualização com regressão é interrompida sem
            # aplicar migrations no banco principal.
            self._run_python_step(
                "Executando testes",
                [
                    "manage.py",
                    "test",
                ],
            )

            backup_path = backup_database()

            if backup_path:
                self.log(
                    "Backup do banco criado: "
                    + str(backup_path)
                )

            self._run_python_step(
                "Aplicando migrations",
                [
                    "manage.py",
                    "migrate",
                ],
            )
            self._run_python_step(
                "Recriando vínculos de contrapartes",
                [
                    "manage.py",
                    "rebuild_counterparties",
                ],
            )
            self._run_python_step(
                "Analisando transferências internas",
                [
                    "manage.py",
                    "analyze_internal_transfers",
                ],
            )
            self._run_python_step(
                "Coletando arquivos estáticos",
                [
                    "manage.py",
                    "collectstatic",
                    "--noinput",
                ],
            )

            install_startup_task()

            stop_server()
            start_server()

            self.log(
                "Atualização concluída e servidor iniciado."
            )
            messagebox.showinfo(
                "Financeiro OFX",
                (
                    "Instalação/atualização concluída.\n\n"
                    "Se o Gerenciador também foi atualizado pelo GitHub, "
                    "feche esta janela e abra novamente para carregar "
                    "a versão nova da interface."
                ),
            )
        except Exception as exc:
            self.log(f"ERRO: {exc}")
            messagebox.showerror(
                "Erro",
                str(exc),
            )
        finally:
            self.refresh_status()

    def start_action(self):
        try:
            start_server()
            self.log("Servidor iniciado.")
        except Exception as exc:
            messagebox.showerror(
                "Erro",
                str(exc),
            )
        finally:
            self.refresh_status()

    def stop_action(self):
        stop_server()
        self.log("Servidor parado.")
        self.refresh_status()

    def restart_action(self):
        try:
            stop_server()
            start_server()
            self.log("Servidor reiniciado.")
        except Exception as exc:
            messagebox.showerror(
                "Erro",
                str(exc),
            )
        finally:
            self.refresh_status()

    def open_action(self):
        if not server_running():
            try:
                start_server()
            except Exception as exc:
                messagebox.showerror(
                    "Erro",
                    str(exc),
                )
                return

        webbrowser.open(APP_URL)
        self.refresh_status()

    def open_lan_action(self):
        if local_network_enabled():
            address = (
                lan_url()
                or "endereço não identificado"
            )
            messagebox.showinfo(
                "Rede local",
                (
                    "O acesso pela rede local já está aberto.\n\n"
                    f"Endereço: {address}"
                ),
            )
            self.refresh_status()
            return

        confirm = messagebox.askyesno(
            "Abrir para rede local",
            (
                "O Financeiro OFX ficará acessível a outros "
                "computadores/dispositivos da mesma sub-rede privada.\n\n"
                "O Windows solicitará permissão de administrador para "
                "criar uma regra de Firewall limitada ao perfil Private "
                "e à LocalSubnet.\n\n"
                "IMPORTANTE: este modo usa HTTP na rede local. Use apenas "
                "em uma rede privada e confiável. Para acesso pela Internet, "
                "use HTTPS/reverse proxy — não use esta opção.\n\n"
                "Deseja continuar?"
            ),
        )

        if not confirm:
            return

        try:
            stop_server()

            address = open_local_network()

            start_server()

            self.log(
                (
                    "Acesso pela rede local aberto: "
                    + address
                )
            )

            messagebox.showinfo(
                "Rede local aberta",
                (
                    "Acesso pela rede local habilitado.\n\n"
                    f"Endereço: {address}\n\n"
                    "A regra do Windows Firewall aceita somente a "
                    "sub-rede local no perfil de rede Private.\n\n"
                    "Se outro computador não acessar, confirme no Windows "
                    "se sua rede atual está marcada como Privada."
                ),
            )
        except Exception as exc:
            try:
                close_local_network()
            except Exception:
                pass

            try:
                start_server()
            except Exception:
                pass

            self.log(
                f"ERRO ao abrir rede local: {exc}"
            )
            messagebox.showerror(
                "Erro",
                str(exc),
            )
        finally:
            self.refresh_status()

    def close_lan_action(self):
        if not local_network_enabled():
            messagebox.showinfo(
                "Rede local",
                (
                    "O acesso pela rede local já está fechado. "
                    "O sistema permanece disponível apenas neste computador."
                ),
            )
            self.refresh_status()
            return

        try:
            stop_server()

            firewall_error = (
                close_local_network()
            )

            start_server()

            self.log(
                (
                    "Acesso pela rede local fechado. "
                    "Servidor voltou para 127.0.0.1."
                )
            )

            message = (
                "Acesso pela rede local fechado.\n\n"
                "O Financeiro OFX voltou a responder somente em:\n"
                f"{APP_URL}"
            )

            if firewall_error:
                message += (
                    "\n\nA regra do Firewall não pôde ser removida, "
                    "mas o servidor não está mais escutando na rede. "
                    "Para remover a regra também, execute esta ação "
                    "novamente e aceite a solicitação de administrador."
                )

            messagebox.showinfo(
                "Rede local fechada",
                message,
            )
        except Exception as exc:
            self.log(
                f"ERRO ao fechar rede local: {exc}"
            )
            messagebox.showerror(
                "Erro",
                str(exc),
            )
        finally:
            self.refresh_status()

    def install_task_action(self):
        try:
            install_startup_task()
            self.log(
                "Inicialização automática ativada."
            )
        except Exception as exc:
            messagebox.showerror(
                "Erro",
                str(exc),
            )
        finally:
            self.refresh_status()

    def remove_task_action(self):
        remove_startup_task()
        self.log(
            "Inicialização automática removida."
        )
        self.refresh_status()


if __name__ == "__main__":
    if "--start" in sys.argv:
        start_server()
        raise SystemExit(0)

    if "--stop" in sys.argv:
        stop_server()
        raise SystemExit(0)

    app = ManagerApp()
    app.mainloop()
