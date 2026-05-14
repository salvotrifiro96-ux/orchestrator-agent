"""Mail di conferma post-iscrizione al funnel.

E` la mail che chi si iscrive riceve subito dopo aver lasciato l'email. Deve:
  - confermare che l'iscrizione e` andata a buon fine
  - consegnare cio` che e` stato promesso (link al PDF, video, calendario)
  - alzare l'aspettativa per cio` che arriva dopo (la sequenza di nurturing)
  - sopravvivere ai filtri Gmail (oggetto deliverable, niente spam triggers)

Output: 3-5 varianti, ognuna con subject + preview + body + signature.
"""
from __future__ import annotations

from dataclasses import dataclass

from anthropic import Anthropic

from .common import CLAUDE_MODEL, clean_str, extract_json, section

MIN_VARIANTS = 1
MAX_VARIANTS = 5


@dataclass(frozen=True)
class ConfirmationMail:
    """Mail di conferma iscrizione.

    Campi:
      - subject:    oggetto della mail (max ~50 char visibili in inbox)
      - preview:    preview text (max ~90 char, mostrato sotto al subject)
      - body:       corpo della mail in plain text (con newline)
      - signature:  chiusura firma (3-5 righe, brand + ps opzionale)
      - tone:       etichetta breve del tono usato (es. 'amichevole', 'urgent')
      - rationale:  perche` questa variante funziona (<=180 char)
    """

    subject: str
    preview: str
    body: str
    signature: str
    tone: str
    rationale: str


_SYSTEM_PROMPT = (
    "Sei un email copywriter senior specializzato in funnel di acquisizione.\n"
    "Scrivi mail di CONFERMA che chi si iscrive a un lead magnet (PDF, webinar,\n"
    "quiz, video, call) riceve subito dopo aver lasciato l'indirizzo email.\n"
    "Italiano nativo, tono diretto, mai \"egregio\" o \"gentile\".\n\n"
    "## OBIETTIVI DELLA MAIL (in ordine)\n"
    "  1. CONFERMA: rassicura che l'iscrizione e` andata a buon fine.\n"
    "  2. CONSEGNA: link/istruzioni per accedere al lead magnet promesso.\n"
    "     Mai nascondere il link, mai bloccarlo dietro a richieste assurde.\n"
    "  3. ASPETTATIVA: anticipa cosa arrivera` nei prossimi giorni\n"
    "     (la sequenza di nurturing). Una sola riga, no spoiler completo.\n"
    "  4. PROSSIMA AZIONE: dove possibile, una micro-azione subito\n"
    "     (es. 'aggiungi questo indirizzo ai contatti', 'rispondi con la\n"
    "     domanda numero 1', 'salva il calendario'). Aumenta engagement.\n\n"
    "## STRUTTURA OBBLIGATORIA\n"
    "  - SUBJECT: max ~50 char visibili in inbox. Deve far aprire SENZA\n"
    "    promesse mendaci. Evita maiuscolo selvaggio, emoji a inizio (Gmail\n"
    "    le promuove poco), parole spam (GRATIS, URGENTE, !!!).\n"
    "    Pattern utili: 'Ecco il tuo [X]', 'Pronto: [X] e` dentro', '[X]:\n"
    "    leggi prima questo', 'Conferma + 3 secondi di lettura'.\n"
    "  - PREVIEW: max ~90 char. Estende il subject, NON lo ripete.\n"
    "  - BODY: 80-180 parole. Apertura senza filler ('Ciao [Nome], ecco...').\n"
    "    Frasi corte. UN solo link per il lead magnet (chiaro, ripetuto max 2x).\n"
    "    Nessuno 'lorem' di marketing aziendale. Niente formattazione HTML\n"
    "    pesante: questo e` plain text, una eventuale newsletter la rende.\n"
    "    Placeholder ammessi: [Nome] per il merge tag, [LINK] per il link\n"
    "    al lead magnet. Lasciali tra parentesi quadre, l'operatore li\n"
    "    sostituira` nell'email tool.\n"
    "  - SIGNATURE: 3-5 righe. Nome del sender, ruolo, brand. Eventuale PS\n"
    "    con la micro-azione del punto 4.\n\n"
    "## VIETATO\n"
    "  - asterischi/maiuscolo per enfasi (mark deliverability)\n"
    "  - punti esclamativi multipli, ALL CAPS\n"
    "  - 'click here', 'cliccare qui' come anchor — usa 'leggi il PDF',\n"
    "    'guarda il video', 'apri il quiz'\n"
    "  - promesse non sostenute dal context (numeri inventati)\n"
    "  - chiusure formali ('Cordiali saluti', 'In attesa di un riscontro')\n\n"
    "## OBBLIGATORIO\n"
    "  - tu/tuo, mai voi/lei\n"
    "  - 1 sola CTA principale (il link al lead magnet)\n"
    "  - tono coerente con il brand_voice del context\n"
    "  - varieta`: ogni variante usa un tono o un'apertura diversi\n\n"
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON, niente prosa, niente markdown fences.\n"
    "Schema di ogni elemento:\n"
    '  {"subject":   "stringa non vuota, ~50 char",\n'
    '   "preview":   "stringa non vuota, ~90 char",\n'
    '   "body":      "stringa, 80-180 parole, con newline",\n'
    '   "signature": "stringa, 3-5 righe",\n'
    '   "tone":      "etichetta breve es. amichevole | urgent | autorita`",\n'
    '   "rationale": "max 180 char, perche` apre + clicca"}\n'
)


def _parse_items(items: list[dict]) -> list[ConfirmationMail]:
    out: list[ConfirmationMail] = []
    for it in items:
        subject = clean_str(it.get("subject"))
        body = clean_str(it.get("body"))
        if not subject or not body:
            continue
        out.append(
            ConfirmationMail(
                subject=subject,
                preview=clean_str(it.get("preview")),
                body=body,
                signature=clean_str(it.get("signature")),
                tone=clean_str(it.get("tone")),
                rationale=clean_str(it.get("rationale")),
            )
        )
    return out


def _build_user_prompt(
    *,
    context: str,
    references: str,
    target_audience: str,
    brand_voice: str,
    lead_magnet: str,
    promise: str,
    sender: str,
    n_variants: int,
    extra_instructions: str,
) -> str:
    parts = [
        section("Target audience", target_audience),
        section("Brand voice", brand_voice),
        section(
            "Sender (chi firma la mail: nome + ruolo + brand)",
            sender,
        ),
        section(
            "Lead magnet (cosa hanno appena richiesto: PDF, webinar, quiz...)",
            lead_magnet,
        ),
        section(
            "Promessa del funnel (cosa hanno visto nella landing prima di iscriversi)",
            promise,
        ),
        section(
            "Context (offerta, target, tono, dettagli del prodotto/servizio)",
            context,
        ),
        section(
            "Reference (esempi/strutture ispirazionali per la mail)",
            references,
        ),
        section("Istruzioni extra", extra_instructions),
        f"\n## Task\nScrivi {n_variants} varianti di mail di conferma. "
        f"Ogni variante ha un tono o angle diverso. Mantieni i placeholder "
        f"[Nome] e [LINK] dove servono. Restituisci solo l'array JSON.\n",
    ]
    return "".join(p for p in parts if p)


def _call_claude(*, api_key: str, user_prompt: str) -> list[dict]:
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    parsed = extract_json(text)
    if not isinstance(parsed, list):
        raise ValueError("Risposta Claude non e` un array JSON")
    return parsed


def write_confirmation_mails(
    *,
    api_key: str,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    promise: str = "",
    sender: str = "",
    n_variants: int = 3,
    extra_instructions: str = "",
) -> list[ConfirmationMail]:
    if not context.strip():
        raise ValueError("context e` obbligatorio")
    if n_variants < MIN_VARIANTS or n_variants > MAX_VARIANTS:
        raise ValueError(
            f"n_variants deve essere in [{MIN_VARIANTS}, {MAX_VARIANTS}]"
        )

    user_prompt = _build_user_prompt(
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        sender=sender,
        n_variants=n_variants,
        extra_instructions=extra_instructions,
    )
    items = _call_claude(api_key=api_key, user_prompt=user_prompt)
    return _parse_items(items)


def regenerate_one(
    *,
    api_key: str,
    original: ConfirmationMail,
    feedback: str,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    lead_magnet: str = "",
    promise: str = "",
    sender: str = "",
) -> ConfirmationMail:
    if not feedback.strip():
        raise ValueError("feedback e` obbligatorio per rigenerare")

    original_block = (
        f"  SUBJECT:   {original.subject}\n"
        f"  PREVIEW:   {original.preview}\n"
        f"  BODY:\n{original.body}\n"
        f"  SIGNATURE: {original.signature}\n"
        f"  TONE:      {original.tone}"
    )
    instructions = (
        "Stai riscrivendo UNA singola mail di conferma. Versione originale:\n"
        f"{original_block}\n\n"
        f"Feedback dell'operatore:\n  {feedback.strip()}\n\n"
        "Restituisci un array JSON con UN SOLO elemento."
    )
    user_prompt = _build_user_prompt(
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        lead_magnet=lead_magnet,
        promise=promise,
        sender=sender,
        n_variants=1,
        extra_instructions=instructions,
    )
    items = _call_claude(api_key=api_key, user_prompt=user_prompt)
    mails = _parse_items(items)
    if not mails:
        raise ValueError("Rigenerazione non ha prodotto risultati validi")
    return mails[0]
