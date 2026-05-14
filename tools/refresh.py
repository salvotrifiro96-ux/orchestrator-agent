"""Tool: funnel-refresher — diagnosi creative + raccomandazioni pause/scale/test.

Usa la lib `funnel_refresher.diagnose` che fa analisi per-referral aggregando
lead Meta pixel + insights.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from lib.accounts import load_accounts
from lib.funnel_refresher.diagnose import run_diagnosis
from lib.funnel_refresher.meta_api import MetaClient as RefresherMeta


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def diagnose_campaign_refresh(
    *,
    campaign_id: str,
    account_slug: str,
    days: int = 14,
) -> dict[str, Any]:
    """Diagnosi della campagna: ads per-referral con CPL, raccomandazioni pause/scale/test."""
    account_slug = account_slug.upper()
    meta_account = None
    for acc in load_accounts():
        if acc.slug == account_slug and acc.is_configured:
            meta_account = acc
            break
    if not meta_account:
        return {"error": f"Account Meta '{account_slug}' non configurato"}

    client = RefresherMeta(
        access_token=meta_account.access_token,
        ad_account_id=meta_account.ad_account_id,
    )
    try:
        report = run_diagnosis(meta=client, campaign_id=campaign_id, days=int(days))
    except Exception as e:
        return {"error": f"Diagnosi fallita: {e}"}

    return {
        "campaign_id": campaign_id,
        "account": account_slug,
        "days": int(days),
        "report": _to_dict(report),
    }


SCHEMAS = [
    {
        "name": "diagnose_campaign_refresh",
        "description": (
            "Analisi 'creative refresh' di una campagna Meta: aggrega per "
            "referral (img1, img2, vid1...) la spesa, CTR, CPL pixel, e "
            "produce raccomandazioni pause/scale/test. Usalo quando "
            "l'operatore chiede 'cosa pauso o cosa scalo' su una campagna "
            "che gira."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "ID Meta della campagna."},
                "account_slug": {"type": "string", "enum": ["SWAT", "PATATINO", "LRES", "GEN", "MEP", "ICMD"]},
                "days": {"type": "integer", "default": 14, "description": "Finestra in giorni."},
            },
            "required": ["campaign_id", "account_slug"],
        },
    },
]
