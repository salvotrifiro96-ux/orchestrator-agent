"""Orchestrator — DISCOVERY MODE.

L'orchestratore ha UN SOLO compito qui: dialogare con l'utente per costruire
il "contesto ufficiale" del progetto marketing. Non esegue azioni, non lancia
agenti. Quando ha abbastanza info chiama il tool `propose_final_context`
con il contesto strutturato; la UI mostra il proposal e l'utente lo approva.

Approvato il contesto, il flusso prosegue fuori da qui (dashboard distribuisce
il contesto agli 8 agenti).
"""
from __future__ import annotations

import json
from typing import Any, Callable

from anthropic import Anthropic


# ── Schema del contesto ufficiale ────────────────────────────────────
CONTEXT_FIELDS: list[tuple[str, str]] = [
    ("client_name", "Brand / cliente per cui stai facendo marketing"),
    ("campaign_name_proposal", "Nome lavoro della campagna (slug-friendly)"),
    ("campaign_goal", "Obiettivo della campagna in una frase (es. lead gen workshop)"),
    ("target_audience", "Target preciso: chi e`, eta`, ruolo, contesto"),
    ("dream_outcome", "Cosa ottiene il prospect se compra (sensazione + numeri)"),
    ("pain_points", "Dolori e frustrazioni del target oggi"),
    ("offer", "Cosa stai vendendo o offrendo (lead magnet + offerta back-end)"),
    ("price_range", "Range prezzi / modello economico"),
    ("proof", "Prove sociali, case study, testimonianze, dati prec."),
    ("constraints", "Cosa NON dire, vincoli legali, brand boundaries"),
    ("brand_voice", "Tone of voice in una frase"),
    ("deadline", "Date chiave (evento, lancio ads, fine campagna)"),
    ("channels", "Canali ads dove pubblicare (meta/google/tiktok/linkedin)"),
    ("lead_magnet", "Cosa ottiene il lead in cambio dell'optin"),
    ("notes_extra", "Tutto cio` che non rientra sopra ma e` rilevante"),
]


SYSTEM_PROMPT_DISCOVERY = """\
Sei l'**Orchestratore** del team Marketing AI di Leone Master School.

Il tuo UNICO compito in questa conversazione e` **costruire il contesto \
ufficiale del progetto** facendo domande precise all'utente, una alla \
volta o al massimo due. NON eseguire azioni, NON chiamare altri agenti, \
NON proporre copy o promesse — solo raccolta info.

# Approccio
1. Italiano, diretto, niente fronzoli.
2. Fai una domanda alla volta (max 2 se sono connesse).
3. Se l'utente da risposte vaghe, sonda piu` in profondita` ("dammi un esempio concreto", "che numeri ha visto questo target?").
4. Sii esigente: il contesto sara` distribuito agli 8 agenti del team — se e` povero, il lavoro a valle e` povero.
5. Quando hai TUTTI i campi necessari (vedi sotto), chiama il tool `propose_final_context` con il riassunto strutturato. NON proporre il riassunto in testo libero — usa il tool.

# Campi del contesto da raccogliere

Devi raccogliere queste informazioni prima di chiamare propose_final_context:
- client_name: brand / cliente
- campaign_name_proposal: nome slug-friendly della campagna
- campaign_goal: obiettivo in una frase
- target_audience: chi e` (eta`, ruolo, contesto)
- dream_outcome: cosa ottiene il prospect (sensazione + numeri)
- pain_points: dolori attuali del target
- offer: cosa vendi (lead magnet + offerta back-end)
- price_range: prezzi
- proof: prove sociali / case study / dati
- constraints: cosa NON dire, vincoli
- brand_voice: tone of voice in una frase
- deadline: date chiave
- channels: lista canali (meta/google/tiktok/linkedin)
- lead_magnet: cosa ottiene il lead optin
- notes_extra: tutto il resto

# Quando chiami propose_final_context
Sii fedele a quello che l'utente ha detto — non inventare. Se un campo e` \
genuinamente vuoto, mettilo come stringa vuota (non come "non specificato"). \
Per channels usa una lista, anche di un solo elemento.

Dopo il tool call, scrivi una nota di chiusura tipo:
"Ho composto il contesto ufficiale. Rivedilo sopra e clicca 'Approva e \
distribuisci' per attivare il team. Se vuoi cambiare qualcosa dimmi cosa."
"""


PROPOSE_CONTEXT_TOOL = {
    "name": "propose_final_context",
    "description": (
        "Da chiamare UNA SOLA VOLTA quando hai raccolto tutte le info "
        "necessarie. Genera il contesto ufficiale strutturato che sara` "
        "distribuito agli 8 agenti del team al click dell'utente."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            field: {"type": "string", "description": desc}
            for field, desc in CONTEXT_FIELDS if field != "channels"
        } | {
            "channels": {
                "type": "array",
                "items": {"type": "string", "enum": ["meta", "google", "tiktok", "linkedin"]},
                "description": "Canali ads dove pubblicare.",
            },
        },
        "required": [f for f, _ in CONTEXT_FIELDS if f != "notes_extra"],
    },
}


def run_discovery_turn(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    on_event: Callable[[dict[str, Any]], None] | None = None,
    max_iterations: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Esegue un turno di discovery. Restituisce (messages aggiornate, proposed_context|None).

    Se Claude chiama `propose_final_context`, il dict ritornato e` il contesto;
    altrimenti None (la conversazione continua).
    """
    client = Anthropic(api_key=api_key)
    proposed_context: dict[str, Any] | None = None
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        if on_event:
            on_event({"type": "round_start", "iter": iterations})
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT_DISCOVERY,
            tools=[PROPOSE_CONTEXT_TOOL],
            messages=messages,
        )
        assistant_blocks: list[dict[str, Any]] = []
        tool_uses = []
        for block in resp.content:
            t = getattr(block, "type", None)
            if t == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
                if on_event:
                    on_event({"type": "assistant_text", "text": block.text})
            elif t == "tool_use":
                assistant_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                tool_uses.append(block)
                if on_event:
                    on_event({"type": "tool_use", "name": block.name, "input": block.input})
        messages.append({"role": "assistant", "content": assistant_blocks})

        # Catturo il proposed context se Claude chiama il tool
        for tu in tool_uses:
            if tu.name == "propose_final_context":
                proposed_context = dict(tu.input or {})

        if resp.stop_reason != "tool_use":
            return messages, proposed_context

        # In modalita` discovery l'unico tool e` propose_final_context, e
        # la sua "esecuzione" e` solo conferma — non c'e` un side effect
        # da fare lato server; rispondiamo con un tool_result vuoto
        # cosi` Claude puo` chiudere il turno con la nota di chiusura.
        tool_results = []
        for tu in tool_uses:
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps({"received": True, "info": "Contesto ricevuto. Il sistema lo mostrera` all'utente per approvazione."}),
            })
        messages.append({"role": "user", "content": tool_results})

    return messages, proposed_context
