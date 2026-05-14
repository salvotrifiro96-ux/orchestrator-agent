"""Tool: web designer — genera landing HTML/Tailwind via funnel-landing-agent.

V1: ritorna l'HTML. La pubblicazione su GitHub Pages resta manuale tramite
il funnel-landing-agent (richiede GitHub token + scelta repo).
"""
from __future__ import annotations

from typing import Any

from lib.funnel_landing.landing_gen import (
    BodyImageSpec,
    LandingBrief,
    generate_landing,
)


def generate_landing_html(
    *,
    api_key: str,
    client_name: str,
    slug: str,
    project_context: str,
    form_html: str = "",
    brand_colors_hex: dict[str, str] | None = None,
    font_family: str = "Inter",
    style_keywords: str = "diretto, premium, italiano",
    references: str = "",
) -> dict[str, Any]:
    """Genera la pagina HTML/Tailwind per la landing.

    Args:
        client_name: nome del cliente / brand (es. "Leone Master School")
        slug: slug per la URL (es. "workshop-15-giugno-dipendenti-artificiali")
        project_context: tutto cio` che sai (offerta, target, promessa, dream outcome, prove)
        form_html: HTML del form di iscrizione (HubSpot embed o custom). Vuoto = CTA finta.
        brand_colors_hex: dict tipo {"primary": "#16a34a", "accent": "#0f172a"}
        font_family: nome Google Font (default Inter)
        style_keywords: keywords stilistiche

    Returns:
        {"html": "...", "slug": "...", "delivery_hint": "..."}
    """
    brief = LandingBrief(
        client_name=client_name,
        slug=slug,
        project_context=project_context,
        form_html=form_html or "<!-- placeholder form -->",
        brand_colors_hex=brand_colors_hex or {"primary": "#16a34a", "accent": "#0f172a"},
        font_family=font_family,
        style_keywords=style_keywords,
        references=references,
    )
    page = generate_landing(api_key=api_key, brief=brief)
    return {
        "slug": slug,
        "html": page.html,
        "image_slots": [
            {"id": s.slot_id, "alt": s.alt, "purpose": getattr(s, "purpose", "")}
            for s in (page.image_slots or [])
        ],
        "delivery_hint": (
            "HTML pronto. Per pubblicarlo su landing.leonemasterschool.it/{slug} "
            "passa il brief al funnel-landing-agent che gestisce il deploy su "
            "GitHub Pages. V2: pubblichero` direttamente da qui."
        ),
    }


SCHEMAS = [
    {
        "name": "generate_landing_html",
        "description": (
            "Genera l'HTML/Tailwind completo di una landing page partendo "
            "dal contesto progetto (promessa, target, offerta, prove). "
            "V1: ritorna l'HTML; la pubblicazione su landing.leonemasterschool.it "
            "resta a carico del funnel-landing-agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string", "description": "Brand/cliente (es. 'Leone Master School')."},
                "slug": {"type": "string", "description": "Slug URL (es. 'workshop-15-giugno-dipendenti-artificiali')."},
                "project_context": {
                    "type": "string",
                    "description": "Contesto completo: promessa, target, offerta, dream outcome, prove, anti-obiezioni.",
                },
                "form_html": {"type": "string", "description": "HTML del form HubSpot embed (opzionale)."},
                "brand_colors_hex": {
                    "type": "object",
                    "description": "Es. {\"primary\": \"#16a34a\", \"accent\": \"#0f172a\"}.",
                },
                "font_family": {"type": "string", "default": "Inter"},
                "style_keywords": {"type": "string", "default": "diretto, premium, italiano"},
                "references": {"type": "string", "description": "Opzionale: esempi/riferimenti."},
            },
            "required": ["client_name", "slug", "project_context"],
        },
    },
]
