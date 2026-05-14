"""Tool: analisi campagne Meta — riusa il data-analyst-agent.

Espone:
  - list_meta_campaigns: campagne ACTIVE + PAUSED da <30gg su tutti i 6 account
  - analyze_campaign: payload completo (perf Meta + lead reali + funnel + ROAS + breakdown + delta)
"""
from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any, Optional

from lib.accounts import load_accounts
from lib.da_config import find_form_for_campaign
from lib.db import DBConfig, get_funnel_metrics
from lib.hubspot_api import HubSpotClient, HubSpotError
from lib.meta_api import MetaClient, MetaError


def _pg_config_from_env() -> DBConfig:
    return DBConfig(
        host=os.getenv("POSTGRES_HOST", "217.154.117.118"),
        port=int(os.getenv("POSTGRES_PORT", "5432") or "5432"),
        dbname=os.getenv("POSTGRES_DB", "db_kpi"),
        user=os.getenv("POSTGRES_USER", "looker_reader"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def _meta_clients() -> list[MetaClient]:
    out: list[MetaClient] = []
    for acc in load_accounts():
        if acc.is_configured:
            out.append(MetaClient(
                access_token=acc.access_token,
                ad_account_id=acc.ad_account_id,
                account_slug=acc.slug,
                account_name=acc.name,
            ))
    return out


def list_meta_campaigns(days_paused: int = 30) -> dict[str, Any]:
    """Lista campagne ACTIVE/PAUSED su tutti gli account Meta configurati."""
    rows: list[dict[str, Any]] = []
    for client in _meta_clients():
        try:
            for c in client.list_recent_campaigns(days_paused=int(days_paused)):
                rows.append({
                    "id": c.id,
                    "name": c.name,
                    "status": c.effective_status,
                    "objective": c.objective,
                    "account": c.account_name,
                    "account_slug": c.account_slug,
                    "updated_at": c.updated_time,
                })
        except MetaError as e:
            rows.append({"error": f"{client.account_slug}: {e}"})
    return {"campaigns": rows, "total": len([r for r in rows if 'id' in r])}


def analyze_campaign(
    *,
    campaign_id: str,
    account_slug: str,
    days: int = 30,
    blocks: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Analisi completa di una campagna Meta: perf, lead reali, funnel, ROAS, breakdown.

    blocks: sottoinsieme di [perf, lead, funnel, breakdown, confronto]. Default: tutti.
    """
    blocks = blocks or ["perf", "lead", "funnel", "breakdown", "confronto"]
    today = date.today()
    since = (today - timedelta(days=int(days))).isoformat()
    until = today.isoformat()

    # Trova il client per l'account
    client: Optional[MetaClient] = None
    for c in _meta_clients():
        if c.account_slug == account_slug.upper():
            client = c
            break
    if not client:
        return {"error": f"Account Meta '{account_slug}' non configurato"}

    # Recupera nome campagna (servira` al matching DB)
    try:
        all_camps = client.list_recent_campaigns(days_paused=365)
    except MetaError as e:
        return {"error": f"Meta API: {e}"}
    target = next((c for c in all_camps if c.id == campaign_id), None)
    if not target:
        return {"error": f"Campagna {campaign_id} non trovata su {account_slug}"}

    payload: dict[str, Any] = {
        "campaign_id": campaign_id,
        "campaign_name": target.name,
        "account": target.account_name,
        "objective": target.objective,
        "status": target.effective_status,
        "period": {"since": since, "until": until, "days": int(days)},
    }

    # Tipo campagna + action type "Risultati"
    try:
        meta_info = client.get_campaign_meta_info(campaign_id)
        payload["tipo_campagna"] = meta_info.campaign_type
        payload["meta_result_action_type"] = meta_info.leads_action_type
    except MetaError as e:
        payload["meta_info_error"] = str(e)
        meta_info = None

    # Performance Meta
    if "perf" in blocks or "lead" in blocks:
        try:
            ins = client.get_campaign_insights(
                campaign_id, since, until,
                leads_action_type=(meta_info.leads_action_type if meta_info else ""),
            )
            cpl_meta = (ins.spend / ins.leads_meta) if ins.leads_meta else 0.0
            payload["meta_insights"] = {
                "spend": round(ins.spend, 2),
                "impressions": ins.impressions,
                "clicks": ins.clicks,
                "ctr": round(ins.ctr, 2),
                "cpm": round(ins.cpm, 2),
                "cpc": round(ins.cpc, 2),
                "reach": ins.reach,
                "leads_meta": ins.leads_meta,
                "leads_action_type_usato": ins.leads_action_type,
                "conversions_offsite": ins.conversions_offsite,
                "cpl_meta": round(cpl_meta, 2),
            }
        except MetaError as e:
            payload["meta_insights_error"] = str(e)

    # Lead reali (HubSpot per landing, Meta per Lead Ad)
    if "lead" in blocks:
        camp_type = payload.get("tipo_campagna", "unknown")
        if camp_type == "lead_ad":
            payload["lead_reali"] = {
                "fonte": "Meta",
                "totale": payload.get("meta_insights", {}).get("leads_meta", 0),
                "cpl_reale": payload.get("meta_insights", {}).get("cpl_meta", 0),
            }
        else:
            mapping = find_form_for_campaign(target.name)
            hs_token = os.getenv("HUBSPOT_ACCESS_TOKEN", "")
            if not mapping:
                payload["lead_reali"] = {
                    "fonte": "HubSpot",
                    "warning": f"Form HubSpot non mappato per '{target.name}'",
                }
            elif not hs_token:
                payload["lead_reali"] = {"fonte": "HubSpot", "warning": "HUBSPOT_ACCESS_TOKEN mancante"}
            else:
                try:
                    stats = HubSpotClient(hs_token).count_submissions(
                        mapping.form_id, since, until, mapping.form_name,
                    )
                    spend = payload.get("meta_insights", {}).get("spend", 0)
                    cpl_t = (spend / stats.total) if stats.total else 0
                    cpl_u = (spend / stats.unique_emails) if stats.unique_emails else 0
                    payload["lead_reali"] = {
                        "fonte": "HubSpot",
                        "form": mapping.form_name,
                        "totale_submission": stats.total,
                        "lead_unici": stats.unique_emails,
                        "cpl_su_totale": round(cpl_t, 2),
                        "cpl_su_unici": round(cpl_u, 2),
                    }
                except HubSpotError as e:
                    payload["lead_reali"] = {"fonte": "HubSpot", "errore": str(e)}

    # Funnel + ROAS dal Postgres KPI
    if "funnel" in blocks:
        cfg = _pg_config_from_env()
        if not cfg.password:
            payload["funnel_db"] = {"errore": "POSTGRES_PASSWORD mancante"}
        else:
            try:
                f = get_funnel_metrics(cfg, target.name, since, until)
                payload["funnel_db"] = {
                    "matched_names": f.matched_names,
                    "lead": f.lead,
                    "unici": f.unici,
                    "risposte": f.risposte,
                    "app_set": f.app_set,
                    "app_proc": f.app_proc,
                    "vendite": f.app_conv,
                    "boom_value": round(f.boom_value, 2),
                    "spesa_db": round(f.spesa_db, 2),
                    "roas": round(f.roas, 2),
                    "tasso_presa_app_pct": round(f.tasso_presa_appuntamento, 1),
                    "tasso_chiusura_pct": round(f.tasso_chiusura, 1),
                }
            except Exception as e:
                payload["funnel_db"] = {"errore": str(e)}

    # Breakdown ads
    if "breakdown" in blocks:
        try:
            ads_rows = client.get_ad_breakdown(
                campaign_id, since, until,
                leads_action_type=(meta_info.leads_action_type if meta_info else ""),
            )
            payload["breakdown_ads"] = [
                {
                    "ad_name": r.ad_name,
                    "spend": round(r.spend, 2),
                    "ctr": round(r.ctr, 2),
                    "leads": r.leads_meta,
                    "conversions_offsite": r.conversions_offsite,
                }
                for r in ads_rows[:15]
            ]
        except MetaError as e:
            payload["breakdown_ads"] = {"errore": str(e)}

    # Confronto periodo precedente (solo perf+lead)
    if "confronto" in blocks:
        u = today
        s = today - timedelta(days=int(days))
        prev_u = s - timedelta(days=1)
        prev_s = prev_u - timedelta(days=int(days) - 1)
        try:
            prev = client.get_campaign_insights(
                campaign_id, prev_s.isoformat(), prev_u.isoformat(),
                leads_action_type=(meta_info.leads_action_type if meta_info else ""),
            )
            curr_ins = payload.get("meta_insights", {})
            def _delta(curr_v, prev_v):
                if not prev_v:
                    return 0.0 if not curr_v else 100.0
                return round((curr_v - prev_v) / prev_v * 100, 1)
            payload["confronto"] = {
                "periodo_precedente": {"since": prev_s.isoformat(), "until": prev_u.isoformat()},
                "delta_spend_pct": _delta(curr_ins.get("spend", 0), prev.spend),
                "delta_ctr_pct": _delta(curr_ins.get("ctr", 0), prev.ctr),
                "delta_cpm_pct": _delta(curr_ins.get("cpm", 0), prev.cpm),
                "delta_leads_pct": _delta(curr_ins.get("leads_meta", 0), prev.leads_meta),
            }
        except MetaError as e:
            payload["confronto"] = {"errore": str(e)}

    return payload


SCHEMAS = [
    {
        "name": "list_meta_campaigns",
        "description": (
            "Restituisce tutte le campagne Meta attualmente ACTIVE oppure "
            "PAUSED da meno di N giorni, su tutti gli account configurati "
            "(Swat, Patatino, LRES, GEN, MEP, ICMD). Usalo per scegliere "
            "una campagna da analizzare o quando l'operatore chiede 'cosa "
            "sta girando'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_paused": {
                    "type": "integer",
                    "description": "Mostra anche le PAUSED aggiornate negli ultimi N giorni. Default 30.",
                    "default": 30,
                },
            },
            "required": [],
        },
    },
    {
        "name": "analyze_campaign",
        "description": (
            "Analisi completa di una campagna Meta sul periodo richiesto: "
            "performance (spend, CTR, CPM, lead Meta), lead reali "
            "(HubSpot per landing, Meta per Lead Ad), funnel post-lead "
            "(presa appuntamento, chiamate, vendite, ROAS), breakdown per "
            "ad, e confronto col periodo precedente. Usalo per capire "
            "come sta andando e dare raccomandazioni."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {
                    "type": "string",
                    "description": "ID Meta della campagna (campo 'id' da list_meta_campaigns).",
                },
                "account_slug": {
                    "type": "string",
                    "description": "Slug account: SWAT | PATATINO | LRES | GEN | MEP | ICMD",
                },
                "days": {"type": "integer", "default": 30, "description": "Finestra in giorni (7/14/30/60/90)."},
                "blocks": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["perf", "lead", "funnel", "breakdown", "confronto"]},
                    "description": "Blocchi da estrarre. Default: tutti.",
                },
            },
            "required": ["campaign_id", "account_slug"],
        },
    },
]
