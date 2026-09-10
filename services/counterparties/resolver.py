from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from django.db import transaction as db_transaction
from django.db.models import Count
from django.db.models import Q

from finance.models import Counterparty
from finance.models import CounterpartyAlias
from finance.models import Transaction


_TRANSFER_TYPES = {
    Transaction.TransactionType.PIX,
    Transaction.TransactionType.TED,
    Transaction.TransactionType.DOC,
    Transaction.TransactionType.TRANSFER,
}

_GENERIC_OPERATION_NAMES = {
    "PIX",
    "TRANSFERENCIA",
    "PAGAMENTO",
    "RECEBIDA",
    "RECEBIDO",
    "ENVIADA",
    "ENVIADO",
    "TRANSFERENCIA RECEBIDA",
    "TRANSFERENCIA ENVIADA",
}

_DIRECTION_TOKENS = {
    "ENVIADO",
    "ENVIADA",
    "RECEBIDO",
    "RECEBIDA",
}

_DATE_PREFIX_RE = re.compile(
    r"^\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s+|$)",
    re.IGNORECASE,
)
_TIME_PREFIX_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s+|$)",
    re.IGNORECASE,
)
_INSTALLMENT_SUFFIX_RE = re.compile(
    r"(?:\s+|^)\d{1,3}/\d{1,3}\s*$",
    re.IGNORECASE,
)
_BANK_IDENTIFIER_PREFIX_RE = re.compile(
    r"^\s*(?P<identifier>(?:\d{2,3}(?:\.\d{3}){1,2})|(?:\d{8,14}))\s+(?P<name>.+)$",
    re.IGNORECASE,
)
_MASKED_IDENTIFIER_RE = re.compile(
    r"(?:[•*]+[^A-Za-z0-9]{0,3}\d|\d[^A-Za-z0-9]{0,3}[•*]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SanitizedName:
    name: str
    normalized_name: str
    bank_identifier: str
    changed: bool


@dataclass(frozen=True, slots=True)
class CounterpartyCandidate:
    name: str
    normalized_name: str
    masked_identifier: str
    bank_identifier: str
    source: str


def normalize_identity_text(value: str) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value or "",
    )
    ascii_text = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    ascii_text = re.sub(
        r"[^A-Za-z0-9]+",
        " ",
        ascii_text,
    )
    return " ".join(
        ascii_text.upper().split()
    )


def _digits(value: str) -> str:
    return "".join(
        character
        for character in (value or "")
        if character.isdigit()
    )


def sanitize_counterparty_name(
    value: str,
) -> SanitizedName:
    """
    Remove ruídos de apresentação que alguns bancos incorporam antes/depois
    do nome: data, horário, raiz/identificador numérico e parcela 001/011.

    Não altera a descrição bancária original; produz apenas a identidade que
    será usada para associação de contraparte.
    """
    original = " ".join(
        (value or "").split()
    )
    cleaned = original

    if not cleaned:
        return SanitizedName(
            name="",
            normalized_name="",
            bank_identifier="",
            changed=False,
        )

    # Alguns históricos chegam como "Enviado 29/08 08:37 Nome".
    words = cleaned.split()
    while words and normalize_identity_text(words[0]) in _DIRECTION_TOKENS:
        words.pop(0)
    cleaned = " ".join(words)

    # Bancos podem repetir data e hora na própria descrição, mesmo quando o
    # lançamento já possui posted_at separado.
    for _ in range(3):
        previous = cleaned
        cleaned = _DATE_PREFIX_RE.sub(
            "",
            cleaned,
            count=1,
        )
        cleaned = _TIME_PREFIX_RE.sub(
            "",
            cleaned,
            count=1,
        )
        cleaned = " ".join(cleaned.split())
        if cleaned == previous:
            break

    # Ex.: "15/01 FRANCISCA ... 001/011".
    cleaned = _INSTALLMENT_SUFFIX_RE.sub(
        "",
        cleaned,
        count=1,
    ).strip()

    bank_identifier = ""
    identifier_match = _BANK_IDENTIFIER_PREFIX_RE.match(
        cleaned
    )

    if identifier_match:
        identifier = _digits(
            identifier_match.group(
                "identifier"
            )
        )
        remainder = " ".join(
            identifier_match.group(
                "name"
            ).split()
        )

        # 8 dígitos aparecem com frequência como raiz/identificador bancário
        # (ex.: 46.685.824). 11/14 podem ser CPF/CNPJ completo. Mantemos tudo
        # como identificador bancário até termos certeza do documento completo.
        if (
            8 <= len(identifier) <= 14
            and re.search(
                r"[A-Za-zÀ-ÿ]",
                remainder,
            )
        ):
            bank_identifier = identifier
            cleaned = remainder

    cleaned = cleaned.strip(" -;,.|")
    cleaned = " ".join(cleaned.split())

    return SanitizedName(
        name=cleaned,
        normalized_name=normalize_identity_text(
            cleaned
        ),
        bank_identifier=bank_identifier,
        changed=(cleaned != original),
    )


def infer_counterparty_kind(
    name: str,
) -> str:
    normalized = normalize_identity_text(
        name
    )

    company_markers = {
        " LTDA",
        " LIMITADA",
        " EIRELI",
        " S A",
        " SOCIEDADE ANONIMA",
        " INSTITUICAO DE PAGAMENTO",
        " SERVICOS ",
        " COMERCIO ",
    }

    if any(
        marker in f" {normalized} "
        for marker in company_markers
    ):
        return Counterparty.Kind.COMPANY

    return Counterparty.Kind.PERSON


def _looks_like_transfer_description(
    value: str,
) -> bool:
    normalized = normalize_identity_text(
        value
    )

    return (
        normalized.startswith("PIX ")
        or normalized == "PIX"
        or normalized.startswith(
            "TRANSFERENCIA "
        )
    )


def _candidate_from_compact_transfer_separator(value: str) -> str:
    """Extract names from compact bank descriptions such as
    ``Transferência Recebida|José da Silva`` or ``Pix enviado: Maria``.

    Several API connectors use ``|``/``:`` instead of the spaced hyphen used
    by OFX/PDF descriptions. Keeping this extraction provider-agnostic allows
    the normal alias/similarity engine to reuse the same Person records.
    """
    match = re.match(
        r"^\s*(?:PIX\s+)?(?:TRANSFER[EÊ]NCIA\s+)?(?:RECEBID[AO]|ENVIAD[AO]|RECEBIMENTO|ENVIO)\s*[|:]\s*(?P<name>.+?)\s*$",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return " ".join(match.group("name").split()).strip()

    match = re.match(
        r"^\s*TRANSFER[EÊ]NCIA\s+(?:RECEBID[AO]|ENVIAD[AO])\s*[|:]\s*(?P<name>.+?)\s*$",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        return " ".join(match.group("name").split()).strip()
    return ""


def _candidate_segment_from_description(
    value: str,
) -> str:
    parts = [
        part.strip()
        for part in re.split(
            r"\s+-\s+",
            value,
        )
        if part.strip()
    ]

    if not parts:
        return ""

    normalized_parts = [
        normalize_identity_text(
            part
        )
        for part in parts
    ]

    # Banco do Brasil, por exemplo:
    #   Pix - Enviado - 29/08 08:37 Livia Alves Mendes
    if (
        normalized_parts[0] == "PIX"
        and len(parts) >= 3
        and normalized_parts[1]
        in _DIRECTION_TOKENS
    ):
        return parts[2]

    # Formato mais tradicional:
    #   Transferência recebida pelo Pix - NOME - CPF mascarado - BANCO
    if normalized_parts[0].startswith(
        "TRANSFERENCIA"
    ):
        if len(parts) >= 2:
            return parts[1]

    # Variações compactas de PIX.
    if normalized_parts[0] == "PIX":
        for index in range(
            1,
            len(parts),
        ):
            normalized = normalized_parts[
                index
            ]

            if normalized in _DIRECTION_TOKENS:
                continue

            return parts[index]

    return ""


def _candidate_from_trailing_transfer_label(
    value: str,
) -> str:
    """
    Alguns extratos (ex.: AstroPay) exibem o nome antes do rótulo:
        NOME DA PESSOA Transferência Pix

    Nesse caso, a contraparte é a parte anterior ao rótulo da operação.
    """
    match = re.match(
        r"^(?P<name>.+?)\s+Transfer[eê]ncia\s+Pix\s*$",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return " ".join(
        match.group("name").split()
    ).strip()


def _plausible_candidate_name(
    name: str,
) -> bool:
    normalized = normalize_identity_text(
        name
    )

    if (
        not normalized
        or len(normalized) < 3
        or normalized in _GENERIC_OPERATION_NAMES
    ):
        return False

    return bool(
        re.search(
            r"[A-Za-zÀ-ÿ]{2}",
            name,
        )
    )


def extract_counterparty_candidate(
    description: str,
    *,
    transaction_type: str | None = None,
) -> CounterpartyCandidate | None:
    value = " ".join(
        (description or "").split()
    )

    if not value:
        return None

    transfer_context = (
        transaction_type in _TRANSFER_TYPES
        if transaction_type
        else _looks_like_transfer_description(
            value
        )
    )

    segment = ""

    if _looks_like_transfer_description(
        value
    ):
        segment = _candidate_from_compact_transfer_separator(value)
        if not segment:
            segment = (
                _candidate_segment_from_description(
                    value
                )
            )
    elif transfer_context:
        segment = (
            _candidate_from_trailing_transfer_label(
                value
            )
        )

        if not segment:
            # Alguns bancos já removem o rótulo PIX/Transferência e deixam apenas
            # "15/01 FRANCISCA ... 001/011" ou um identificador + nome.
            segment = value
    elif (
        _DATE_PREFIX_RE.match(value)
        or _BANK_IDENTIFIER_PREFIX_RE.match(
            value
        )
    ):
        # Mantido para a rotina de saneamento/rebuild de cadastros legados.
        segment = value
    else:
        return None

    sanitized = sanitize_counterparty_name(
        segment
    )

    if not _plausible_candidate_name(
        sanitized.name
    ):
        return None

    masked_identifier = ""

    # O identificador mascarado normalmente fica em outra parte da descrição.
    parts = [
        part.strip()
        for part in re.split(
            r"\s+-\s+",
            value,
        )
        if part.strip()
    ]

    for part in parts:
        if _MASKED_IDENTIFIER_RE.search(
            part
        ):
            masked_identifier = (
                part.strip()
            )
            break

    return CounterpartyCandidate(
        name=sanitized.name,
        normalized_name=(
            sanitized.normalized_name
        ),
        masked_identifier=(
            masked_identifier
        ),
        bank_identifier=(
            sanitized.bank_identifier
        ),
        source=value,
    )


def _counterparty_identifiers(
    counterparty: Counterparty,
) -> set[str]:
    return set(
        counterparty.aliases.filter(
            alias_type__in=[
                CounterpartyAlias.AliasType.PIX,
                CounterpartyAlias.AliasType.BANK_ID,
                CounterpartyAlias.AliasType.TAX_ID,
            ]
        ).values_list(
            "normalized_alias",
            flat=True,
        )
    )


def _candidate_identifiers(
    candidate: CounterpartyCandidate,
) -> set[str]:
    result = set()

    if candidate.masked_identifier:
        normalized = normalize_identity_text(
            candidate.masked_identifier
        )
        if normalized:
            result.add(normalized)

    if candidate.bank_identifier:
        normalized = normalize_identity_text(
            candidate.bank_identifier
        )
        if normalized:
            result.add(normalized)

    return result


def _identifiers_conflict(
    counterparty: Counterparty,
    candidate: CounterpartyCandidate,
) -> bool:
    existing = _counterparty_identifiers(
        counterparty
    )
    incoming = _candidate_identifiers(
        candidate
    )

    return bool(
        existing
        and incoming
        and existing.isdisjoint(
            incoming
        )
    )


def truncated_name_equivalent(
    left: str,
    right: str,
) -> bool:
    """
    Associação conservadora para nomes truncados pelo banco.

    Ex.:
      FRANCISCA DEIJANE CARVAL  <-> FRANCISCA DEIJANE CARVALH
      ROSENILSON EDUAR          <-> ROSENILSON EDUARDO DE SOUSA
      ANA LUCIA ANASTACIO DA S <-> ANA LUCIA ANASTACIO DA SILVA

    Não considera apenas similaridade percentual: exige prefixo token a token.
    """
    left_norm = normalize_identity_text(
        left
    )
    right_norm = normalize_identity_text(
        right
    )

    if (
        not left_norm
        or not right_norm
        or left_norm == right_norm
    ):
        return False

    left_tokens = left_norm.split()
    right_tokens = right_norm.split()

    if len(left_norm) <= len(right_norm):
        short_tokens = left_tokens
        long_tokens = right_tokens
        short_norm = left_norm
    else:
        short_tokens = right_tokens
        long_tokens = left_tokens
        short_norm = right_norm

    if (
        len(short_norm) < 12
        or len(short_tokens) < 2
        or len(short_tokens) > len(long_tokens)
    ):
        return False

    # Todos os tokens anteriores ao último devem coincidir exatamente.
    for index in range(
        len(short_tokens) - 1
    ):
        if (
            short_tokens[index]
            != long_tokens[index]
        ):
            return False

    short_last = short_tokens[-1]
    long_last = long_tokens[
        len(short_tokens) - 1
    ]

    if not long_last.startswith(
        short_last
    ):
        return False

    if short_last == long_last:
        # Se o último token já é completo, não juntamos nomes apenas porque
        # um possui sobrenomes adicionais (JOAO SILVA != JOAO SILVA JUNIOR).
        return False

    if len(short_last) >= 4:
        return True

    # Bancos às vezes cortam no primeiro caractere do último sobrenome.
    return (
        len(short_tokens) >= 4
        and len(short_norm) >= 20
    )


def _find_truncated_match(
    candidate: CounterpartyCandidate,
) -> Counterparty | None:
    possible = []

    queryset = (
        Counterparty.objects.filter(
            is_active=True
        )
        .prefetch_related(
            "aliases"
        )
        .order_by("id")
    )

    for counterparty in queryset:
        if _identifiers_conflict(
            counterparty,
            candidate,
        ):
            continue

        names = {
            counterparty.display_name,
        }
        names.update(
            alias.alias
            for alias in counterparty.aliases.all()
            if alias.alias_type
            == CounterpartyAlias.AliasType.NAME
        )

        if any(
            truncated_name_equivalent(
                candidate.name,
                name,
            )
            for name in names
        ):
            possible.append(
                counterparty
            )

    # Ambiguidade nunca é resolvida silenciosamente.
    if len(possible) == 1:
        return possible[0]

    return None


def _richer_display_name(
    current: str,
    candidate: str,
) -> str:
    current_clean = (
        sanitize_counterparty_name(
            current
        ).name
    )
    candidate_clean = (
        sanitize_counterparty_name(
            candidate
        ).name
    )

    if not current_clean:
        return candidate_clean

    if not candidate_clean:
        return current_clean

    if truncated_name_equivalent(
        current_clean,
        candidate_clean,
    ):
        if (
            len(
                normalize_identity_text(
                    candidate_clean
                )
            )
            > len(
                normalize_identity_text(
                    current_clean
                )
            )
        ):
            return candidate_clean

    return current_clean


def _find_counterparty_for_candidate(
    candidate: CounterpartyCandidate,
) -> Counterparty | None:
    normalized_identifiers = []

    for raw_identifier, alias_type in [
        (
            candidate.masked_identifier,
            CounterpartyAlias.AliasType.PIX,
        ),
        (
            candidate.bank_identifier,
            CounterpartyAlias.AliasType.BANK_ID,
        ),
    ]:
        normalized = normalize_identity_text(
            raw_identifier
        )

        if normalized:
            normalized_identifiers.append(
                (
                    normalized,
                    alias_type,
                )
            )

    for normalized, alias_type in normalized_identifiers:
        matches = list(
            CounterpartyAlias.objects.select_related(
                "counterparty"
            )
            .filter(
                normalized_alias=normalized,
                alias_type=alias_type,
                counterparty__is_active=True,
            )
            .order_by("id")[:2]
        )

        if len(matches) == 1:
            return matches[0].counterparty

    name_alias_matches = list(
        CounterpartyAlias.objects.select_related(
            "counterparty"
        )
        .filter(
            normalized_alias=(
                candidate.normalized_name
            ),
            alias_type=(
                CounterpartyAlias.AliasType.NAME
            ),
            counterparty__is_active=True,
        )
        .order_by("id")[:2]
    )

    if len(name_alias_matches) == 1:
        counterparty = (
            name_alias_matches[0].counterparty
        )

        if not _identifiers_conflict(
            counterparty,
            candidate,
        ):
            return counterparty

    direct_matches = list(
        Counterparty.objects.filter(
            normalized_name=(
                candidate.normalized_name
            ),
            is_active=True,
        ).order_by("id")[:2]
    )

    if len(direct_matches) == 1:
        counterparty = direct_matches[0]

        if not _identifiers_conflict(
            counterparty,
            candidate,
        ):
            return counterparty

    return _find_truncated_match(
        candidate
    )


def _ensure_alias(
    *,
    counterparty: Counterparty,
    alias: str,
    alias_type: str,
):
    normalized = normalize_identity_text(
        alias
    )

    if not normalized:
        return

    CounterpartyAlias.objects.get_or_create(
        counterparty=counterparty,
        normalized_alias=normalized,
        alias_type=alias_type,
        defaults={
            "alias": alias,
        },
    )


def _apply_candidate_metadata(
    counterparty: Counterparty,
    candidate: CounterpartyCandidate,
):
    richer_name = _richer_display_name(
        counterparty.display_name,
        candidate.name,
    )
    inferred_kind = infer_counterparty_kind(
        richer_name
    )

    changed_fields = []

    if richer_name != counterparty.display_name:
        counterparty.display_name = richer_name
        counterparty.normalized_name = (
            normalize_identity_text(
                richer_name
            )
        )
        changed_fields.extend(
            [
                "display_name",
                "normalized_name",
            ]
        )

    if counterparty.kind != inferred_kind:
        counterparty.kind = inferred_kind
        changed_fields.append(
            "kind"
        )

    if changed_fields:
        changed_fields.append(
            "updated_at"
        )
        counterparty.save(
            update_fields=changed_fields
        )

    _ensure_alias(
        counterparty=counterparty,
        alias=candidate.name,
        alias_type=(
            CounterpartyAlias.AliasType.NAME
        ),
    )

    if candidate.source:
        _ensure_alias(
            counterparty=counterparty,
            alias=candidate.source,
            alias_type=(
                CounterpartyAlias.AliasType.BANK_TEXT
            ),
        )

    if candidate.masked_identifier:
        _ensure_alias(
            counterparty=counterparty,
            alias=(
                candidate.masked_identifier
            ),
            alias_type=(
                CounterpartyAlias.AliasType.PIX
            ),
        )

    if candidate.bank_identifier:
        _ensure_alias(
            counterparty=counterparty,
            alias=(
                candidate.bank_identifier
            ),
            alias_type=(
                CounterpartyAlias.AliasType.BANK_ID
            ),
        )


@db_transaction.atomic
def resolve_transaction_counterparty(
    transaction: Transaction,
    *,
    force: bool = False,
) -> Counterparty | None:
    # Movimentações manuais podem ter sido associadas explicitamente pelo
    # usuário. Não sobrescrevemos esse vínculo a menos que force=True.
    if (
        transaction.source_type
        == Transaction.SourceType.MANUAL
        and transaction.counterparty_id
        and not force
    ):
        return transaction.counterparty

    candidate = extract_counterparty_candidate(
        transaction.raw_description,
        transaction_type=(
            transaction.transaction_type
        ),
    )

    if candidate is None:
        if force and transaction.counterparty_id:
            transaction.counterparty = None
            transaction.counterparty_raw_name = ""
            transaction.save(
                update_fields=[
                    "counterparty",
                    "counterparty_raw_name",
                    "updated_at",
                ]
            )
        return None

    counterparty = (
        _find_counterparty_for_candidate(
            candidate
        )
    )

    if counterparty is None:
        counterparty = Counterparty(
            display_name=candidate.name,
            normalized_name=(
                candidate.normalized_name
            ),
            kind=infer_counterparty_kind(
                candidate.name
            ),
            is_active=True,
        )
        counterparty.full_clean()
        counterparty.save()

    _apply_candidate_metadata(
        counterparty,
        candidate,
    )

    transaction.counterparty = counterparty
    transaction.counterparty_raw_name = (
        candidate.name
    )
    transaction.save(
        update_fields=[
            "counterparty",
            "counterparty_raw_name",
            "updated_at",
        ]
    )

    return counterparty


@db_transaction.atomic
def resolve_transaction_counterparty_from_hint(
    transaction: Transaction,
    *,
    name: str,
    tax_id: str = "",
    bank_identifier: str = "",
    source: str = "Pluggy paymentData",
) -> Counterparty | None:
    """Resolve contraparte a partir de dados estruturados da instituição.

    É usado quando a API fornece payer/receiver separadamente. A descrição
    original da movimentação permanece intocada.
    """
    sanitized = sanitize_counterparty_name(name)
    if not sanitized.name:
        return resolve_transaction_counterparty(transaction)

    candidate = CounterpartyCandidate(
        name=sanitized.name,
        normalized_name=sanitized.normalized_name,
        masked_identifier="",
        bank_identifier=(bank_identifier or sanitized.bank_identifier or "").strip(),
        source=source,
    )
    digits = _digits(tax_id)

    # CPF/CNPJ completo é um identificador mais forte que o nome. Isso evita
    # criar duas Pessoas quando o banco usa grafias diferentes para a mesma
    # contraparte em OFX/PDF e paymentData da Pluggy.
    counterparty = None
    if len(digits) in {11, 14}:
        counterparty = Counterparty.objects.filter(tax_id=digits).first()
    if counterparty is None:
        counterparty = _find_counterparty_for_candidate(candidate)
    if counterparty is None:
        counterparty = Counterparty(
            display_name=candidate.name,
            normalized_name=candidate.normalized_name,
            kind=infer_counterparty_kind(candidate.name),
            is_active=True,
        )
        if len(digits) in {11, 14} and not Counterparty.objects.filter(tax_id=digits).exists():
            counterparty.tax_id = digits
        counterparty.full_clean()
        counterparty.save()

    _apply_candidate_metadata(counterparty, candidate)
    if len(digits) in {11, 14}:
        if not counterparty.tax_id:
            conflict = Counterparty.objects.filter(tax_id=digits).exclude(pk=counterparty.pk).exists()
            if not conflict:
                counterparty.tax_id = digits
                counterparty.save(update_fields=["tax_id", "updated_at"])
        _ensure_alias(
            counterparty=counterparty,
            alias=digits,
            alias_type=CounterpartyAlias.AliasType.TAX_ID,
        )

    transaction.counterparty = counterparty
    transaction.counterparty_raw_name = candidate.name
    transaction.save(update_fields=["counterparty", "counterparty_raw_name", "updated_at"])
    return counterparty


def _copy_aliases(
    *,
    source: Counterparty,
    target: Counterparty,
):
    for alias in source.aliases.all():
        _ensure_alias(
            counterparty=target,
            alias=alias.alias,
            alias_type=alias.alias_type,
        )


def _merge_counterparty(
    *,
    source: Counterparty,
    target: Counterparty,
) -> int:
    if source.pk == target.pk:
        return 0

    moved = Transaction.objects.filter(
        counterparty=source
    ).update(
        counterparty=target
    )

    _copy_aliases(
        source=source,
        target=target,
    )

    target_name = _richer_display_name(
        target.display_name,
        source.display_name,
    )

    if target_name != target.display_name:
        target.display_name = target_name
        target.normalized_name = (
            normalize_identity_text(
                target_name
            )
        )
        target.kind = infer_counterparty_kind(
            target_name
        )
        target.save(
            update_fields=[
                "display_name",
                "normalized_name",
                "kind",
                "updated_at",
            ]
        )

    source.is_active = False
    source.save(
        update_fields=[
            "is_active",
            "updated_at",
        ]
    )

    return moved


@db_transaction.atomic
def normalize_existing_counterparties() -> dict[str, int]:
    """
    Saneia cadastros legados antes de reprocessar as movimentações.

    Remove data/hora, identificadores bancários e parcelas do display_name,
    cria aliases de identificador e mescla duplicidades óbvias. Depois o
    rebuild das transações completa a associação.
    """
    counters = {
        "renamed": 0,
        "merged": 0,
        "deactivated": 0,
    }

    # 1) Limpa cada display_name individualmente.
    for counterparty in Counterparty.objects.filter(
        is_active=True
    ).order_by("id"):
        sanitized = sanitize_counterparty_name(
            counterparty.display_name
        )

        if not sanitized.name:
            continue

        changed = False

        if (
            sanitized.name
            != counterparty.display_name
        ):
            counterparty.display_name = (
                sanitized.name
            )
            counterparty.normalized_name = (
                sanitized.normalized_name
            )
            changed = True

        inferred_kind = infer_counterparty_kind(
            sanitized.name
        )

        if counterparty.kind != inferred_kind:
            counterparty.kind = inferred_kind
            changed = True

        if changed:
            counterparty.save(
                update_fields=[
                    "display_name",
                    "normalized_name",
                    "kind",
                    "updated_at",
                ]
            )
            counters["renamed"] += 1

        _ensure_alias(
            counterparty=counterparty,
            alias=sanitized.name,
            alias_type=(
                CounterpartyAlias.AliasType.NAME
            ),
        )

        if sanitized.bank_identifier:
            _ensure_alias(
                counterparty=counterparty,
                alias=(
                    sanitized.bank_identifier
                ),
                alias_type=(
                    CounterpartyAlias.AliasType.BANK_ID
                ),
            )

    # 2) Mescla identificadores bancários exatos. Preferimos o nome mais rico.
    bank_id_aliases = (
        CounterpartyAlias.objects.filter(
            alias_type=(
                CounterpartyAlias.AliasType.BANK_ID
            ),
            counterparty__is_active=True,
        )
        .select_related("counterparty")
        .order_by(
            "normalized_alias",
            "counterparty_id",
        )
    )

    groups: dict[str, list[Counterparty]] = {}

    for alias in bank_id_aliases:
        groups.setdefault(
            alias.normalized_alias,
            [],
        ).append(
            alias.counterparty
        )

    for _identifier, group in groups.items():
        unique = {
            item.pk: item
            for item in group
            if item.is_active
        }

        if len(unique) <= 1:
            continue

        candidates = list(
            unique.values()
        )
        candidates.sort(
            key=lambda item: (
                len(
                    normalize_identity_text(
                        item.display_name
                    )
                ),
                -item.pk,
            ),
            reverse=True,
        )
        target = candidates[0]

        for source in candidates[1:]:
            _merge_counterparty(
                source=source,
                target=target,
            )
            counters["merged"] += 1

    # 3) Mescla nomes normalizados exatamente iguais.
    duplicates = (
        Counterparty.objects.filter(
            is_active=True
        )
        .values("normalized_name")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    for item in duplicates:
        candidates = list(
            Counterparty.objects.filter(
                is_active=True,
                normalized_name=(
                    item["normalized_name"]
                ),
            )
            .annotate(
                tx_count=Count(
                    "transactions"
                )
            )
            .order_by(
                "-tx_count",
                "id",
            )
        )

        target = candidates[0]

        for source in candidates[1:]:
            target_ids = _counterparty_identifiers(
                target
            )
            source_ids = _counterparty_identifiers(
                source
            )

            # Homônimos com identificadores incompatíveis permanecem
            # separados, mesmo quando o nome normalizado é idêntico.
            if (
                target_ids
                and source_ids
                and target_ids.isdisjoint(
                    source_ids
                )
            ):
                continue

            _merge_counterparty(
                source=source,
                target=target,
            )
            counters["merged"] += 1

    return counters


@db_transaction.atomic
def merge_truncated_counterparties() -> int:
    """
    Segunda passagem após o rebuild. Mescla apenas pares de nomes truncados
    quando cada registro possui exatamente um candidato compatível.
    """
    active = list(
        Counterparty.objects.filter(
            is_active=True
        )
        .annotate(
            tx_count=Count(
                "transactions"
            )
        )
        .prefetch_related(
            "aliases"
        )
        .order_by("id")
    )

    compatibility: dict[int, list[int]] = {
        item.pk: []
        for item in active
    }
    by_id = {
        item.pk: item
        for item in active
    }

    for index, left in enumerate(active):
        for right in active[
            index + 1 :
        ]:
            if not truncated_name_equivalent(
                left.display_name,
                right.display_name,
            ):
                continue

            left_ids = _counterparty_identifiers(
                left
            )
            right_ids = _counterparty_identifiers(
                right
            )

            if (
                left_ids
                and right_ids
                and left_ids.isdisjoint(
                    right_ids
                )
            ):
                continue

            compatibility[left.pk].append(
                right.pk
            )
            compatibility[right.pk].append(
                left.pk
            )

    merged = 0
    consumed = set()

    for left in active:
        if left.pk in consumed:
            continue

        matches = compatibility.get(
            left.pk,
            [],
        )

        if len(matches) != 1:
            continue

        right_id = matches[0]

        if (
            right_id in consumed
            or len(
                compatibility.get(
                    right_id,
                    [],
                )
            )
            != 1
            or compatibility[
                right_id
            ][0]
            != left.pk
        ):
            continue

        right = by_id[right_id]
        pair = [left, right]
        pair.sort(
            key=lambda item: (
                len(
                    normalize_identity_text(
                        item.display_name
                    )
                ),
                item.tx_count,
                -item.pk,
            ),
            reverse=True,
        )
        target = pair[0]
        source = pair[1]

        _merge_counterparty(
            source=source,
            target=target,
        )
        consumed.add(
            source.pk
        )
        merged += 1

    return merged


@db_transaction.atomic
def deactivate_orphan_counterparties() -> int:
    # Só desativamos órfãos que carregam texto bancário gerado pelo resolver.
    # Assim um cadastro criado manualmente no Admin, ainda sem movimentos, é
    # preservado.
    orphan_ids = list(
        Counterparty.objects.filter(
            is_active=True,
            transactions__isnull=True,
            aliases__alias_type=(
                CounterpartyAlias.AliasType.BANK_TEXT
            ),
        )
        .distinct()
        .values_list(
            "pk",
            flat=True,
        )
    )

    if not orphan_ids:
        return 0

    return Counterparty.objects.filter(
        pk__in=orphan_ids
    ).update(
        is_active=False
    )



@dataclass(frozen=True, slots=True)
class ManualCounterpartyMergeResult:
    target_id: int
    merged_records: int
    moved_transactions: int
    final_display_name: str


def _full_tax_ids(
    counterparty: Counterparty,
) -> set[str]:
    result = set()

    if counterparty.tax_id:
        digits = _digits(
            counterparty.tax_id
        )
        if len(digits) in {
            11,
            14,
        }:
            result.add(digits)

    for alias in counterparty.aliases.filter(
        alias_type=(
            CounterpartyAlias.AliasType.TAX_ID
        )
    ):
        digits = _digits(
            alias.alias
        )
        if len(digits) in {
            11,
            14,
        }:
            result.add(digits)

    return result


def analyze_manual_counterparty_merge(
    counterparties,
) -> dict:
    items = list(
        counterparties
    )

    tax_ids = set()
    pix_ids = set()
    bank_ids = set()
    kinds = set()

    for counterparty in items:
        tax_ids.update(
            _full_tax_ids(
                counterparty
            )
        )

        if (
            counterparty.kind
            != Counterparty.Kind.UNKNOWN
        ):
            kinds.add(
                counterparty.kind
            )

        for alias in counterparty.aliases.all():
            normalized = (
                alias.normalized_alias
                or normalize_identity_text(
                    alias.alias
                )
            )

            if not normalized:
                continue

            if (
                alias.alias_type
                == CounterpartyAlias.AliasType.PIX
            ):
                pix_ids.add(
                    normalized
                )
            elif (
                alias.alias_type
                == CounterpartyAlias.AliasType.BANK_ID
            ):
                bank_ids.add(
                    normalized
                )

    strong_conflicts = []

    if len(tax_ids) > 1:
        strong_conflicts.append(
            (
                "Há CPFs/CNPJs completos diferentes entre "
                "os registros selecionados."
            )
        )

    if len(kinds) > 1:
        strong_conflicts.append(
            (
                "A seleção mistura registros classificados "
                "como Pessoa e Empresa."
            )
        )

    informational_warnings = []

    if len(pix_ids) > 1:
        informational_warnings.append(
            (
                "Existem identificadores PIX diferentes. "
                "Isso pode ser legítimo para a mesma pessoa, "
                "mas revise antes de confirmar."
            )
        )

    if len(bank_ids) > 1:
        informational_warnings.append(
            (
                "Existem identificadores bancários diferentes. "
                "Isso pode representar contas distintas da mesma "
                "pessoa ou cadastros realmente diferentes."
            )
        )

    return {
        "strong_conflicts": strong_conflicts,
        "has_strong_conflicts": bool(
            strong_conflicts
        ),
        "informational_warnings": (
            informational_warnings
        ),
        "tax_ids": sorted(
            tax_ids
        ),
        "pix_ids": sorted(
            pix_ids
        ),
        "bank_ids": sorted(
            bank_ids
        ),
        "kinds": sorted(
            kinds
        ),
    }


@db_transaction.atomic
def merge_counterparties_manually(
    *,
    counterparty_ids,
    target_id: int,
    final_display_name: str,
    allow_strong_conflicts: bool = False,
) -> ManualCounterpartyMergeResult:
    ids = tuple(
        dict.fromkeys(
            int(value)
            for value in counterparty_ids
        )
    )

    if len(ids) < 2:
        raise ValueError(
            "Selecione pelo menos duas contrapartes para unificar."
        )

    if len(ids) > 50:
        raise ValueError(
            "Unifique no máximo 50 registros por operação."
        )

    selected = list(
        Counterparty.objects.select_for_update()
        .filter(
            pk__in=ids,
            is_active=True,
        )
        .prefetch_related(
            "aliases"
        )
        .order_by("id")
    )

    if len(selected) != len(ids):
        raise ValueError(
            (
                "Um ou mais registros selecionados não existem "
                "ou já foram unificados."
            )
        )

    selected_by_id = {
        item.pk: item
        for item in selected
    }

    if target_id not in selected_by_id:
        raise ValueError(
            (
                "O registro principal precisa fazer parte "
                "da seleção."
            )
        )

    analysis = (
        analyze_manual_counterparty_merge(
            selected
        )
    )

    if (
        analysis[
            "has_strong_conflicts"
        ]
        and not allow_strong_conflicts
    ):
        raise ValueError(
            (
                "A seleção possui conflitos fortes de identidade. "
                "Revise os avisos e confirme explicitamente "
                "se realmente deseja unificar."
            )
        )

    final_display_name = " ".join(
        (final_display_name or "").split()
    )

    if not final_display_name:
        raise ValueError(
            "Informe o nome final da contraparte."
        )

    if len(final_display_name) > 200:
        raise ValueError(
            (
                "O nome final deve possuir no máximo "
                "200 caracteres."
            )
        )

    target = selected_by_id[
        target_id
    ]

    # Preserva o nome atual do registro principal como alias antes
    # de eventualmente alterar o display_name.
    _ensure_alias(
        counterparty=target,
        alias=target.display_name,
        alias_type=(
            CounterpartyAlias.AliasType.NAME
        ),
    )

    all_tax_ids = set(
        analysis["tax_ids"]
    )
    moved_transactions = 0
    merged_records = 0

    for source in selected:
        if source.pk == target.pk:
            continue

        # O display_name antigo também passa a identificar o registro final.
        _ensure_alias(
            counterparty=target,
            alias=source.display_name,
            alias_type=(
                CounterpartyAlias.AliasType.NAME
            ),
        )

        if source.tax_id:
            _ensure_alias(
                counterparty=target,
                alias=source.tax_id,
                alias_type=(
                    CounterpartyAlias.AliasType.TAX_ID
                ),
            )

        moved_transactions += (
            _merge_counterparty(
                source=source,
                target=target,
            )
        )
        merged_records += 1

    # Mantém um CPF/CNPJ canônico somente quando existe um único
    # documento completo no grupo. Em conflito, preserva o do target
    # e os demais ficam nos aliases para auditoria.
    canonical_tax_id = (
        next(iter(all_tax_ids))
        if len(all_tax_ids) == 1
        else target.tax_id
    )

    for tax_id in sorted(
        all_tax_ids
    ):
        _ensure_alias(
            counterparty=target,
            alias=tax_id,
            alias_type=(
                CounterpartyAlias.AliasType.TAX_ID
            ),
        )

    target.display_name = (
        final_display_name
    )
    target.normalized_name = (
        normalize_identity_text(
            final_display_name
        )
    )
    target.kind = (
        infer_counterparty_kind(
            final_display_name
        )
    )
    target.tax_id = (
        canonical_tax_id
        or ""
    )
    target.is_active = True
    target.full_clean()
    target.save(
        update_fields=[
            "display_name",
            "normalized_name",
            "kind",
            "tax_id",
            "is_active",
            "updated_at",
        ]
    )

    _ensure_alias(
        counterparty=target,
        alias=final_display_name,
        alias_type=(
            CounterpartyAlias.AliasType.NAME
        ),
    )

    return ManualCounterpartyMergeResult(
        target_id=target.pk,
        merged_records=merged_records,
        moved_transactions=(
            moved_transactions
        ),
        final_display_name=(
            target.display_name
        ),
    )

@db_transaction.atomic
def rebuild_counterparty_links() -> dict[str, int]:
    normalized = normalize_existing_counterparties()

    queryset = (
        Transaction.objects.exclude(
            source_type=(
                Transaction.SourceType.MANUAL
            ),
            counterparty__isnull=False,
        )
        .select_related(
            "counterparty"
        )
        .order_by("id")
    )

    total = queryset.count()
    linked = 0
    reassigned = 0
    unlinked = 0

    for transaction in queryset.iterator(
        chunk_size=500
    ):
        previous_id = (
            transaction.counterparty_id
        )

        resolved = (
            resolve_transaction_counterparty(
                transaction,
                force=True,
            )
        )

        if resolved is None:
            unlinked += 1
            continue

        linked += 1

        if (
            previous_id
            and previous_id
            != resolved.pk
        ):
            reassigned += 1

    truncated_merged = (
        merge_truncated_counterparties()
    )
    orphaned = (
        deactivate_orphan_counterparties()
    )

    return {
        "total": total,
        "linked": linked,
        "reassigned": reassigned,
        "unlinked": unlinked,
        "renamed": normalized["renamed"],
        "merged": normalized["merged"],
        "truncated_merged": truncated_merged,
        "orphaned": orphaned,
    }

