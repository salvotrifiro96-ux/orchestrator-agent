"""Tool: automation-specialist — workflow HubSpot (preview only V1).

V1: costruisce il payload del workflow Leone (form → conferma → nurturing)
e ritorna sia il JSON che la versione human-readable in markdown. NON pubblica
su HubSpot: la pubblicazione resta a carico dell'automation-specialist-agent.
"""
from __future__ import annotations

from typing import Any

from lib.automation_specialist.workflows import (
    build_funnel_workflow_payload,
    render_workflow_spec_md,
)


def build_hubspot_funnel_workflow(
    *,
    name: str,
    triggering_form_id: str,
    confirmation_email_id: str | None = None,
    confirmation_delay_minutes: int = 1,
    nurturing_sequence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Genera il payload del workflow Leone unico (form → conferma → nurturing).

    Args:
        name: nome del workflow in HubSpot
        triggering_form_id: ID HubSpot del form che fa partire il flow
        confirmation_email_id: ID Marketing Email conferma (opzionale)
        confirmation_delay_minutes: ritardo invio email conferma (default 1 min)
        nurturing_sequence: lista step nurturing. Ogni step: {"day": N, "email_id": "...", "subject": "..."}.
    """
    payload = build_funnel_workflow_payload(
        name=name,
        triggering_form_id=triggering_form_id,
        confirmation_email_id=confirmation_email_id,
        confirmation_delay_minutes=int(confirmation_delay_minutes),
        nurturing_sequence=nurturing_sequence or [],
        enabled=False,  # SEMPRE disabled V1: serve HITL prima di pubblicare
    )
    md_spec = render_workflow_spec_md(payload)
    return {
        "workflow_payload": payload,
        "spec_markdown": md_spec,
        "delivery_hint": (
            "Preview-only V1. Per pubblicare il workflow su HubSpot "
            "(richiede HUBSPOT_ACCESS_TOKEN write), passa il payload "
            "all'automation-specialist-agent. V2: publish diretto da qui "
            "con HITL confirm."
        ),
    }


SCHEMAS = [
    {
        "name": "build_hubspot_funnel_workflow",
        "description": (
            "Costruisce il PAYLOAD JSON di un workflow HubSpot v4 (form -> "
            "conferma -> nurturing) e ne mostra una spec markdown. NON "
            "pubblica: l'operatore lo finalizza nell'automation-specialist-"
            "agent. Da usare a fine ciclo (lead magnet + mail + nurturing "
            "gia` pronti)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome del workflow in HubSpot."},
                "triggering_form_id": {"type": "string", "description": "Form GUID HubSpot che fa partire il flow."},
                "confirmation_email_id": {"type": "string", "description": "Marketing Email ID di conferma (opzionale)."},
                "confirmation_delay_minutes": {"type": "integer", "default": 1},
                "nurturing_sequence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "integer", "description": "Giorno dall'iscrizione."},
                            "email_id": {"type": "string"},
                            "subject": {"type": "string"},
                        },
                    },
                    "description": "Lista step nurturing in ordine cronologico.",
                },
            },
            "required": ["name", "triggering_form_id"],
        },
    },
]
