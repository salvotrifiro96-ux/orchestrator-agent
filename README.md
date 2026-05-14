# Orchestrator Agent — Leone Master School

**PM virtuale** del team Marketing AI di Leone. Streamlit chat che coordina tutti gli altri agenti via **Claude tool-use loop**.

Deploy: `orchestrator-agent.streamlit.app` (in setup)
Password: `faraone.92` (env `APP_PASSWORD`)

## Cosa fa
L'operatore scrive in chat una direttiva (es. _"analizza la campagna 22 nicchie e dammi raccomandazioni"_) e l'orchestratore:
1. Capisce cosa serve
2. Delega ai tool right giusti (uno per ciascun agente specializzato)
3. Riporta risultati strutturati + raccomandazioni
4. Chiede conferma esplicita prima di azioni costose (lanci ads, modifiche HubSpot)

## Stack
- **Streamlit** chat UI (`st.chat_message` + `st.chat_input`)
- **Anthropic SDK** con `tools` parameter — loop tool_use → tool_result fino a `stop_reason="end_turn"`
- **Claude Sonnet 4.6** come decisionale (configurabile via env `CLAUDE_MODEL`)
- Logica degli agenti **importata da `lib/`** (snapshot dei moduli core dei vari repo)

## Tool registrati (V1)

| Tool | Agente | Cosa fa |
|---|---|---|
| `list_promise_briefs` | promise-writer | Lista archivio brief Supabase |
| `get_promise_brief` | promise-writer | Recupera un brief per id |
| `generate_promises` | promise-writer | Genera N promesse Hormozi e salva in archivio |
| `write_ad_copy` | copywriter | Copy ads per meta/google/tiktok/linkedin |
| `write_email_confirmation` | copywriter | Mail conferma iscrizione |
| `write_nurturing_sequence` | copywriter | Sequenza nurturing N mail con cadenza |
| `list_meta_campaigns` | data-analyst | Tutte le campagne ACTIVE+PAUSED<30gg sui 6 account |
| `analyze_campaign` | data-analyst | Perf+lead+funnel+ROAS+breakdown+delta |
| `make_visual_brief` | graphic-designer *(stub V1)* | Brief immagine strutturato |
| `propose_ad_launch` | media-buyer *(stub V1)* | Proposta di lancio campagna (HITL) |

## Setup locale

```bash
cd /Users/salvotrifiro/leone-agents/orchestrator-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env  # compila i valori
.venv/bin/streamlit run app.py
```

## Deploy Streamlit Cloud
1. Push su GitHub (gia` fatto)
2. share.streamlit.io → New app → repo `salvotrifiro96-ux/orchestrator-agent`
3. Branch `main` / file `app.py` / custom subdomain `orchestrator-agent`
4. Secrets TOML: usa i valori sparsi negli altri repo (media-buyer/.env + meta-ads-analyzer/.env)

## Architettura cartelle

```
orchestrator-agent/
├── app.py                       # Streamlit chat UI
├── agent/
│   ├── orchestrator.py          # Claude tool-use loop
│   └── tools_registry.py        # Aggrega schemi + dispatch
├── tools/                       # Adapter Claude tool → lib functions
│   ├── promise.py
│   ├── copy.py
│   ├── analyze.py
│   └── visual_and_launch.py
├── lib/                         # Snapshot dei moduli core degli altri agenti
│   ├── brief_store.py           # da promise-writer-agent
│   ├── promise_writer.py
│   ├── meta_api.py              # da data-analyst-agent
│   ├── hubspot_api.py
│   ├── db.py
│   ├── da_config.py
│   ├── da_recommendations.py
│   ├── accounts.py
│   └── copywriter_lib/          # da copywriter-agent (sub-pacchetto)
│       ├── ads.py
│       ├── confirmation.py
│       ├── nurturing.py
│       └── common.py
└── data/campaigns_config.json   # mapping campagna → form HubSpot
```

## Estensione futura (V2)
- HITL via bottoni Approva/Annulla (oggi solo testuale)
- Tool `launch_ad_real` con vero call Meta API
- Tool `generate_visual_real` con gpt-image-1
- Tool `publish_landing_page` (riusa funnel-landing-agent)
- Tool `setup_hubspot_workflow` (riusa automation-specialist-agent)
- Persistenza sessioni chat su Supabase (tabella `orchestrator_sessions`)
