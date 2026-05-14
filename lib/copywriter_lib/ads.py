"""Ads copy generation per i 4 canali Leone: Meta, Google Search, TikTok/Reels,
LinkedIn.

Ogni canale ha vincoli/struttura specifici, ma il pattern e` lo stesso:
- system prompt specializzato
- output JSON array
- parsing in dataclass tipizzata
- funzione `regenerate_one` per rifare una variante con feedback operatore.

Channel = "meta" | "google" | "tiktok" | "linkedin".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Union

from anthropic import Anthropic

from .common import (
    CLAUDE_MODEL,
    clean_list,
    clean_str,
    extract_json,
    section,
)

Channel = Literal["meta", "google", "tiktok", "linkedin"]

MIN_VARIANTS = 3
MAX_VARIANTS = 10


# ── Dataclass per canale ───────────────────────────────────────────


@dataclass(frozen=True)
class MetaAd:
    """Meta Ads (Facebook + Instagram feed/reel).

    Limiti UI di Meta (approssimati, possono cambiare):
      - primary_text: ~125 char visibili senza "Altro"
      - headline:     ~40 char
      - description:  ~30 char (mostrato solo in alcuni placement)
    """

    primary_text: str
    headline: str
    description: str
    cta: str
    angle: str
    rationale: str


@dataclass(frozen=True)
class GoogleAd:
    """Google Search RSA — Responsive Search Ad.

    Limiti Google Ads:
      - headlines: ognuna max 30 char, fino a 15 totali
      - descriptions: ognuna max 90 char, fino a 4 totali
      - paths: 2 segmenti, max 15 char ognuno
    """

    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    paths: tuple[str, ...]
    angle: str
    rationale: str


@dataclass(frozen=True)
class TikTokAd:
    """TikTok / Instagram Reels script.

    Output e` lo script per il creator: hook nei primi 3 secondi (l'unica
    cosa che decide se si scrolla via), body con problema/soluzione/proof,
    CTA verbale e caption con hashtag.
    """

    hook: str
    body: str
    cta_verbal: str
    caption: str
    hashtags: tuple[str, ...]
    angle: str
    rationale: str


@dataclass(frozen=True)
class LinkedInAd:
    """LinkedIn Sponsored Content.

    Tono piu` professionale e B2B. Headline puo` essere lunga (~150 char)
    ma le prime 2 righe del body sono cio` che si vede senza "Altro".
    """

    headline: str
    body: str
    cta: str
    angle: str
    rationale: str


Ad = Union[MetaAd, GoogleAd, TikTokAd, LinkedInAd]


# ── System prompts (uno per canale) ────────────────────────────────


_META_PROMPT = (
    "Sei un performance copywriter senior di Meta Ads. Scrivi annunci per "
    "Facebook + Instagram (feed e reel). Italiano nativo, tono diretto, mai "
    "anglicismi superflui.\n\n"
    "## STRUTTURA OBBLIGATORIA\n"
    "Ogni variante ha:\n"
    "  - PRIMARY TEXT: ~150-250 char totali, ma i PRIMI ~125 char devono\n"
    "    funzionare da soli (Meta tronca con 'Altro...'). Apri con un hook\n"
    "    forte: domanda diretta, pattern interrupt, dato contro-intuitivo,\n"
    "    pain literale del target. NO emoji decorative inutili, max 1-2 se\n"
    "    aiutano la lettura.\n"
    "  - HEADLINE: max 40 char. Promessa nuda o curiosita`. Non ripete il\n"
    "    primary text.\n"
    "  - DESCRIPTION: max 30 char. Rinforzo o anti-obiezione corta.\n"
    "  - CTA: scegli da {Iscriviti, Scopri di piu`, Prenota ora, Scarica,\n"
    "    Contattaci, Registrati, Invia un messaggio}. Niente CTA inventate.\n\n"
    "## ANGLE (obbligatorio)\n"
    "Ogni variante usa un angle diverso: pain-focus, dream-outcome,\n"
    "anti-obiezione, social proof, scarcity, autorita`, contrarian, before/after,\n"
    "domanda diretta, storytelling 1-frase. NON ripetere lo stesso angle.\n\n"
    "## VIETATO\n"
    "  - claim non quantificabili ('cambiamo la vita', 'il migliore')\n"
    "  - promesse non sostenibili dal context\n"
    "  - clickbait vuoto ('non crederai a cosa e` successo dopo')\n"
    "  - emoji a pioggia\n"
    "  - call to action diverse dalle CTA disponibili in Meta\n\n"
    "## OBBLIGATORIO\n"
    "  - Tu/tuo, mai voi/lei\n"
    "  - Numeri dal context quando ci sono\n"
    "  - Una sola idea per annuncio (non sommare benefici)\n"
    "  - Verbo all'inizio quando possibile\n\n"
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON, niente prosa, niente markdown fences.\n"
    "Schema di ogni elemento:\n"
    '  {"primary_text": "stringa non vuota",\n'
    '   "headline":     "stringa non vuota, max 40 char",\n'
    '   "description":  "stringa, puo` essere vuota, max 30 char",\n'
    '   "cta":          "una delle CTA elencate",\n'
    '   "angle":        "etichetta breve dell\'angle usato",\n'
    '   "rationale":    "max 180 char, perche` funziona su questo target"}\n'
)


_GOOGLE_PROMPT = (
    "Sei un performance copywriter senior di Google Ads. Scrivi RSA "
    "(Responsive Search Ads) per query commerciali ad alto intento.\n"
    "Italiano nativo, tono diretto.\n\n"
    "## STRUTTURA OBBLIGATORIA per ogni VARIANTE\n"
    "Ogni variante e` un set completo RSA, composto da:\n"
    "  - HEADLINES: 12-15 stringhe diverse, OGNUNA max 30 caratteri.\n"
    "    Devono coprire angle eterogenei: keyword esatta, benefit principale,\n"
    "    USP, social proof, urgenza/scadenza, prezzo/sconto se sostenibile,\n"
    "    anti-obiezione, CTA, brand. Almeno 3 contengono la KEYWORD del\n"
    "    context (Google rewardsa headline che matchano la query).\n"
    "  - DESCRIPTIONS: 3-4 stringhe, OGNUNA max 90 caratteri.\n"
    "    Espandono i top benefit, includono CTA esplicita.\n"
    "  - PATHS: 2 stringhe da max 15 char (mostrate dopo il dominio).\n"
    "    Devono essere parole-chiave SEO leggibili, non slug random.\n\n"
    "## REGOLA FERREA SULLA LUNGHEZZA\n"
    "Conta i caratteri SCRUPOLOSAMENTE. Google scarta gli asset oltre il limite.\n"
    "Se una headline supera 30 char la accorci. Se non puoi accorciarla\n"
    "mantenendo il senso, scrivine una diversa.\n\n"
    "## VIETATO\n"
    "  - capitalizzazione random, ALL CAPS interi, eccesso di punteggiatura\n"
    "  - claim non sostenuti dal context\n"
    "  - asset duplicati o quasi-duplicati nella stessa variante\n"
    "  - paths con underscore, numeri random, caratteri speciali\n\n"
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON, niente prosa, niente markdown fences.\n"
    "Schema di ogni elemento (= 1 RSA completo):\n"
    '  {"headlines":    ["str <=30 char", ...],   // 12-15 elementi\n'
    '   "descriptions": ["str <=90 char", ...],   // 3-4 elementi\n'
    '   "paths":        ["str <=15 char", "str <=15 char"],  // esattamente 2\n'
    '   "angle":        "etichetta breve dell\'angle dominante",\n'
    '   "rationale":    "max 180 char, perche` questo set RSA performa"}\n'
)


_TIKTOK_PROMPT = (
    "Sei un creative strategist senior di TikTok/Reels paid. Scrivi script\n"
    "per video short (15-30s) studiati per fermare lo scroll.\n"
    "Italiano nativo, parlato, come uno che parla in camera. Niente didascalia\n"
    "da brand TV.\n\n"
    "## STRUTTURA OBBLIGATORIA\n"
    "Ogni variante e` uno script con:\n"
    "  - HOOK: i PRIMI 3 SECONDI. Una sola frase parlata. Deve essere o:\n"
    "    pattern interrupt (es. 'Ho perso 12.000€ prima di capirlo'),\n"
    "    domanda diretta al target ('Stai ancora vendendo a chiamata fredda?'),\n"
    "    contrarian ('Smettetela di chiedere referenze'),\n"
    "    o promessa concreta ('Ti mostro come riempire l\'agenda in 30 giorni').\n"
    "    Max 12 parole. Se serve, indica tra parentesi un'azione visiva\n"
    "    (es. '[apre laptop e fa vedere screen]').\n"
    "  - BODY: lo script parlato per i 12-25 secondi successivi.\n"
    "    Struttura suggerita: problema (1 frase) -> soluzione (1-2 frasi) ->\n"
    "    dimostrazione/proof (1 frase) -> next step. Frasi corte, contesto\n"
    "    'tu', niente liste teoriche, esempi concreti.\n"
    "  - CTA VERBAL: la frase finale parlata che spinge all'azione.\n"
    "    Es. 'Clicca il link in bio e prenota una call gratis.'\n"
    "  - CAPTION: il testo del post sotto al video. Max 150 char visibili\n"
    "    + hashtag a parte. La caption RIPRENDE l\'hook con parole diverse,\n"
    "    non lo copia.\n"
    "  - HASHTAGS: 5-10 hashtag pertinenti, mix di hashtag larghi (audience\n"
    "    grande), medi (niche-target) e brandati. Senza # nel JSON: solo\n"
    "    la parola.\n\n"
    "## ANGLE\n"
    "Ogni variante usa un angle diverso (storytelling 1ma persona, demo,\n"
    "POV, contrarian, before/after, list-style 'le 3 cose', anti-obiezione).\n\n"
    "## VIETATO\n"
    "  - frasi da brand corporate ('Scopri la nostra soluzione innovativa')\n"
    "  - hook fluff ('Ciao a tutti, oggi voglio parlarvi di...')\n"
    "  - emoji a pioggia, frasi tutte maiuscole\n"
    "  - claim non sostenuti dal context\n\n"
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON, niente prosa, niente markdown fences.\n"
    "Schema di ogni elemento:\n"
    '  {"hook":       "stringa, max 12 parole",\n'
    '   "body":       "script parlato, 3-6 frasi",\n'
    '   "cta_verbal": "frase finale di chiusura",\n'
    '   "caption":    "stringa <=150 char",\n'
    '   "hashtags":   ["hashtag1", "hashtag2", ...],  // 5-10, senza #\n'
    '   "angle":      "etichetta breve dell\'angle",\n'
    '   "rationale":  "max 180 char"}\n'
)


_LINKEDIN_PROMPT = (
    "Sei un B2B copywriter senior di LinkedIn Ads. Scrivi Sponsored Content\n"
    "per professionisti, decisori e imprenditori. Tono autorevole ma diretto,\n"
    "italiano nativo, niente acronimi non spiegati.\n\n"
    "## STRUTTURA OBBLIGATORIA\n"
    "Ogni variante ha:\n"
    "  - HEADLINE: max 150 char. NON click-bait. Deve qualificare il target\n"
    "    (es. 'Per fondatori B2B che gestiscono >5 venditori') e accennare\n"
    "    al benefit. LinkedIn premia chi dichiara subito a chi parla.\n"
    "  - BODY: ~500-700 char totali, ma i PRIMI ~140 char devono funzionare\n"
    "    da soli (LinkedIn tronca con 'Altro...'). Struttura suggerita:\n"
    "    hook (1 frase) -> contesto/dato (1 frase) -> meccanismo (1-2 frasi)\n"
    "    -> proof (1 frase) -> CTA (1 frase). Frasi separate da newline,\n"
    "    leggibile su mobile.\n"
    "  - CTA: scegli da {Per saperne di piu`, Iscriviti, Registrati,\n"
    "    Richiedi una demo, Scarica, Visualizza}. Niente CTA inventate.\n\n"
    "## ANGLE\n"
    "Varianti su angle diversi: case study 1-frase, dato di settore\n"
    "contro-intuitivo, autorita` di metodo, anti-obiezione di costo,\n"
    "scarcity di slot/data, contrarian rispetto alla narrativa LinkedIn.\n\n"
    "## VIETATO\n"
    "  - tono \"motivational poster\" ('Insieme possiamo...')\n"
    "  - buzzword vuote (synergy, paradigma, eccellenza, innovazione)\n"
    "  - emoji a pioggia (max 1 se aiuta scansione)\n"
    "  - prima persona plurale 'noi' senza un soggetto chiaro\n"
    "  - hashtag-spam: max 2-3 hashtag nel body, fine annuncio\n\n"
    "## OUTPUT\n"
    "Rispondi SOLO con un array JSON, niente prosa, niente markdown fences.\n"
    "Schema di ogni elemento:\n"
    '  {"headline":  "stringa, max 150 char",\n'
    '   "body":      "stringa, ~500-700 char totali",\n'
    '   "cta":       "una delle CTA elencate",\n'
    '   "angle":     "etichetta breve dell\'angle",\n'
    '   "rationale": "max 180 char"}\n'
)


_SYSTEM_PROMPTS: dict[Channel, str] = {
    "meta": _META_PROMPT,
    "google": _GOOGLE_PROMPT,
    "tiktok": _TIKTOK_PROMPT,
    "linkedin": _LINKEDIN_PROMPT,
}


# ── Parsers (uno per canale) ───────────────────────────────────────


def _parse_meta(items: list[dict]) -> list[MetaAd]:
    out: list[MetaAd] = []
    for it in items:
        primary = clean_str(it.get("primary_text"))
        headline = clean_str(it.get("headline"))
        cta = clean_str(it.get("cta"))
        if not primary or not headline or not cta:
            continue
        out.append(
            MetaAd(
                primary_text=primary,
                headline=headline,
                description=clean_str(it.get("description")),
                cta=cta,
                angle=clean_str(it.get("angle")),
                rationale=clean_str(it.get("rationale")),
            )
        )
    return out


def _parse_google(items: list[dict]) -> list[GoogleAd]:
    out: list[GoogleAd] = []
    for it in items:
        headlines = clean_list(it.get("headlines"))
        descriptions = clean_list(it.get("descriptions"))
        paths = clean_list(it.get("paths"))
        if not headlines or not descriptions:
            continue
        # paths e` opzionale ma sempre 2 se presente
        if paths and len(paths) > 2:
            paths = paths[:2]
        out.append(
            GoogleAd(
                headlines=headlines,
                descriptions=descriptions,
                paths=paths,
                angle=clean_str(it.get("angle")),
                rationale=clean_str(it.get("rationale")),
            )
        )
    return out


def _parse_tiktok(items: list[dict]) -> list[TikTokAd]:
    out: list[TikTokAd] = []
    for it in items:
        hook = clean_str(it.get("hook"))
        body = clean_str(it.get("body"))
        if not hook or not body:
            continue
        out.append(
            TikTokAd(
                hook=hook,
                body=body,
                cta_verbal=clean_str(it.get("cta_verbal")),
                caption=clean_str(it.get("caption")),
                hashtags=clean_list(it.get("hashtags")),
                angle=clean_str(it.get("angle")),
                rationale=clean_str(it.get("rationale")),
            )
        )
    return out


def _parse_linkedin(items: list[dict]) -> list[LinkedInAd]:
    out: list[LinkedInAd] = []
    for it in items:
        headline = clean_str(it.get("headline"))
        body = clean_str(it.get("body"))
        cta = clean_str(it.get("cta"))
        if not headline or not body or not cta:
            continue
        out.append(
            LinkedInAd(
                headline=headline,
                body=body,
                cta=cta,
                angle=clean_str(it.get("angle")),
                rationale=clean_str(it.get("rationale")),
            )
        )
    return out


_PARSERS: dict[Channel, Callable[[list[dict]], list[Ad]]] = {
    "meta": _parse_meta,
    "google": _parse_google,
    "tiktok": _parse_tiktok,
    "linkedin": _parse_linkedin,
}


# ── Prompt building + Claude call ──────────────────────────────────


def _build_user_prompt(
    *,
    channel: Channel,
    context: str,
    references: str,
    target_audience: str,
    brand_voice: str,
    promise: str,
    n_variants: int,
    extra_instructions: str,
) -> str:
    parts: list[str] = [
        section("Target audience", target_audience),
        section("Brand voice", brand_voice),
        section(
            "Promessa scelta (USP / headline a cui ancorare le copy)",
            promise,
        ),
        section(
            "Context (offerta, dream outcome, pain, meccanismo, prove, vincoli)",
            context,
        ),
        section(
            "Reference (esempi/strutture che il copywriter deve usare come ispirazione)",
            references,
        ),
        section("Istruzioni extra", extra_instructions),
        f"\n## Task\nScrivi esattamente {n_variants} varianti di annuncio "
        f"per il canale {channel.upper()}. Ogni variante deve usare un angle "
        f"diverso o un'apertura strutturale diversa. Restituisci solo "
        f"l'array JSON.\n",
    ]
    return "".join(p for p in parts if p)


def _call_claude(*, api_key: str, channel: Channel, user_prompt: str) -> list[dict]:
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=_SYSTEM_PROMPTS[channel],
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    parsed = extract_json(text)
    if not isinstance(parsed, list):
        raise ValueError("Risposta Claude non e` un array JSON")
    return parsed


def write_ads(
    *,
    api_key: str,
    channel: Channel,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    promise: str = "",
    n_variants: int = 5,
    extra_instructions: str = "",
) -> list[Ad]:
    """Genera `n_variants` copy ads per il canale richiesto.

    Args:
        channel: uno di meta | google | tiktok | linkedin
        context: blob libero con offerta, target, pain, dream, proof
        references: esempi/pattern strutturali (opzionale)
        promise: headline/USP gia` scelta dalla fase precedente (opzionale)
        n_variants: bounded [MIN_VARIANTS, MAX_VARIANTS]

    Returns:
        Lista di Ad tipizzati in base al canale.
    """
    if channel not in _SYSTEM_PROMPTS:
        raise ValueError(f"channel deve essere uno di {list(_SYSTEM_PROMPTS)}")
    if not context.strip():
        raise ValueError("context e` obbligatorio")
    if n_variants < MIN_VARIANTS or n_variants > MAX_VARIANTS:
        raise ValueError(
            f"n_variants deve essere in [{MIN_VARIANTS}, {MAX_VARIANTS}], "
            f"ricevuto {n_variants}"
        )

    user_prompt = _build_user_prompt(
        channel=channel,
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        promise=promise,
        n_variants=n_variants,
        extra_instructions=extra_instructions,
    )
    items = _call_claude(api_key=api_key, channel=channel, user_prompt=user_prompt)
    return _PARSERS[channel](items)


def _render_original_block(original: Ad) -> str:
    """Renderizza l'ad originale come blocco testuale per il feedback prompt."""
    if isinstance(original, MetaAd):
        return (
            f"  PRIMARY: {original.primary_text}\n"
            f"  HEADLINE: {original.headline}\n"
            f"  DESCRIPTION: {original.description}\n"
            f"  CTA: {original.cta}\n"
            f"  ANGLE: {original.angle}"
        )
    if isinstance(original, GoogleAd):
        h = " | ".join(original.headlines)
        d = " | ".join(original.descriptions)
        p = " / ".join(original.paths) if original.paths else "—"
        return (
            f"  HEADLINES: {h}\n"
            f"  DESCRIPTIONS: {d}\n"
            f"  PATHS: {p}\n"
            f"  ANGLE: {original.angle}"
        )
    if isinstance(original, TikTokAd):
        return (
            f"  HOOK: {original.hook}\n"
            f"  BODY: {original.body}\n"
            f"  CTA: {original.cta_verbal}\n"
            f"  CAPTION: {original.caption}\n"
            f"  ANGLE: {original.angle}"
        )
    if isinstance(original, LinkedInAd):
        return (
            f"  HEADLINE: {original.headline}\n"
            f"  BODY: {original.body}\n"
            f"  CTA: {original.cta}\n"
            f"  ANGLE: {original.angle}"
        )
    raise TypeError(f"Tipo ad non riconosciuto: {type(original)}")


def regenerate_one(
    *,
    api_key: str,
    channel: Channel,
    original: Ad,
    feedback: str,
    context: str,
    references: str = "",
    target_audience: str = "",
    brand_voice: str = "",
    promise: str = "",
) -> Ad:
    """Rigenera UNA singola variante con feedback dell'operatore."""
    if not feedback.strip():
        raise ValueError("feedback e` obbligatorio per rigenerare")

    instructions = (
        "Stai riscrivendo UNA singola variante ad. Versione originale:\n"
        f"{_render_original_block(original)}\n\n"
        f"Feedback dell'operatore:\n  {feedback.strip()}\n\n"
        "Restituisci un array JSON con UN SOLO elemento (la nuova variante)."
    )

    user_prompt = _build_user_prompt(
        channel=channel,
        context=context,
        references=references,
        target_audience=target_audience,
        brand_voice=brand_voice,
        promise=promise,
        n_variants=1,
        extra_instructions=instructions,
    )
    items = _call_claude(api_key=api_key, channel=channel, user_prompt=user_prompt)
    ads = _PARSERS[channel](items)
    if not ads:
        raise ValueError("Rigenerazione non ha prodotto risultati validi")
    return ads[0]
