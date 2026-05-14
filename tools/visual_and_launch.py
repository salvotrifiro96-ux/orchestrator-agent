"""Tool stub V1: visual brief + propose ad launch.

Per ora questi 2 tool generano output strutturato pronto per l'esecuzione
manuale (graphic-designer-agent / media-buyer-agent). In V2 li implementeremo
end-to-end (gpt-image-1, Meta API direct launch).
"""
from __future__ import annotations

from typing import Any


def make_visual_brief(
    *,
    promise: str,
    target_audience: str,
    channel: str = "meta",
    aspect_ratio: str = "1:1",
    mood: str = "",
    must_have: list[str] | None = None,
    must_avoid: list[str] | None = None,
) -> dict[str, Any]:
    """Compone un brief visivo strutturato pronto per il graphic-designer-agent."""
    return {
        "channel": channel,
        "aspect_ratio": aspect_ratio,
        "promise_summary": promise[:300],
        "target_audience": target_audience,
        "mood": mood or "diretto, premium, italiano, pulito",
        "must_have": must_have or [],
        "must_avoid": must_avoid or ["stock photo generiche", "AI hands rotte"],
        "delivery_hint": (
            "Incolla questo brief nel Graphic Designer Agent "
            "(https://graphic-designer-agent.streamlit.app) — V1 stub, "
            "V2 generera` direttamente l'immagine via gpt-image-1."
        ),
    }


def propose_ad_launch(
    *,
    account_slug: str,
    campaign_name: str,
    budget_daily_eur: int,
    objective: str,
    target: str,
    placements: str = "advantage_plus",
    copy_summary: str = "",
    visual_summary: str = "",
    start_date: str = "",
) -> dict[str, Any]:
    """Prepara una proposta di lancio campagna Meta. NON lancia: l'operatore
    rivede la preview e poi conferma manualmente nel media-buyer-agent."""
    return {
        "status": "PROPOSAL_ONLY_REQUIRES_CONFIRMATION",
        "account": account_slug.upper(),
        "campaign_name": campaign_name,
        "budget_daily_eur": int(budget_daily_eur),
        "objective": objective,
        "target_description": target,
        "placements": placements,
        "copy_summary": copy_summary[:400],
        "visual_summary": visual_summary[:400],
        "start_date": start_date or "appena confermato",
        "delivery_hint": (
            "V1: usa il Media Buyer Agent "
            "(https://media-buyer-agent.streamlit.app) per finalizzare il "
            "lancio — copia questi parametri lì. V2: lancio diretto via "
            "Meta API con HITL confirm in chat."
        ),
    }


SCHEMAS = [
    {
        "name": "make_visual_brief",
        "description": (
            "Compone un brief visivo strutturato per il graphic-designer. "
            "Usalo quando hai una promessa pronta e serve l'immagine ads. "
            "Output: brief che l'operatore incollera` nel graphic-designer-"
            "agent (V1 stub, V2 generera` l'immagine direttamente)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "promise": {"type": "string", "description": "La promessa (output del promise-writer)."},
                "target_audience": {"type": "string"},
                "channel": {"type": "string", "enum": ["meta", "google", "tiktok", "linkedin"], "default": "meta"},
                "aspect_ratio": {"type": "string", "enum": ["1:1", "4:5", "9:16", "16:9"], "default": "1:1"},
                "mood": {"type": "string", "description": "Tone visuale (es. 'diretto premium italiano')."},
                "must_have": {"type": "array", "items": {"type": "string"}, "description": "Elementi obbligatori."},
                "must_avoid": {"type": "array", "items": {"type": "string"}, "description": "Cose da evitare."},
            },
            "required": ["promise", "target_audience"],
        },
    },
    {
        "name": "propose_ad_launch",
        "description": (
            "Prepara una PROPOSTA di lancio campagna Meta per review umana. "
            "NON lancia automaticamente — produce solo un summary parametri "
            "che l'operatore conferma e finalizza nel media-buyer-agent. "
            "Usa SEMPRE request_confirmation dopo questo, perche` la "
            "campagna spende soldi."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_slug": {"type": "string", "enum": ["SWAT", "PATATINO", "LRES", "GEN", "MEP", "ICMD"]},
                "campaign_name": {"type": "string", "description": "Slug snake_case (es. 'lms_imprenditoria_workshop_X')."},
                "budget_daily_eur": {"type": "integer", "description": "Budget giornaliero in EUR."},
                "objective": {"type": "string", "enum": ["OUTCOME_LEADS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_SALES"]},
                "target": {"type": "string", "description": "Descrizione target (es. 'Broad Italia 25-65 Advantage')."},
                "placements": {"type": "string", "default": "advantage_plus"},
                "copy_summary": {"type": "string"},
                "visual_summary": {"type": "string"},
                "start_date": {"type": "string", "description": "ISO date o 'subito'."},
            },
            "required": ["account_slug", "campaign_name", "budget_daily_eur", "objective", "target"],
        },
    },
]
