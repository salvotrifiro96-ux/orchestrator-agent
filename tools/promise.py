"""Tool: generazione e archivio promesse Hormozi-style.

Adatta la logica del promise-writer-agent come tool callable da Claude.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from lib.brief_store import BriefStore
from lib.promise_writer import Promise, write_promises


def _promise_to_dict(p: Promise) -> dict[str, Any]:
    return {
        "pre_headline": p.pre_headline,
        "usp_name": p.usp_name,
        "headline": p.headline,
        "sub_headline": p.sub_headline,
        "structure": p.structure,
        "levers": list(p.levers or ()),
        "rationale": p.rationale,
    }


def list_promise_briefs(limit: int = 20) -> dict[str, Any]:
    """Ritorna gli ultimi N brief salvati nell'archivio del promise-writer."""
    store = BriefStore.from_env()
    if not store:
        return {"error": "Supabase non configurato", "briefs": []}
    rows = store.list_recent(limit=int(limit))
    return {
        "briefs": [
            {
                "id": r.id,
                "title": r.title,
                "updated_at": r.updated_at,
                "n_promises": len(r.promises),
                "target_audience": r.brief.get("target_audience", "")[:120],
            }
            for r in rows
        ]
    }


def get_promise_brief(brief_id: str) -> dict[str, Any]:
    """Recupera un brief completo (input + promesse generate)."""
    store = BriefStore.from_env()
    if not store:
        return {"error": "Supabase non configurato"}
    row = store.get(brief_id)
    if not row:
        return {"error": f"Brief {brief_id} non trovato"}
    return {
        "id": row.id,
        "title": row.title,
        "brief": row.brief,
        "promises": row.promises,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def generate_promises(
    *,
    api_key: str,
    context: str,
    target_audience: str = "",
    brand_voice: str = "",
    n_headlines: int = 10,
    references: str = "",
    extra_instructions: str = "",
    save_to_archive: bool = True,
) -> dict[str, Any]:
    """Genera N promesse Hormozi-style e (opzionalmente) le salva in archivio."""
    promises = write_promises(
        api_key=api_key,
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        n_headlines=int(n_headlines),
        extra_instructions=extra_instructions,
    )
    payload_promises = [_promise_to_dict(p) for p in promises]
    out: dict[str, Any] = {"promises": payload_promises}

    if save_to_archive:
        store = BriefStore.from_env()
        if store:
            try:
                row = store.insert(
                    brief={
                        "context": context,
                        "references": references,
                        "target_audience": target_audience,
                        "brand_voice": brand_voice,
                        "n_headlines": int(n_headlines),
                        "extra_instructions": extra_instructions,
                    },
                    promises=payload_promises,
                )
                out["archive"] = {"saved": True, "brief_id": row.id, "title": row.title}
            except Exception as e:  # silenzioso: la chat puo` continuare anche senza save
                out["archive"] = {"saved": False, "error": str(e)}
        else:
            out["archive"] = {"saved": False, "error": "Supabase non configurato"}

    return out


# ── JSON-Schema per Claude tool definitions ───────────────────────────
SCHEMAS = [
    {
        "name": "list_promise_briefs",
        "description": (
            "Restituisce un elenco dei brief precedenti del promise-writer "
            "(archivio Supabase). Usalo quando l'operatore chiede di riprendere "
            "un lavoro passato, vedere lo storico promesse, o cercare un brief "
            "per target/argomento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Numero massimo di brief da ritornare (default 20).",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_promise_brief",
        "description": (
            "Recupera un brief specifico per ID, con tutte le promesse "
            "generate. Usalo dopo list_promise_briefs quando l'operatore "
            "vuole vedere il dettaglio di un brief."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "brief_id": {
                    "type": "string",
                    "description": "UUID del brief (campo 'id' restituito da list_promise_briefs).",
                },
            },
            "required": ["brief_id"],
        },
    },
    {
        "name": "generate_promises",
        "description": (
            "Genera nuove promesse Hormozi-style a 4 livelli (pre-headline, "
            "USP-name, headline, sub-headline). Salva automaticamente in "
            "archivio. Usa il context piu` ricco possibile: chi e` il target, "
            "cosa vendi, dream outcome, pain, prove, vincoli. Restituisce "
            "tutte le promesse generate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Blob testuale: offerta, target, dream outcome, pain, prove, vincoli. Piu dettagli = promesse migliori.",
                },
                "target_audience": {
                    "type": "string",
                    "description": "Target in una frase (es. 'coach 1-1 che vendono percorsi 1.500-3.000€').",
                },
                "brand_voice": {
                    "type": "string",
                    "description": "Tone di voce in una frase (es. 'diretto, italiano semplice, no anglicismi').",
                },
                "n_headlines": {
                    "type": "integer",
                    "description": "Quante promesse generare (5-25). Default 10.",
                    "default": 10,
                },
                "references": {
                    "type": "string",
                    "description": "(Opzionale) Esempi headline o pattern strutturali da imitare.",
                },
                "extra_instructions": {
                    "type": "string",
                    "description": "(Opzionale) Vincoli aggiuntivi (es. 'evita garanzie monetarie').",
                },
            },
            "required": ["context"],
        },
    },
]
