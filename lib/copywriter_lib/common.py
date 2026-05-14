"""Shared helpers per il copywriter-agent.

Tutti i moduli (ads, confirmation, nurturing) usano lo stesso pattern:
- richiesta a Claude con system prompt specializzato
- output JSON strutturato
- parsing tollerante (con o senza code fences)

Questo modulo concentra:
- selezione modello unico (cosi` cambiamo versione in un solo posto)
- estrazione JSON dalla risposta
- rendering condizionale di sezioni del prompt
"""
from __future__ import annotations

import json
import re

# Tutto il team agenti usa lo stesso modello — cambiarlo qui si propaga.
CLAUDE_MODEL = "claude-sonnet-4-6"


def extract_json(raw: str) -> list[dict] | dict:
    """Estrae JSON da una risposta Claude, tollerando code fences opzionali.

    Accetta sia array che oggetti — il caller sa cosa aspettarsi.
    """
    raw = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    return json.loads(raw)


def section(label: str, body: str) -> str:
    """Renderizza una sezione del prompt utente, o stringa vuota se body e` blank."""
    body = (body or "").strip()
    if not body:
        return ""
    return f"\n## {label}\n{body}\n"


def clean_str(value: object) -> str:
    """Cast a stringa, strip, mai None."""
    if value is None:
        return ""
    return str(value).strip()


def clean_list(value: object) -> tuple[str, ...]:
    """Normalizza un campo list-of-strings dal JSON (Claude a volte ritorna
    stringhe singole anche dove ci si aspetta una lista)."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(clean_str(v) for v in value if clean_str(v))
    return ()
