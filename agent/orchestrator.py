"""Orchestrator core: Claude tool-use loop.

Pattern:
  1. send messages + tools -> Anthropic
  2. if stop_reason="tool_use": esegui tool, append tool_result, ricicla
  3. else: ritorna messages aggiornati

Tutti i messaggi (anche tool_use / tool_result) sono memorizzati nella history
cosi` un turno conversazionale successivo ha tutto il contesto.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from anthropic import Anthropic

from agent.tools_registry import TOOL_SCHEMAS, dispatch


SYSTEM_PROMPT = """\
Sei l'**Orchestratore** del team Marketing AI di Leone Master School.

Coordini un'agenzia di marketing reale composta da agenti specializzati. \
L'operatore umano ti da una direttiva (es. "lanciamo workshop X", \
"analizziamo la campagna 22 nicchie", "rifacciamo i copy delle ads"); \
tu capisci cosa serve, deleghi agli agenti via tool call, e riporti i \
risultati. Stile: italiano, pragmatico, diretto.

# Gli agenti a tua disposizione (via tool)

- **promise-writer**: `list_promise_briefs`, `get_promise_brief`, \
`generate_promises`. Genera promesse Hormozi-style a 4 livelli.
- **copywriter**: `write_ad_copy` (canale meta/google/tiktok/linkedin), \
`write_email_confirmation`, `write_nurturing_sequence`.
- **web designer (funnel-landing)**: `generate_landing_html` produce HTML/Tailwind \
completo; la pubblicazione su landing.leonemasterschool.it resta a carico \
del funnel-landing-agent (richiede GitHub token).
- **graphic-designer**: `make_visual_brief` (V1: brief strutturato pronto per \
graphic-designer-agent; V2: gen immagine diretta).
- **media-buyer**: `propose_ad_launch` (V1: proposta parametri; conferma e \
lancio nel media-buyer-agent. V2: launch diretto via Meta API).
- **data-analyst**: `list_meta_campaigns`, `analyze_campaign` (performance + \
funnel + ROAS + breakdown + delta).
- **funnel-refresher**: `diagnose_campaign_refresh` (analisi per-referral, \
pause/scale/test suggestions).
- **automation-specialist**: `build_hubspot_funnel_workflow` (V1: payload \
preview-only; pubblicazione nell'automation-specialist-agent).

# Regole

1. **Pensa prima di delegare**: se la direttiva e` ambigua, fai 1-2 domande \
prima di chiamare tool. Non sparare tool a caso.
2. **Mai inventare dati**: se ti serve un numero (es. spesa di una campagna), \
chiamalo via `analyze_campaign`. Non stimare.
3. **HITL su azioni costose**: PRIMA di chiamare `propose_ad_launch` o \
qualsiasi modifica HubSpot/Meta/Email, riassumi l'azione e CHIEDI conferma \
testuale all'operatore ("OK procedo?"). Aspetta sua risposta esplicita.
4. **Riusa l'archivio**: prima di rigenerare promesse o copy da zero, controlla \
se esiste gia` qualcosa in archivio (`list_promise_briefs`).
5. **Riassunto finale**: a fine turno, sintetizza in 3-5 punti cosa hai \
fatto, cosa hai prodotto, cosa serve all'operatore (eventuali link agli \
agenti per finalizzare).
6. **Brevita`**: niente paragrafi inutili. Numeri, bullet, link. Solo cose \
azionabili.

# Catena marketing tipica (per orientarti)

Promessa → Copy → Visual → Landing (se servono) → Lancio Ads → Funnel \
Email (conferma + nurturing) → Analisi → Refresh creative.

# Output

Quando ricevi tool_result, valutali criticamente. Se un numero sembra strano \
(es. ROAS 50x, CTR 8%), segnalalo come "verifica" invece di darlo per buono.
"""


def run_loop(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    on_event: Callable[[dict[str, Any]], None] | None = None,
    max_iterations: int = 8,
) -> list[dict[str, Any]]:
    """Esegue un turno conversazionale: chiama Claude, esegue eventuali tool,
    ricicla finche` Claude restituisce un messaggio finale (`stop_reason != tool_use`).

    Args:
        messages: history conversazionale completa (modificata in-place: i nuovi
                  messages assistant/tool_result vengono appesi).
        on_event: callback chiamato per ogni evento (testo, tool_use, tool_result,
                  errore). La UI Streamlit lo usa per render incrementale.
        max_iterations: limite rounds prevenzione loop infinito.

    Returns:
        La stessa lista `messages`, aggiornata in-place per comodita`.
    """
    client = Anthropic(api_key=api_key)
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        if on_event:
            on_event({"type": "round_start", "iter": iterations})
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        assistant_blocks: list[dict[str, Any]] = []
        tool_uses = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
                if on_event:
                    on_event({"type": "assistant_text", "text": block.text})
            elif btype == "tool_use":
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

        if resp.stop_reason != "tool_use":
            if on_event:
                on_event({"type": "end_turn", "iter": iterations})
            return messages

        # Eseguo i tool richiesti e riempio i tool_result
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            tool_name = tu.name
            tool_args = tu.input or {}
            try:
                result = dispatch(tool_name, tool_args, anthropic_api_key=api_key)
                payload = json.dumps(result, ensure_ascii=False, default=str)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": payload,
                })
                if on_event:
                    on_event({"type": "tool_result", "name": tool_name, "result": result})
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps({"error": err_msg}, ensure_ascii=False),
                    "is_error": True,
                })
                if on_event:
                    on_event({"type": "tool_error", "name": tool_name, "error": err_msg})
        messages.append({"role": "user", "content": tool_results})

    if on_event:
        on_event({"type": "max_iterations_reached"})
    return messages
