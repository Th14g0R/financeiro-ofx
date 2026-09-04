from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent

REPOSITORY_URL = (
    "https://github.com/Th14g0R/financeiro-ofx.git"
)
REMOTE_NAME = "origin"
DEFAULT_BRANCH = "main"

# Somente estes caminhos fazem parte do código-fonte publicável.
# Isso evita que arquivos criados localmente sejam enviados por engano.
ESSENTIAL_TOP_LEVEL_DIRS = (
    "config",
    "core",
    "finance",
    "imports",
    "integrations",
    "services",
    "static",
    "templates",
    "windows",
)

ESSENTIAL_TOP_LEVEL_FILES = (
    ".env.example",
    ".gitignore",
    "Abrir-Financeiro-OFX.bat",
    "Atualizar-GitHub.bat",
    "Baixar-Atualizacao-GitHub.bat",
    "GITHUB.md",
    "Gerenciar-Financeiro-OFX.bat",
    "MERCADO_PAGO_SETUP.md",
    "README.md",
    "SECURITY.md",
    "github_sync.py",
    "manage.py",
    "requirements.txt",
    "run.ps1",
    "serve_waitress.py",
    "setup.ps1",
    "windows_manager.py",
)

# A interface gráfica não pode depender de prompt textual invisível.
# Nos BATs/CLI este valor é ligado para permitir autenticação HTTPS/GCM.
CLI_INTERACTIVE = False

RUN_DIR = BASE_DIR / "run"

FORBIDDEN_EXACT_PATHS = {
    ".env",
    "db.sqlite3",
}

FORBIDDEN_PREFIXES = (
    ".venv/",
    "venv/",
    "media/",
    "backups/",
    "logs/",
    "run/",
    "staticfiles/",
    "__pycache__/",
    ".pytest_cache/",
)

FORBIDDEN_SUFFIXES = (
    ".pyc",
    ".sqlite3",
    ".sqlite3-journal",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".ofx",
    ".qfx",
    ".pdf",
    ".csv",
    ".xls",
    ".xlsx",
    ".ods",
)

SECRET_PATTERNS = (
    (
        "Mercado Pago Access Token",
        re.compile(
            rb"\bAPP_USR-[A-Za-z0-9_-]{20,}\b"
        ),
    ),
    (
        "GitHub token clássico",
        re.compile(
            rb"\bghp_[A-Za-z0-9]{20,}\b"
        ),
    ),
    (
        "GitHub fine-grained token",
        re.compile(
            rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"
        ),
    ),
    (
        "Chave privada",
        re.compile(
            rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"
        ),
    ),
    (
        "DJANGO_SECRET_KEY preenchida",
        re.compile(
            rb"(?im)^\s*DJANGO_SECRET_KEY\s*=\s*"
            rb"(?!troque|change|exemplo|example|\s*$)"
            rb"\S{16,}\s*$"
        ),
    ),
    (
        "FINANCEIRO_CREDENTIAL_KEY preenchida",
        re.compile(
            rb"(?im)^\s*FINANCEIRO_CREDENTIAL_KEY\s*=\s*"
            rb"(?!troque|change|exemplo|example|\s*$)"
            rb"\S{16,}\s*$"
        ),
    ),
)


class GitSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RepositoryStatus:
    branch: str
    remote_branch: str
    head: str
    remote_head: str
    ahead: int
    behind: int
    dirty: bool
    changes: tuple[str, ...]
    initialized_now: bool

    @property
    def diverged(self) -> bool:
        return (
            self.ahead > 0
            and self.behind > 0
        )

    @property
    def update_available(self) -> bool:
        return (
            self.behind > 0
            and self.ahead == 0
        )

    @property
    def local_ahead_only(self) -> bool:
        return (
            self.ahead > 0
            and self.behind == 0
        )


def _creation_flags() -> int:
    if os.name != "nt":
        return 0

    return getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )


def git_executable() -> str:
    executable = shutil.which(
        "git"
    )

    if not executable:
        raise GitSyncError(
            (
                "Git não foi encontrado no Windows. "
                "Instale o Git for Windows e abra novamente "
                "o Gerenciador."
            )
        )

    return executable


def _run_git(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    interactive: bool | None = None,
) -> subprocess.CompletedProcess:
    command = [
        git_executable(),
        *args,
    ]

    kwargs = {
        "cwd": BASE_DIR,
        "text": True,
        "creationflags": (
            _creation_flags()
        ),
    }

    if capture:
        kwargs.update(
            {
                "capture_output": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
        )

    env = os.environ.copy()

    if interactive is None:
        interactive = (
            CLI_INTERACTIVE
        )

    if interactive:
        env.pop(
            "GIT_TERMINAL_PROMPT",
            None,
        )
    else:
        # Git Credential Manager ainda pode abrir sua UI no Windows.
        # Apenas evita um prompt textual invisível em processos GUI.
        env.setdefault(
            "GIT_TERMINAL_PROMPT",
            "0",
        )

    kwargs["env"] = env

    result = subprocess.run(
        command,
        **kwargs,
    )

    if (
        check
        and result.returncode != 0
    ):
        detail = ""

        if capture:
            detail = (
                result.stderr
                or result.stdout
                or ""
            ).strip()

        if not detail:
            detail = (
                "O Git retornou código "
                f"{result.returncode}."
            )

        raise GitSyncError(
            detail
        )

    return result


def _normalize_remote_url(
    value: str,
) -> str:
    value = (
        value.strip()
        .rstrip("/")
    )

    if value.endswith(
        ".git"
    ):
        value = value[:-4]

    return value.lower()


def is_git_repository() -> bool:
    result = _run_git(
        [
            "rev-parse",
            "--is-inside-work-tree",
        ],
        check=False,
    )

    return (
        result.returncode == 0
        and result.stdout.strip()
        == "true"
    )


def _remote_url() -> str:
    result = _run_git(
        [
            "remote",
            "get-url",
            REMOTE_NAME,
        ],
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def _configure_expected_remote() -> None:
    current = _remote_url()

    if not current:
        _run_git(
            [
                "remote",
                "add",
                REMOTE_NAME,
                REPOSITORY_URL,
            ]
        )
        return

    if (
        _normalize_remote_url(
            current
        )
        != _normalize_remote_url(
            REPOSITORY_URL
        )
    ):
        raise GitSyncError(
            (
                "O remote 'origin' desta pasta aponta para outro "
                "repositório:\n\n"
                f"{current}\n\n"
                "Por segurança, o sistema não alterou a URL "
                "automaticamente."
            )
        )


def _remote_default_branch() -> str:
    result = _run_git(
        [
            "ls-remote",
            "--symref",
            REMOTE_NAME,
            "HEAD",
        ],
        check=False,
    )

    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if (
                line.startswith(
                    "ref: refs/heads/"
                )
                and line.endswith(
                    "\tHEAD"
                )
            ):
                value = (
                    line.split(
                        "\t",
                        1,
                    )[0]
                    .removeprefix(
                        "ref: refs/heads/"
                    )
                    .strip()
                )

                if value:
                    return value

    # Repositório recém-criado/sem HEAD remoto:
    # usa main, padrão atual do projeto.
    return DEFAULT_BRANCH


def _remote_branch_exists(
    branch: str,
) -> bool:
    result = _run_git(
        [
            "ls-remote",
            "--exit-code",
            "--heads",
            REMOTE_NAME,
            branch,
        ],
        check=False,
    )

    return (
        result.returncode == 0
        and bool(
            result.stdout.strip()
        )
    )


def _current_branch() -> str:
    result = _run_git(
        [
            "branch",
            "--show-current",
        ],
        check=False,
    )

    return result.stdout.strip()


def _head_exists() -> bool:
    result = _run_git(
        [
            "rev-parse",
            "--verify",
            "HEAD",
        ],
        check=False,
    )
    return result.returncode == 0


def _ref_sha(
    ref: str,
) -> str:
    result = _run_git(
        [
            "rev-parse",
            "--verify",
            ref,
        ],
        check=False,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def ensure_repository_connection() -> bool:
    initialized_now = False

    if not is_git_repository():
        _run_git(
            [
                "init",
            ]
        )
        initialized_now = True

    _configure_expected_remote()

    remote_branch = (
        _remote_default_branch()
    )

    current_branch = (
        _current_branch()
    )
    needs_bootstrap = (
        not _head_exists()
    )

    if (
        initialized_now
        or not current_branch
        or needs_bootstrap
    ):
        # Não mexe nos arquivos. Apenas aponta HEAD para o branch esperado.
        _run_git(
            [
                "symbolic-ref",
                "HEAD",
                (
                    "refs/heads/"
                    + remote_branch
                ),
            ]
        )

    if (
        needs_bootstrap
        and _remote_branch_exists(
            remote_branch
        )
    ):
        _run_git(
            [
                "fetch",
                "--prune",
                REMOTE_NAME,
                (
                    f"+refs/heads/{remote_branch}:"
                    f"refs/remotes/{REMOTE_NAME}/{remote_branch}"
                ),
            ]
        )

        # `reset --mixed` conecta o histórico local ao remoto SEM
        # substituir o conteúdo da pasta. Arquivos locais diferentes
        # passam a aparecer como modificados e precisam ser revisados.
        _run_git(
            [
                "reset",
                "--mixed",
                (
                    f"refs/remotes/{REMOTE_NAME}/"
                    f"{remote_branch}"
                ),
            ]
        )

    return initialized_now


def fetch_remote(
    branch: str,
) -> None:
    if not _remote_branch_exists(
        branch
    ):
        return

    _run_git(
        [
            "fetch",
            "--prune",
            REMOTE_NAME,
            (
                f"+refs/heads/{branch}:"
                f"refs/remotes/{REMOTE_NAME}/{branch}"
            ),
        ]
    )


def _status_records() -> tuple[str, ...]:
    result = _run_git(
        [
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]
    )

    return tuple(
        line
        for line in result.stdout.splitlines()
        if line.strip()
    )


def _ahead_behind(
    branch: str,
) -> tuple[int, int]:
    remote_ref = (
        f"refs/remotes/"
        f"{REMOTE_NAME}/{branch}"
    )

    if (
        not _head_exists()
        or not _ref_sha(
            remote_ref
        )
    ):
        return (
            0,
            0,
        )

    result = _run_git(
        [
            "rev-list",
            "--left-right",
            "--count",
            (
                "HEAD..."
                f"{REMOTE_NAME}/{branch}"
            ),
        ]
    )

    parts = (
        result.stdout.strip()
        .replace(
            "\t",
            " ",
        )
        .split()
    )

    if len(parts) != 2:
        raise GitSyncError(
            (
                "Não foi possível interpretar a divergência "
                "entre o repositório local e o GitHub."
            )
        )

    return (
        int(parts[0]),
        int(parts[1]),
    )


def repository_status(
    *,
    fetch: bool = True,
) -> RepositoryStatus:
    initialized_now = (
        ensure_repository_connection()
    )

    branch = (
        _remote_default_branch()
    )
    current_branch = (
        _current_branch()
    )

    if (
        current_branch
        and current_branch != branch
    ):
        raise GitSyncError(
            (
                f"O branch local atual é '{current_branch}', "
                f"mas o branch principal do GitHub é '{branch}'. "
                "Troque para o branch principal antes de atualizar."
            )
        )

    if fetch:
        fetch_remote(
            branch
        )

    ahead, behind = (
        _ahead_behind(
            branch
        )
    )
    changes = (
        _status_records()
    )

    return RepositoryStatus(
        branch=(
            current_branch
            or branch
        ),
        remote_branch=branch,
        head=_ref_sha(
            "HEAD"
        ),
        remote_head=_ref_sha(
            (
                f"refs/remotes/"
                f"{REMOTE_NAME}/{branch}"
            )
        ),
        ahead=ahead,
        behind=behind,
        dirty=bool(
            changes
        ),
        changes=changes,
        initialized_now=(
            initialized_now
        ),
    )


def save_update_checkpoint(
    status: RepositoryStatus,
) -> None:
    if not status.head:
        return

    git_dir_result = _run_git(
        [
            "rev-parse",
            "--git-dir",
        ]
    )

    git_dir = Path(
        git_dir_result.stdout.strip()
    )

    if not git_dir.is_absolute():
        git_dir = (
            BASE_DIR
            / git_dir
        )

    checkpoint = (
        git_dir
        / "financeiro-ofx-before-update.txt"
    )

    checkpoint.write_text(
        (
            f"timestamp={datetime.now().isoformat()}\n"
            f"commit={status.head}\n"
            f"branch={status.branch}\n"
            f"remote={REPOSITORY_URL}\n"
        ),
        encoding="utf-8",
    )


def download_fast_forward() -> RepositoryStatus:
    status = repository_status(
        fetch=True
    )

    if status.dirty:
        raise GitSyncError(
            (
                "Existem arquivos locais alterados. O download foi "
                "cancelado para não sobrescrever seu trabalho.\n\n"
                "Envie/commit as alterações primeiro ou revise-as "
                "manualmente."
            )
        )

    if status.diverged:
        raise GitSyncError(
            (
                "O histórico local e o GitHub divergiram. "
                "O sistema não fará merge/rebase automaticamente."
            )
        )

    if status.local_ahead_only:
        raise GitSyncError(
            (
                "O repositório local possui commits que ainda não "
                "estão no GitHub. Envie-os antes de baixar."
            )
        )

    if not status.update_available:
        return status

    save_update_checkpoint(
        status
    )

    _run_git(
        [
            "pull",
            "--ff-only",
            REMOTE_NAME,
            status.remote_branch,
        ]
    )

    return repository_status(
        fetch=False
    )


def _normalized_repo_path(
    relative_path: str,
) -> str:
    path = relative_path.replace(
        "\\",
        "/",
    )

    while path.startswith("./"):
        path = path[2:]

    return path


def is_essential_source_path(
    relative_path: str,
) -> bool:
    path = _normalized_repo_path(
        relative_path
    )

    if path in ESSENTIAL_TOP_LEVEL_FILES:
        return True

    return any(
        path == directory
        or path.startswith(
            directory + "/"
        )
        for directory
        in ESSENTIAL_TOP_LEVEL_DIRS
    )


def essential_stage_pathspecs() -> tuple[str, ...]:
    # Os diretórios principais sempre existem no pacote oficial.
    # Arquivos individuais são mantidos explicitamente para que uma
    # remoção futura de arquivo já rastreado também possa ser preparada.
    return (
        *ESSENTIAL_TOP_LEVEL_FILES,
        *ESSENTIAL_TOP_LEVEL_DIRS,
    )


def publishable_change_paths() -> tuple[str, ...]:
    return tuple(
        path
        for path in _porcelain_paths()
        if is_essential_source_path(
            path
        )
    )


def _porcelain_paths() -> tuple[str, ...]:
    result = _run_git(
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ]
    )

    raw = result.stdout
    records = raw.split(
        "\0"
    )
    paths: list[str] = []
    index = 0

    while index < len(records):
        record = records[index]

        if not record:
            index += 1
            continue

        status = record[:2]
        path = record[3:]

        if path:
            paths.append(
                path
            )

        if (
            "R" in status
            or "C" in status
        ):
            index += 1

            if index < len(records):
                old_path = (
                    records[index]
                )

                if old_path:
                    paths.append(
                        old_path
                    )

        index += 1

    return tuple(
        dict.fromkeys(
            paths
        )
    )


def _is_forbidden_path(
    relative_path: str,
) -> bool:
    path = relative_path.replace(
        "\\",
        "/",
    ).lstrip("./")

    if path in FORBIDDEN_EXACT_PATHS:
        return True

    name = Path(path).name

    if (
        name.startswith(".env.")
        and name != ".env.example"
    ):
        return True

    if any(
        path.startswith(prefix)
        for prefix in FORBIDDEN_PREFIXES
    ):
        return True

    if any(
        path.endswith(suffix)
        for suffix in FORBIDDEN_SUFFIXES
    ):
        return True

    return False


def _tracked_paths() -> tuple[str, ...]:
    result = _run_git(
        [
            "ls-files",
            "-z",
        ]
    )

    return tuple(
        item
        for item in result.stdout.split(
            "\0"
        )
        if item
    )


def _scan_file_for_secrets(
    relative_path: str,
) -> list[str]:
    path = (
        BASE_DIR
        / relative_path
    )

    if (
        not path.is_file()
        or path.stat().st_size
        > 5 * 1024 * 1024
    ):
        return []

    try:
        content = path.read_bytes()
    except OSError:
        return []

    # Evita varrer binários arbitrários.
    if (
        b"\x00" in content[:8192]
    ):
        return []

    findings = []

    for label, pattern in SECRET_PATTERNS:
        if pattern.search(
            content
        ):
            findings.append(
                label
            )

    return findings


def validate_safe_push() -> tuple[str, ...]:
    paths = tuple(
        dict.fromkeys(
            (
                *_tracked_paths(),
                *_porcelain_paths(),
            )
        )
    )

    forbidden = [
        path
        for path in paths
        if _is_forbidden_path(
            path
        )
    ]

    if forbidden:
        preview = "\n".join(
            f" - {item}"
            for item in forbidden[:20]
        )

        raise GitSyncError(
            (
                "Arquivos locais/sensíveis estão sendo rastreados "
                "ou preparados pelo Git:\n\n"
                f"{preview}\n\n"
                "O envio foi bloqueado."
            )
        )

    secret_findings = []

    for relative_path in paths:
        findings = (
            _scan_file_for_secrets(
                relative_path
            )
        )

        for finding in findings:
            secret_findings.append(
                (
                    relative_path,
                    finding,
                )
            )

    if secret_findings:
        preview = "\n".join(
            (
                f" - {path}: "
                f"{finding}"
            )
            for (
                path,
                finding,
            )
            in secret_findings[:20]
        )

        raise GitSyncError(
            (
                "Possíveis credenciais/segredos foram encontrados "
                "nos arquivos que seriam enviados:\n\n"
                f"{preview}\n\n"
                "O push foi bloqueado."
            )
        )

    return paths


def git_identity() -> tuple[str, str]:
    name_result = _run_git(
        [
            "config",
            "--get",
            "user.name",
        ],
        check=False,
    )
    email_result = _run_git(
        [
            "config",
            "--get",
            "user.email",
        ],
        check=False,
    )

    return (
        name_result.stdout.strip(),
        email_result.stdout.strip(),
    )


def configure_local_git_identity(
    *,
    name: str,
    email: str,
) -> None:
    name = " ".join(
        (name or "").split()
    )
    email = (
        email or ""
    ).strip()

    if not name:
        raise GitSyncError(
            "Informe o nome que será usado nos commits."
        )

    if (
        "@" not in email
        or " " in email
    ):
        raise GitSyncError(
            (
                "Informe um e-mail válido para os commits. "
                "Pode ser também o e-mail noreply fornecido "
                "pelo GitHub."
            )
        )

    _run_git(
        [
            "config",
            "user.name",
            name,
        ]
    )
    _run_git(
        [
            "config",
            "user.email",
            email,
        ]
    )


def _staged_paths() -> tuple[str, ...]:
    result = _run_git(
        [
            "diff",
            "--cached",
            "--name-only",
            "-z",
        ]
    )

    return tuple(
        path
        for path in result.stdout.split(
            "\0"
        )
        if path
    )


def validate_staged_manifest() -> tuple[str, ...]:
    staged = _staged_paths()

    invalid = [
        path
        for path in staged
        if not is_essential_source_path(
            path
        )
    ]

    if invalid:
        preview = "\n".join(
            f" - {item}"
            for item in invalid[:30]
        )

        raise GitSyncError(
            (
                "O Git preparou arquivos fora do manifest "
                "essencial do Financeiro OFX:\n\n"
                f"{preview}\n\n"
                "O commit foi bloqueado."
            )
        )

    return staged


def _staged_changes_exist() -> bool:
    result = _run_git(
        [
            "diff",
            "--cached",
            "--quiet",
        ],
        check=False,
    )

    return (
        result.returncode == 1
    )


def prepare_commit(
    commit_message: str,
) -> bool:
    message = " ".join(
        (
            commit_message
            or ""
        ).split()
    )

    if not message:
        raise GitSyncError(
            "Informe uma mensagem para o commit."
        )

    if len(message) > 240:
        raise GitSyncError(
            (
                "A mensagem do commit deve ter no máximo "
                "240 caracteres."
            )
        )

    validate_safe_push()

    _run_git(
        [
            "add",
            "-A",
            "--",
            *essential_stage_pathspecs(),
        ]
    )

    try:
        validate_staged_manifest()
        validate_safe_push()
    except Exception:
        _run_git(
            [
                "reset",
            ],
            check=False,
        )
        raise

    if not _staged_changes_exist():
        return False

    _run_git(
        [
            "commit",
            "-m",
            message,
        ],
        capture=False,
        interactive=True,
    )

    return True


def push_to_github(
    *,
    commit_message: str,
) -> RepositoryStatus:
    status = repository_status(
        fetch=True
    )

    if status.behind > 0:
        raise GitSyncError(
            (
                "O GitHub possui alterações que ainda não existem "
                "nesta pasta. Baixe/integre essas alterações antes "
                "de fazer push."
            )
        )

    validate_safe_push()

    prepare_commit(
        commit_message
    )

    # Evita sobrescrever um commit que tenha chegado ao GitHub
    # enquanto o commit local estava sendo criado.
    fetch_remote(
        status.remote_branch
    )

    final_status = (
        repository_status(
            fetch=False
        )
    )

    if final_status.behind > 0:
        raise GitSyncError(
            (
                "O GitHub recebeu novas alterações durante a "
                "preparação do commit. O commit local foi preservado, "
                "mas o push foi cancelado."
            )
        )

    if final_status.diverged:
        raise GitSyncError(
            (
                "O histórico divergiu. O push automático foi "
                "cancelado para evitar sobrescrever o GitHub."
            )
        )

    if (
        final_status.ahead == 0
        and final_status.remote_head
    ):
        return final_status

    _run_git(
        [
            "push",
            "-u",
            REMOTE_NAME,
            (
                f"HEAD:refs/heads/"
                f"{final_status.remote_branch}"
            ),
        ],
        capture=False,
        interactive=True,
    )

    return repository_status(
        fetch=True
    )


def format_status(
    status: RepositoryStatus,
) -> str:
    lines = [
        (
            "Repositório: "
            + REPOSITORY_URL
        ),
        (
            "Branch: "
            + status.remote_branch
        ),
        (
            "Commits locais não enviados: "
            + str(
                status.ahead
            )
        ),
        (
            "Commits disponíveis no GitHub: "
            + str(
                status.behind
            )
        ),
        (
            "Arquivos locais alterados: "
            + (
                "SIM"
                if status.dirty
                else "NÃO"
            )
        ),
    ]

    if status.initialized_now:
        lines.append(
            (
                "A pasta foi conectada ao GitHub sem "
                "substituir arquivos locais."
            )
        )

    if status.changes:
        lines.append("")
        lines.append(
            "Alterações locais:"
        )
        lines.extend(
            f"  {item}"
            for item in status.changes[:30]
        )

        if len(
            status.changes
        ) > 30:
            lines.append(
                (
                    "  ... "
                    f"{len(status.changes) - 30} "
                    "item(ns) adicional(is)"
                )
            )

    return "\n".join(
        lines
    )


def cli_check() -> int:
    status = repository_status(
        fetch=True
    )

    print(
        format_status(
            status
        )
    )

    if status.diverged:
        print(
            "\nATENÇÃO: histórico divergente."
        )
        return 2

    if status.update_available:
        print(
            "\nHá atualização disponível no GitHub."
        )
    elif status.local_ahead_only:
        print(
            "\nHá commits locais aguardando envio."
        )
    else:
        print(
            "\nO histórico local está atualizado."
        )

    return 0


def cli_pull() -> int:
    before = repository_status(
        fetch=True
    )

    print(
        format_status(
            before
        )
    )

    if not before.update_available:
        if before.behind == 0:
            print(
                "\nNenhuma atualização para baixar."
            )
            return 0

    answer = input(
        (
            "\nDigite SIM para baixar por fast-forward "
            "as alterações do GitHub: "
        )
    ).strip().upper()

    if answer != "SIM":
        print(
            "Operação cancelada."
        )
        return 1

    after = download_fast_forward()

    print(
        "\nDownload concluído."
    )
    print(
        format_status(
            after
        )
    )
    return 0


def cli_push() -> int:
    status = repository_status(
        fetch=True
    )

    print(
        format_status(
            status
        )
    )

    validate_safe_push()

    if (
        status.initialized_now
        and status.remote_head
        and status.dirty
    ):
        print(
            "\nATENÇÃO: esta pasta acabou de ser conectada a um "
            "repositório que já possui histórico. Os arquivos locais "
            "diferem do GitHub."
        )
        print(
            "O push criará um commit fazendo o repositório remoto "
            "receber essas diferenças locais."
        )

        first_answer = input(
            (
                "Digite PUBLICAR LOCAL para confirmar que "
                "é isso que deseja: "
            )
        ).strip().upper()

        if first_answer != "PUBLICAR LOCAL":
            print(
                "Operação cancelada."
            )
            return 1

    if (
        not status.dirty
        and status.ahead == 0
    ):
        print(
            "\nNão há alterações para enviar."
        )
        return 0

    if status.behind > 0:
        raise GitSyncError(
            (
                "Existem commits novos no GitHub. "
                "Baixe/integre-os antes do push."
            )
        )

    print(
        "\nSomente o código-fonte essencial será preparado para envio."
    )
    print(
        "Banco, .env, media, extratos, backups, logs, samples, "
        "VALIDACAO_ETAPA*.txt e demais arquivos locais ficam fora."
    )

    git_name, git_email = (
        git_identity()
    )

    if (
        not git_name
        or not git_email
    ):
        print(
            "\nA identidade Git ainda não está configurada "
            "neste repositório."
        )

        git_name = input(
            "Nome para os commits: "
        ).strip()
        git_email = input(
            (
                "E-mail para os commits "
                "(pode ser o noreply do GitHub): "
            )
        ).strip()

        configure_local_git_identity(
            name=git_name,
            email=git_email,
        )

    message = input(
        "\nMensagem do commit: "
    ).strip()

    if not message:
        message = (
            "Atualização Financeiro OFX "
            + datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
        )

    answer = input(
        (
            "\nDigite SIM para criar o commit e enviar "
            "ao GitHub: "
        )
    ).strip().upper()

    if answer != "SIM":
        print(
            "Operação cancelada."
        )
        return 1

    final_status = (
        push_to_github(
            commit_message=message
        )
    )

    print(
        "\nGitHub atualizado com sucesso."
    )
    print(
        format_status(
            final_status
        )
    )
    return 0


def main() -> int:
    global CLI_INTERACTIVE
    CLI_INTERACTIVE = True

    command = (
        sys.argv[1].lower()
        if len(sys.argv) > 1
        else "check"
    )

    try:
        if command == "check":
            return cli_check()

        if command == "pull":
            return cli_pull()

        if command == "push":
            return cli_push()

        print(
            (
                "Uso: python github_sync.py "
                "[check|pull|push]"
            )
        )
        return 2
    except GitSyncError as exc:
        print(
            "\nERRO:"
        )
        print(
            str(exc)
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
