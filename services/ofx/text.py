from __future__ import annotations

import re


# Caracteres/sequências comuns quando bytes UTF-8 são interpretados
# incorretamente como Windows-1252/Latin-1.
_SUSPICIOUS_RE = re.compile(
    r"""
    Ã.
    |Â.
    |â(?:€|€™|€œ|€|€¢|€“|€”|€¦|€˜|€š|€ž|€¡|€º|€¹|€‹|€º)?
    |ð.
    |�+
    """,
    re.VERBOSE,
)

# Controles C1 (U+0080..U+009F) quase nunca são desejáveis em histórico bancário.
_C1_RE = re.compile(r"[\u0080-\u009f]")


def _mojibake_score(text: str) -> int:
    """
    Quanto maior o score, mais provável que o texto esteja corrompido.

    Não tentamos "adivinhar" o idioma; apenas penalizamos padrões típicos
    de UTF-8 mal interpretado e caracteres de substituição/controle.
    """
    if not text:
        return 0

    score = 0
    score += len(_SUSPICIOUS_RE.findall(text)) * 4
    score += len(_C1_RE.findall(text)) * 5
    score += text.count("\ufffd") * 10

    # Sequências muito recorrentes no caso brasileiro.
    for marker in (
        "Ã¡",
        "Ã ",
        "Ã¢",
        "Ã£",
        "Ã¤",
        "Ã©",
        "Ãª",
        "Ã­",
        "Ã³",
        "Ã´",
        "Ãµ",
        "Ãº",
        "Ã§",
        "Ã",
        "Ã‰",
        "Ã‡",
        "Â ",
        "Â°",
        "â€¢",
        "â€“",
        "â€”",
        "â€œ",
        "â€",
        "â€™",
        "â€¦",
    ):
        score += text.count(marker) * 6

    return score


def _decode_candidate(text: str, source_encoding: str) -> str | None:
    try:
        return text.encode(source_encoding).decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def repair_mojibake(text: str) -> str:
    """
    Repara mojibake do tipo UTF-8 → CP1252/Latin-1, sem alterar texto correto.

    Exemplos:
        "Compra no dÃ©bito"   -> "Compra no débito"
        "TransferÃªncia"      -> "Transferência"
        "â€¢â€¢â€¢713"        -> "•••713"

    A transformação só é aceita se reduzir o score de corrupção.
    São permitidas até duas passagens para cobrir mojibake duplo.
    """
    if not text:
        return text

    current = text

    for _ in range(2):
        current_score = _mojibake_score(current)

        if current_score == 0:
            break

        candidates: list[str] = []

        for encoding in ("cp1252", "latin-1"):
            candidate = _decode_candidate(
                current,
                encoding,
            )

            if candidate is not None:
                candidates.append(candidate)

        if not candidates:
            break

        best = min(
            candidates,
            key=_mojibake_score,
        )
        best_score = _mojibake_score(best)

        if best_score >= current_score:
            break

        current = best

    return current


def normalize_display_text(text: str) -> str:
    """
    Repara encoding e remove apenas espaços redundantes de apresentação.

    Não remove acentos, pontuação, CPF mascarado, nomes ou informação bancária.
    """
    repaired = repair_mojibake(text.strip())
    return " ".join(repaired.split())
