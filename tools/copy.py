"""Tool: copywriting (Meta/Google/TikTok/LinkedIn ads, email conferma, sequenza nurturing).

Riusa la lib del copywriter-agent come tool callable da Claude.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from lib.copywriter_lib.ads import write_ads
from lib.copywriter_lib.confirmation import write_confirmation_mails
from lib.copywriter_lib.nurturing import write_sequence


def _dataclasses_to_dicts(items: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        try:
            out.append(asdict(it))
        except Exception:
            out.append({k: v for k, v in vars(it).items() if not k.startswith("_")})
    return out


def write_ad_copy(
    *,
    api_key: str,
    channel: str,
    context: str,
    promise: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    n_variants: int = 5,
    references: str = "",
    extra_instructions: str = "",
) -> dict[str, Any]:
    ch = channel.lower()
    if ch not in ("meta", "google", "tiktok", "linkedin"):
        return {"error": f"channel non supportato: {channel}. Usa meta|google|tiktok|linkedin"}
    ads = write_ads(
        api_key=api_key,
        channel=ch,  # type: ignore[arg-type]
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        promise=promise,
        n_variants=int(n_variants),
        extra_instructions=extra_instructions,
    )
    return {"channel": ch, "ads": _dataclasses_to_dicts(ads)}


def write_email_confirmation(
    *,
    api_key: str,
    context: str,
    promise: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    sender: str = "",
    n_variants: int = 3,
    references: str = "",
    extra_instructions: str = "",
) -> dict[str, Any]:
    mails = write_confirmation_mails(
        api_key=api_key,
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        sender=sender,
        n_variants=int(n_variants),
        extra_instructions=extra_instructions,
    )
    return {"mails": _dataclasses_to_dicts(mails)}


def write_nurturing_sequence(
    *,
    api_key: str,
    context: str,
    promise: str = "",
    offer: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    sender: str = "",
    n_mails: int = 5,
    cadence_days: int = 7,
    references: str = "",
    extra_instructions: str = "",
) -> dict[str, Any]:
    seq = write_sequence(
        api_key=api_key,
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        offer=offer,
        sender=sender,
        n_mails=int(n_mails),
        cadence_days=int(cadence_days),
        extra_instructions=extra_instructions,
    )
    return {"sequence": _dataclasses_to_dicts(seq), "cadence_days": int(cadence_days)}


SCHEMAS = [
    {
        "name": "write_ad_copy",
        "description": (
            "Genera N varianti di copy per ads su un canale specifico (meta, "
            "google, tiktok, linkedin). Da usare DOPO avere la promessa "
            "definita. Per Meta restituisce primary_text + headline + "
            "description; per Google rispetta RSA; per TikTok hook + body; "
            "per LinkedIn intro + body."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["meta", "google", "tiktok", "linkedin"],
                    "description": "Canale ads.",
                },
                "context": {
                    "type": "string",
                    "description": "Tutto cio` che sai su offerta, target, prove, dream outcome, pain.",
                },
                "promise": {
                    "type": "string",
                    "description": "La promessa scelta (output del promise-writer): pre + USP-name + headline + sub.",
                },
                "target_audience": {"type": "string"},
                "brand_voice": {"type": "string"},
                "n_variants": {"type": "integer", "default": 5, "description": "Numero varianti (3-10)."},
                "references": {"type": "string", "description": "Esempi/pattern opzionali."},
                "extra_instructions": {"type": "string"},
            },
            "required": ["channel", "context"],
        },
    },
    {
        "name": "write_email_confirmation",
        "description": (
            "Genera N varianti di mail di conferma iscrizione (post lead). "
            "Tono: caldo, breve, ricorda promise e prossimo step. Sender e "
            "promise sono fortemente raccomandati."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "promise": {"type": "string"},
                "target_audience": {"type": "string"},
                "brand_voice": {"type": "string"},
                "lead_magnet": {"type": "string", "description": "Cosa ottiene il lead (es. 'workshop gratuito 3 giorni')."},
                "sender": {"type": "string", "description": "Nome+cognome del sender (es. 'Leonardo Leone')."},
                "n_variants": {"type": "integer", "default": 3},
                "references": {"type": "string"},
                "extra_instructions": {"type": "string"},
            },
            "required": ["context"],
        },
    },
    {
        "name": "write_nurturing_sequence",
        "description": (
            "Genera una sequenza di N mail di nurturing post lead, con "
            "cadenza in giorni. Output: lista mail con subject + body + "
            "send_day. Da usare per warmup pre-vendita o post-evento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "promise": {"type": "string"},
                "offer": {"type": "string", "description": "Cosa stai vendendo nella sequenza."},
                "target_audience": {"type": "string"},
                "brand_voice": {"type": "string"},
                "lead_magnet": {"type": "string"},
                "sender": {"type": "string"},
                "n_mails": {"type": "integer", "default": 5},
                "cadence_days": {"type": "integer", "default": 7, "description": "Distanza in giorni fra una mail e la successiva."},
                "references": {"type": "string"},
                "extra_instructions": {"type": "string"},
            },
            "required": ["context"],
        },
    },
]
