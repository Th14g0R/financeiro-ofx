from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import django
import re

from django.conf import settings
from django.core.checks import Error
from django.core.checks import run_checks
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    code: str
    message: str
    location: str = ""


class Command(BaseCommand):
    help = (
        "Executa auditoria de segurança local: configurações Django, "
        "templates, padrões de injeção/XSS, segredos e superfície web."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-high",
            action="store_true",
            help="Retorna erro se houver achado de severidade ALTA.",
        )

    def handle(self, *args, **options):
        findings = []
        findings.extend(self._settings_findings())
        findings.extend(self._django_check_findings())
        findings.extend(self._source_findings())
        findings.extend(self._template_findings())

        order = {
            "HIGH": 0,
            "MEDIUM": 1,
            "LOW": 2,
            "INFO": 3,
        }
        findings.sort(
            key=lambda item: (
                order.get(item.severity, 9),
                item.code,
                item.location,
            )
        )

        self.stdout.write("")
        self.stdout.write("=== Financeiro OFX — Auditoria de segurança ===")

        if findings:
            for item in findings:
                location = f" [{item.location}]" if item.location else ""
                self.stdout.write(
                    f"{item.severity:<6} {item.code}{location}: {item.message}"
                )
        else:
            self.stdout.write("Nenhum achado foi identificado pelos controles automatizados.")

        totals = {
            level: sum(1 for item in findings if item.severity == level)
            for level in ("HIGH", "MEDIUM", "LOW", "INFO")
        }
        self.stdout.write("")
        self.stdout.write(
            "Resumo: "
            + ", ".join(
                f"{level}={totals[level]}"
                for level in ("HIGH", "MEDIUM", "LOW", "INFO")
            )
        )
        self.stdout.write(
            "Escopo: análise automatizada local. Não substitui pentest externo "
            "autorizado, revisão manual ou scanner de dependências com base CVE."
        )

        if options["fail_on_high"] and totals["HIGH"]:
            high_findings = [
                item
                for item in findings
                if item.severity == "HIGH"
            ]

            summary = "; ".join(
                (
                    f"{item.code}"
                    + (
                        f" [{item.location}]"
                        if item.location
                        else ""
                    )
                    + f": {item.message}"
                )
                for item in high_findings
            )

            raise CommandError(
                (
                    f"Auditoria encontrou {totals['HIGH']} "
                    "achado(s) de severidade ALTA. "
                    f"{summary}"
                )
            )

    def _settings_findings(self):
        result = []
        required_middleware = (
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
            "core.middleware.AuditTrailMiddleware",
            "core.middleware.SensitiveSurfaceMiddleware",
            "core.middleware.SecurityHeadersMiddleware",
        )
        middleware = tuple(settings.MIDDLEWARE)

        for item in required_middleware:
            if item not in middleware:
                result.append(
                    Finding("HIGH", "CFG001", f"Middleware obrigatório ausente: {item}")
                )

        if settings.DEBUG:
            result.append(Finding("HIGH", "CFG002", "DEBUG está ativo."))

        if django.VERSION < (5, 2, 17):
            result.append(
                Finding(
                    "HIGH",
                    "CFG009",
                    (
                        "Django anterior a 5.2.17 detectado. "
                        "Atualize para uma versão 5.2 com os patches "
                        "de segurança mais recentes do projeto."
                    ),
                )
            )

        if "*" in settings.ALLOWED_HOSTS:
            result.append(Finding("HIGH", "CFG003", "ALLOWED_HOSTS contém wildcard '*'."))

        if (
            len(settings.SECRET_KEY) < 50
            or len(set(settings.SECRET_KEY)) < 5
            or settings.SECRET_KEY.startswith(
                "django-insecure-"
            )
        ):
            result.append(
                Finding(
                    "HIGH",
                    "CFG004",
                    (
                        "DJANGO_SECRET_KEY é curta, possui baixa diversidade "
                        "ou usa o prefixo django-insecure-."
                    ),
                )
            )

        if not settings.SESSION_COOKIE_HTTPONLY:
            result.append(
                Finding("HIGH", "CFG005", "SESSION_COOKIE_HTTPONLY deve permanecer True.")
            )

        if settings.X_FRAME_OPTIONS != "DENY":
            result.append(
                Finding("HIGH", "CFG006", "X_FRAME_OPTIONS deve permanecer DENY.")
            )

        if settings.SESSION_COOKIE_SAMESITE not in {"Lax", "Strict"}:
            result.append(
                Finding("MEDIUM", "CFG007", "SESSION_COOKIE_SAMESITE está permissivo.")
            )

        if not settings.SECURE_MODE:
            result.append(
                Finding(
                    "MEDIUM",
                    "CFG008",
                    "HTTPS/SECURE_MODE não está ativo. Em LAN, use somente rede privada e Firewall LocalSubnet.",
                )
            )

        return result

    def _django_check_findings(self):
        result = []
        for issue in run_checks(include_deployment_checks=True):
            if isinstance(issue, Error):
                severity = "HIGH"
            else:
                # Alguns warnings de deploy são esperados em localhost/LAN sem HTTPS.
                severity = "MEDIUM"
            result.append(
                Finding(
                    severity,
                    f"DJANGO-{issue.id}",
                    str(issue.msg),
                )
            )
        return result

    def _source_findings(self):
        result = []
        base_dir = Path(settings.BASE_DIR)
        skip_parts = {
            ".git",
            ".venv",
            "venv",
            "media",
            "backups",
            "logs",
            "run",
            "staticfiles",
        }

        high_patterns = (
            ("SRC001", re.compile(r"\beval\s*\("), "Uso de eval()."),
            ("SRC002", re.compile(r"\bexec\s*\("), "Uso de exec()."),
            ("SRC003", re.compile(r"mark_safe\s*\("), "Uso de mark_safe() exige revisão manual."),
            ("SRC004", re.compile(r"cursor\.execute\s*\(\s*f[\"']"), "SQL montado por f-string."),
            ("SRC005", re.compile(r"subprocess\.(?:run|Popen|call)\([^\n]*shell\s*=\s*True"), "subprocess com shell=True."),
        )
        secret_patterns = (
            re.compile(r"APP_USR-[A-Za-z0-9_-]{20,}"),
            re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
            re.compile(r"ghp_[A-Za-z0-9]{20,}"),
            re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        )

        for path in base_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(base_dir)
            if relative.as_posix() == "core/management/commands/security_audit.py":
                continue
            if any(part in skip_parts for part in relative.parts):
                continue
            if path.name == ".env":
                continue
            if path.suffix.lower() not in {".py", ".html", ".js", ".ps1", ".bat", ".md", ".txt", ".example"} and path.name not in {".gitignore"}:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if path.suffix.lower() == ".py":
                for code, pattern, message in high_patterns:
                    if pattern.search(content):
                        result.append(
                            Finding("HIGH", code, message, str(relative))
                        )

            for pattern in secret_patterns:
                if pattern.search(content):
                    result.append(
                        Finding("HIGH", "SRC006", "Possível segredo/token versionado.", str(relative))
                    )
                    break

        return result

    def _template_findings(self):
        result = []
        template_dir = Path(settings.BASE_DIR) / "templates"
        form_pattern = re.compile(
            r"<form\b(?=[^>]*\bmethod\s*=\s*[\"']post[\"'])[^>]*>(.*?)</form>",
            flags=re.I | re.S,
        )

        for path in template_dir.rglob("*.html"):
            content = path.read_text(encoding="utf-8", errors="replace")
            relative = path.relative_to(settings.BASE_DIR)

            if "|safe" in content or "{% autoescape off %}" in content:
                result.append(
                    Finding("HIGH", "TPL001", "Escape automático desativado/|safe encontrado.", str(relative))
                )

            for match in form_pattern.finditer(content):
                if "{% csrf_token %}" not in match.group(1):
                    result.append(
                        Finding("HIGH", "TPL002", "Formulário POST interno sem csrf_token.", str(relative))
                    )

            for script in re.finditer(r"<script\b([^>]*)\bsrc=[\"']https://([^\"']+)[\"']([^>]*)>", content, flags=re.I):
                attrs = script.group(1) + script.group(3)
                if "integrity=" not in attrs:
                    result.append(
                        Finding(
                            "MEDIUM",
                            "TPL003",
                            "Script JavaScript externo sem Subresource Integrity; prefira arquivo local ou SRI.",
                            str(relative),
                        )
                    )

        return result
