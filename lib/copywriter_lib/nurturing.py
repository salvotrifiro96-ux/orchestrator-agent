"""Mail di nurturing per chi si e` iscritto a un funnel Leone.

Due modalita`:
  - SEQUENCE: l'operatore dice "5 mail in 7 giorni" e l'agente sforna
    l'intera sequenza, ogni mail con il suo ruolo nel funnel.
  - SINGLE: l'operatore dice "Day 3: anti-obiezione prezzo" e l'agente
    scrive solo quella mail.

Una sequenza ben costruita ha un arco narrativo:
  1. Bonding / chi-sei-tu
  2. Pain agitation / cosa-c-e-che-non-va
  3. Mechanism / il-come
  4. Proof / case-study
  5. Anti-objection / il-motivo-per-cui-non-comprerai
  6. Urgency + offer / l-azione-ora
"""
from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic

from .common import CLAUDE_MODEL, clean_str, extract_json, section

MIN_SEQUENCE = 3
MAX_SEQUENCE = 10


@dataclass(frozen=True)
class NurturingMail:
    """Singola mail di una sequenza di nurturing.

    Campi:
      - day:        giorno del funnel (es. 1, 2, 3...). 0 se single-mail
                    senza ordinamento esplicito.
      - role:       ruolo della mail nel funnel ('bonding', 'pain-agitation',
                    'mechanism', 'proof', 'anti-objection', 'urgency-offer'...)
      - subject:    oggetto inbox (~50 char)
      - preview:    preview text (~90 char)
      - body:       corpo plain text
      - signature:  firma 3-5 righe
      - cta:        cosa deve fare il lettore (es. 'prenota la call',
                    'guarda il video 2', 'rispondi a questa mail')
      - rationale:  perche` questa mail funziona qui nella sequenza
    """

    day: int
    role: str
    subject: str
    preview: str
    body: str
    signature: str
    cta: str
    rationale: str


_BASE_SYSTEM_PROMPT = (
    "Sei un email copywriter senior specializzato in funnel di nurturing per\n"
    "info-prodotti e high-ticket. Italiano nativo, tono diretto.\n\n"
    "## RUOLI TIPICI IN UNA SEQUENZA\n"
    "  - bonding: ti presento chi sono, perche` puoi fidarti\n"
    "  - pain-agitation: rendi visibile il problema, attiva il malessere\n"
    "  - mechanism: ti racconto IL COME (il metodo unico, l'insight chiave)\n"
    "  - proof: case study o testimonial concreto\n"
    "  - anti-objection: smonti l'obiezione piu` frequente\n"
    "  - urgency-offer: motivo per cui agire ORA + chiusura\n"
    "Le sequenze migliori alternano tono: emotivo / pratico / autorevole.\n\n"
    "## STRUTTURA PER OGNI MAIL\n"
    "  - SUBJECT (~50 char visibili): incuriosisce SENZA promesse mendaci.\n"
    "    Pattern: '[Domanda]', 'Ecco perche` [contro-intuitivo]', '[Nome di\n"
    "    cliente]: storia di [risultato]', 'Una cosa che faccio sempre prima\n"
    "    di [X]'. No CAPS, no spam triggers (GRATIS, GUADAGNA, !!!).\n"
    "  - PREVIEW (~90 char): estende il subject, NON lo ripete.\n"
    "  - BODY (120-260 parole): apri senza filler. Una sola idea per mail.\n"
    "    Frasi corte. Usa storytelling concreto (dialogo, scena, dato).\n"
    "    Una sola CTA, esplicita, mai nascosta. Placeholder ammessi:\n"
    "    [Nome], [LINK]. Niente markdown, niente HTML.\n"
    "  - SIGNATURE (3-5 righe): nome + ruolo + brand. PS opzionale per\n"
    "    rinforzare la CTA o aggiungere un dettaglio strategico.\n"
    "  - CTA (la frase che spinge il prossimo passo): UNA sola, chiara.\n\n"
    "## VIETATO\n"
    "  - asterischi/maiuscolo per enfasi, !!!\n"
    "  - tono da newsletter aziendale ('In questo articolo ti racconto...')\n"
    "  - mail-supermercato (6 link diversi, 4 PS)\n"
    "  - claim non sostenuti dal context (numeri inventati)\n"
    "  - chiusure formali ('Cordiali saluti')\n"
    "  - ripetere lo stesso angle in mail consecutive\n\n"
    "## OBBLIGATORIO\n"
    "  - tu/tuo, mai voi/lei\n"
    "  - varieta` di tono e ruolo lungo la sequenza\n"
    "  - storytelling concreto > teoria astratta\n"
    "  - coerenza con la PROMESSA del funnel e il LEAD MAGNET appena consegnato\n\n"
)


_SEQUENCE_OUTPUT_BLOCK = (
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON, niente prosa, niente markdown fences.\n"
    "Ogni elemento e` una mail della sequenza, in ORDINE crescente di day.\n"
    "Schema:\n"
    '  {"day":       intero (1, 2, 3...),\n'
    '   "role":      "uno dei ruoli elencati",\n'
    '   "subject":   "stringa non vuota",\n'
    '   "preview":   "stringa non vuota",\n'
    '   "body":      "stringa, 120-260 parole",\n'
    '   "signature": "stringa, 3-5 righe",\n'
    '   "cta":       "frase CTA chiara",\n'
    '   "rationale": "max 180 char"}\n'
)

_SINGLE_OUTPUT_BLOCK = (
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON di UN SOLO elemento, niente prosa,\n"
    "niente markdown fences. Schema (vedi sequenza). Se l'operatore non\n"
    "specifica il `day`, mettilo a 0.\n"
)


def _parse_items(items: list[dict]) -> list[NurturingMail]:
    out: list[NurturingMail] = []
    for it in items:
        subject = clean_str(it.get("subject"))
        body = clean_str(it.get("body"))
        if not subject or not body:
            continue
        try:
            day = int(it.get("day", 0) or 0)
        except (TypeError, ValueError):
            day = 0
        out.append(
            NurturingMail(
                day=day,
                role=clean_str(it.get("role")),
                subject=subject,
                preview=clean_str(it.get("preview")),
                body=body,
                signature=clean_str(it.get("signature")),
                cta=clean_str(it.get("cta")),
                rationale=clean_str(it.get("rationale")),
            )
        )
    return out


def _build_user_prompt_sequence(
    *,
    context: str,
    references: str,
    target_audience: str,
    brand_voice: str,
    lead_magnet: str,
    promise: str,
    offer: str,
    sender: str,
    n_mails: int,
    cadence_days: int,
    extra_instructions: str,
) -> str:
    parts = [
        section("Target audience", target_audience),
        section("Brand voice", brand_voice),
        section("Sender (firma)", sender),
        section("Lead magnet (cosa hanno appena ricevuto)", lead_magnet),
        section("Promessa del funnel", promise),
        section(
            "Offerta finale (cosa la sequenza deve portare a comprare/prenotare)",
            offer,
        ),
        section(
            "Context (offerta, target, tono, dettagli operativi)",
            context,
        ),
        section("Reference (esempi/strutture ispirazionali)", references),
        section("Istruzioni extra", extra_instructions),
        f"\n## Task\nScrivi una sequenza di {n_mails} mail di nurturing,\n"
        f"distribuite su circa {cadence_days} giorni (campi day 1..{n_mails}).\n"
        f"La sequenza deve avere un arco narrativo coerente: alternare ruoli\n"
        f"diversi (bonding, pain-agitation, mechanism, proof, anti-objection,\n"
        f"urgency-offer) per evitare ripetizioni di angle. Ultima mail con\n"
        f"role=urgency-offer e CTA forte verso l'offerta.\n",
    ]
    return "".join(p for p in parts if p)


def _build_user_prompt_single(
    *,
    context: str,
    references: str,
    target_audience: str,
    brand_voice: str,
    lead_magnet: str,
    promise: str,
    offer: str,
    sender: str,
    role: str,
    day: int,
    extra_instructions: str,
) -> str:
    role_section = (
        f"Ruolo richiesto per questa mail: **{role}**.\n"
        f"Giorno della sequenza: {day if day > 0 else 'non specificato'}."
    )
    parts = [
        section("Target audience", target_audience),
        section("Brand voice", brand_voice),
        section("Sender (firma)", sender),
        section("Lead magnet", lead_magnet),
        section("Promessa del funnel", promise),
        section("Offerta finale", offer),
        section("Context", context),
        section("Reference", references),
        section("Mail richiesta", role_section),
        section("Istruzioni extra", extra_instructions),
        "\n## Task\nScrivi UNA singola mail con il ruolo specificato sopra.\n",
    ]
    return "".join(p for p in parts if p)


def _call_claude(
    *, api_key: str, user_prompt: str, output_block: str
) -> list[dict]:
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        system=_BASE_SYSTEM_PROMPT + output_block,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    parsed = extract_json(text)
    if not isinstance(parsed, list):
        raise ValueError("Risposta Claude non e` un array JSON")
    return parsed


def write_sequence(
    *,
    api_key: str,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    promise: str = "",
    offer: str = "",
    sender: str = "",
    n_mails: int = 5,
    cadence_days: int = 7,
    extra_instructions: str = "",
) -> list[NurturingMail]:
    """Genera l'intera sequenza in un solo colpo, ordinata per day."""
    if not context.strip():
        raise ValueError("context e` obbligatorio")
    if n_mails < MIN_SEQUENCE or n_mails > MAX_SEQUENCE:
        raise ValueError(
            f"n_mails deve essere in [{MIN_SEQUENCE}, {MAX_SEQUENCE}]"
        )
    if cadence_days < 1:
        raise ValueError("cadence_days >= 1")

    user_prompt = _build_user_prompt_sequence(
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        offer=offer,
        sender=sender,
        n_mails=n_mails,
        cadence_days=cadence_days,
        extra_instructions=extra_instructions,
    )
    items = _call_claude(
        api_key=api_key,
        user_prompt=user_prompt,
        output_block=_SEQUENCE_OUTPUT_BLOCK,
    )
    mails = _parse_items(items)
    mails.sort(key=lambda m: m.day)
    return mails


def write_single(
    *,
    api_key: str,
    role: str,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    promise: str = "",
    offer: str = "",
    sender: str = "",
    day: int = 0,
    extra_instructions: str = "",
) -> NurturingMail:
    """Genera UNA singola mail di nurturing per il ruolo richiesto."""
    if not context.strip():
        raise ValueError("context e` obbligatorio")
    if not role.strip():
        raise ValueError("role e` obbligatorio per la modalita` single")

    user_prompt = _build_user_prompt_single(
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        offer=offer,
        sender=sender,
        role=role,
        day=day,
        extra_instructions=extra_instructions,
    )
    items = _call_claude(
        api_key=api_key,
        user_prompt=user_prompt,
        output_block=_SINGLE_OUTPUT_BLOCK,
    )
    mails = _parse_items(items)
    if not mails:
        raise ValueError("Generazione non ha prodotto risultati validi")
    return mails[0]


def regenerate_one(
    *,
    api_key: str,
    original: NurturingMail,
    feedback: str,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    promise: str = "",
    offer: str = "",
    sender: str = "",
) -> NurturingMail:
    if not feedback.strip():
        raise ValueError("feedback e` obbligatorio")

    original_block = (
        f"  DAY:       {original.day}\n"
        f"  ROLE:      {original.role}\n"
        f"  SUBJECT:   {original.subject}\n"
        f"  PREVIEW:   {original.preview}\n"
        f"  BODY:\n{original.body}\n"
        f"  SIGNATURE: {original.signature}\n"
        f"  CTA:       {original.cta}"
    )
    instructions = (
        "Stai riscrivendo UNA mail di una sequenza di nurturing. Originale:\n"
        f"{original_block}\n\n"
        f"Feedback dell'operatore:\n  {feedback.strip()}\n\n"
        "Restituisci un array JSON con UN SOLO elemento, mantenendo lo stesso\n"
        "`day` e `role` dell'originale (a meno che il feedback non chieda di\n"
        "cambiarli esplicitamente)."
    )
    user_prompt = _build_user_prompt_single(
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        offer=offer,
        sender=sender,
        role=original.role or "generic",
        day=original.day,
        extra_instructions=instructions,
    )
    items = _call_claude(
        api_key=api_key,
        user_prompt=user_prompt,
        output_block=_SINGLE_OUTPUT_BLOCK,
    )
    mails = _parse_items(items)
    if not mails:
        raise ValueError("Rigenerazione non ha prodotto risultati validi")
    return mails[0]
