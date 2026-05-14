"""Orchestrator Agent — piattaforma marketing AI Leone.

Flow:
  HOME (lista progetti + New)
    ↓ New Project
  DISCOVERY (chat con orchestratore per costruire contesto)
    ↓ Approva contesto
  DASHBOARD (8 agenti con stato + click per entrare)
    ↓ click agente
  AGENT (form input + genera + output + approva → torna a dashboard)
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from agent.orchestrator import CONTEXT_FIELDS, run_discovery_turn
from agent.projects import (
    AGENT_DEFS,
    AGENT_DEFS_BY_SLUG,
    AgentDef,
    Project,
    ProjectAgent,
    ProjectStore,
)


load_dotenv()


def _secret(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, AttributeError):
        return default


APP_PASSWORD = _secret("APP_PASSWORD")
ANTHROPIC_KEY = _secret("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _secret("CLAUDE_MODEL", "claude-sonnet-4-6")

st.set_page_config(page_title="Orchestrator Agent", layout="wide", page_icon="🎯")


def _password_gate() -> None:
    if not APP_PASSWORD:
        return
    if st.session_state.get("authed"):
        return
    st.title("🎯 Orchestrator Agent")
    pw = st.text_input("Password", type="password", key="pw_input")
    if st.button("Entra"):
        if pw == APP_PASSWORD:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Password errata")
    st.stop()


_password_gate()


# ── Routing state ─────────────────────────────────────────────────
if "view" not in st.session_state:
    st.session_state.view = "home"  # home | discovery | dashboard | agent
if "project_id" not in st.session_state:
    st.session_state.project_id = None
if "agent_slug" not in st.session_state:
    st.session_state.agent_slug = None
if "discovery_messages" not in st.session_state:
    st.session_state.discovery_messages = []
if "proposed_context" not in st.session_state:
    st.session_state.proposed_context = None


def _store() -> ProjectStore | None:
    if "_project_store" not in st.session_state:
        try:
            st.session_state._project_store = ProjectStore.from_env()
        except Exception:
            st.session_state._project_store = None
    return st.session_state._project_store


def _go(view: str, **kwargs) -> None:
    st.session_state.view = view
    for k, v in kwargs.items():
        st.session_state[k] = v
    st.rerun()


# ── STATUS helpers ─────────────────────────────────────────────────
STATUS_LABELS = {
    "received": ("📨 Contesto ricevuto", "#64748b"),
    "waiting_input": ("⏳ Attendo info", "#f59e0b"),
    "work_in_progress": ("🔧 In lavorazione", "#3b82f6"),
    "pending_approval": ("🧐 Da approvare", "#a855f7"),
    "completed": ("✅ Completato", "#16a34a"),
}


def _status_badge(status: str) -> str:
    label, color = STATUS_LABELS.get(status, (status, "#64748b"))
    return (
        f"<span style='background:{color}; color:white; padding:3px 10px; "
        f"border-radius:12px; font-size:0.8rem; font-weight:600;'>{label}</span>"
    )


# ── HOME view: list projects + new ─────────────────────────────────
def render_home() -> None:
    st.title("🎯 Orchestrator")
    st.caption("Piattaforma di lavoro del team Marketing AI di Leone Master School.")

    store = _store()
    if not store:
        st.error("Supabase non configurato (`SUPABASE_URL` / `SUPABASE_SECRET_KEY`).")
        return

    col_new, col_spacer = st.columns([1, 3])
    if col_new.button("➕ **New Project**", type="primary", use_container_width=True):
        st.session_state.discovery_messages = []
        st.session_state.proposed_context = None
        try:
            new_p = store.create_project(name=f"Progetto {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            _go("discovery", project_id=new_p.id)
        except Exception as e:
            st.error(f"Creazione progetto fallita: {e}")

    st.divider()

    st.subheader("📂 Progetti")
    try:
        projects = store.list_projects(limit=50)
    except Exception as e:
        st.error(f"Errore lettura progetti: {e}")
        return
    if not projects:
        st.info("Nessun progetto ancora. Clicca **New Project** per iniziare.")
        return

    for p in projects:
        with st.container(border=True):
            cols = st.columns([4, 2, 1, 1])
            cols[0].markdown(f"**{p.name}**")
            cols[0].caption(
                f"`{p.id[:8]}…` · status: `{p.status}` · "
                f"agg. {p.updated_at[:16].replace('T', ' ')}"
            )
            cols[1].caption(
                f"Contesto: {'✅' if p.context else '—'}"
            )
            if cols[2].button("Apri →", key=f"open_{p.id}"):
                if p.status == "discovery":
                    st.session_state.discovery_messages = p.discovery_messages or []
                    _go("discovery", project_id=p.id)
                else:
                    _go("dashboard", project_id=p.id)
            if cols[3].button("🗑️", key=f"del_{p.id}", help="Elimina"):
                try:
                    store.delete_project(p.id)
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete: {e}")


# ── DISCOVERY view: chat per costruire contesto ────────────────────
def render_discovery() -> None:
    store = _store()
    project_id = st.session_state.project_id
    if not store or not project_id:
        _go("home")
        return
    project = store.get_project(project_id)
    if not project:
        st.error("Progetto non trovato")
        _go("home")
        return

    # Header
    cols = st.columns([5, 1])
    cols[0].title(f"🪄 Discovery — {project.name}")
    if cols[1].button("← Home"):
        _go("home")

    st.caption(
        "Parla con l'orchestratore. Ti fara` domande mirate per costruire il "
        "contesto ufficiale del progetto. Quando avra` raccolto tutto, ti "
        "proporra` un riassunto strutturato che potrai approvare."
    )

    # Render history
    for msg in st.session_state.discovery_messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            with st.chat_message("user"):
                st.markdown(content if isinstance(content, str) else str(content))
        elif role == "assistant":
            with st.chat_message("assistant"):
                blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
                for b in blocks:
                    if b.get("type") == "text":
                        st.markdown(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        st.caption(f"📋 Contesto proposto")

    # Proposed context (se presente)
    if st.session_state.proposed_context:
        st.divider()
        st.subheader("📋 Contesto proposto")
        ctx = st.session_state.proposed_context
        edited = {}
        for field, _label in CONTEXT_FIELDS:
            val = ctx.get(field, "")
            if field == "channels":
                # Channels e` lista
                channels = ctx.get("channels") or []
                opts = ["meta", "google", "tiktok", "linkedin"]
                edited[field] = st.multiselect(
                    "Canali", options=opts, default=[c for c in channels if c in opts]
                )
            else:
                edited[field] = st.text_area(
                    field.replace("_", " ").title(),
                    value=val,
                    height=70,
                    key=f"ctx_{field}",
                )

        approve_cols = st.columns([1, 1, 3])
        if approve_cols[0].button("✅ Approva e distribuisci", type="primary", use_container_width=True):
            try:
                # Salva contesto finale + cambia status progetto
                store.update_project(
                    project_id,
                    context=edited,
                    status="active",
                    name=edited.get("campaign_name_proposal") or project.name,
                    discovery_messages=st.session_state.discovery_messages,
                )
                # Inizializza i record agente (idempotente)
                store.init_agents_for_project(project_id, edited)
                # Reset state
                st.session_state.proposed_context = None
                st.session_state.discovery_messages = []
                _go("dashboard", project_id=project_id)
            except Exception as e:
                st.error(f"Approvazione fallita: {e}")
        if approve_cols[1].button("✏️ Modifica chat", use_container_width=True):
            st.session_state.proposed_context = None
            st.rerun()

    # Chat input
    if not st.session_state.proposed_context:
        prompt = st.chat_input("Scrivi qui (parti dicendo brief progetto, brand, target, obiettivo…)")
        if prompt:
            if not ANTHROPIC_KEY:
                st.error("Manca ANTHROPIC_API_KEY")
                return
            st.session_state.discovery_messages.append({"role": "user", "content": prompt})
            with st.spinner("L'orchestratore sta pensando…"):
                try:
                    updated_msgs, proposed = run_discovery_turn(
                        api_key=ANTHROPIC_KEY,
                        model=CLAUDE_MODEL,
                        messages=st.session_state.discovery_messages,
                        max_iterations=3,
                    )
                    st.session_state.discovery_messages = updated_msgs
                    if proposed:
                        st.session_state.proposed_context = proposed
                    # Persisti history nel progetto
                    store.update_project(project_id, discovery_messages=updated_msgs)
                except Exception as e:
                    st.error(f"Errore: {e}")
                    with st.expander("Traceback"):
                        st.code(traceback.format_exc())
            st.rerun()


# ── DASHBOARD view: 8 cards ────────────────────────────────────────
def render_dashboard() -> None:
    store = _store()
    project_id = st.session_state.project_id
    if not store or not project_id:
        _go("home")
        return
    project = store.get_project(project_id)
    if not project:
        st.error("Progetto non trovato")
        _go("home")
        return

    cols = st.columns([5, 1, 1])
    cols[0].title(f"📊 Dashboard — {project.name}")
    if cols[1].button("✏️ Modifica contesto"):
        _go("discovery", project_id=project_id)
    if cols[2].button("← Home"):
        _go("home")

    # Mostra contesto in expander
    with st.expander("📋 Contesto progetto", expanded=False):
        if project.context:
            for field, label in CONTEXT_FIELDS:
                val = project.context.get(field, "")
                if val:
                    pretty = ", ".join(val) if isinstance(val, list) else str(val)
                    st.markdown(f"**{field.replace('_', ' ').title()}**: {pretty}")
        else:
            st.info("Nessun contesto ancora.")

    st.divider()
    st.subheader("👥 Team agenti")

    # Mappo gli agenti del progetto in dict slug → ProjectAgent
    agents_by_slug = {a.agent_slug: a for a in (project.agents or [])}

    # Render cards in 2 colonne
    items = AGENT_DEFS
    for i in range(0, len(items), 2):
        row_cols = st.columns(2)
        for col, ad in zip(row_cols, items[i : i + 2]):
            pa = agents_by_slug.get(ad.slug)
            status = pa.status if pa else "received"
            with col.container(border=True):
                head_cols = st.columns([6, 2])
                head_cols[0].markdown(f"### {ad.emoji} {ad.name}")
                head_cols[1].markdown(_status_badge(status), unsafe_allow_html=True)
                st.caption(ad.description)
                btn_cols = st.columns([2, 1])
                if btn_cols[0].button(
                    f"Apri {ad.name} →",
                    key=f"open_agent_{ad.slug}",
                    use_container_width=True,
                ):
                    _go("agent", project_id=project_id, agent_slug=ad.slug)
                if ad.external_url and btn_cols[1].button(
                    "🔗", key=f"ext_{ad.slug}", help=f"Apri {ad.name} esterno"
                ):
                    st.markdown(f"[Apri in nuova tab]({ad.external_url})")


# ── AGENT view: dispatcher su slug ─────────────────────────────────
def render_agent() -> None:
    from agent_pages import render_agent_page  # lazy import per non rallentare home
    project_id = st.session_state.project_id
    slug = st.session_state.agent_slug
    store = _store()
    if not store or not project_id or not slug:
        _go("home")
        return

    project = store.get_project(project_id)
    pa = store.get_agent(project_id, slug)
    if not project or not pa:
        st.error("Progetto o agente non trovato")
        _go("dashboard", project_id=project_id)
        return

    ad = AGENT_DEFS_BY_SLUG.get(slug)
    if not ad:
        st.error(f"Agente sconosciuto: {slug}")
        _go("dashboard", project_id=project_id)
        return

    # Header + nav
    cols = st.columns([5, 2])
    cols[0].title(f"{ad.emoji} {ad.name}")
    cols[0].markdown(_status_badge(pa.status), unsafe_allow_html=True)
    if cols[1].button("← Torna alla dashboard", use_container_width=True):
        _go("dashboard", project_id=project_id)

    st.caption(ad.description)
    with st.expander("📋 Contesto progetto (read-only)", expanded=False):
        for field, _label in CONTEXT_FIELDS:
            val = project.context.get(field, "")
            if val:
                pretty = ", ".join(val) if isinstance(val, list) else str(val)
                st.markdown(f"**{field.replace('_', ' ').title()}**: {pretty}")

    st.divider()
    render_agent_page(slug=slug, project=project, agent_def=ad, project_agent=pa, store=store)

    st.divider()
    # Approve / reset / notes / external link
    cols = st.columns([1, 1, 1])
    if pa.status == "pending_approval":
        if cols[0].button("✅ Approva", type="primary", use_container_width=True):
            store.update_agent(project_id, slug, status="completed")
            _go("dashboard", project_id=project_id)
    if cols[1].button("🔄 Reset stato", use_container_width=True):
        new_status = "waiting_input" if ad.required_inputs else "received"
        store.update_agent(project_id, slug, status=new_status, output={})
        _go("agent", project_id=project_id, agent_slug=slug)
    if ad.external_url and cols[2].link_button("🔗 Apri agente standalone", ad.external_url, use_container_width=True):
        pass

    notes = st.text_area("📝 Note interne (visibili solo qui)", value=pa.notes, height=80, key=f"notes_{slug}")
    if st.button("Salva note", key=f"save_notes_{slug}"):
        store.update_agent(project_id, slug, notes=notes)
        st.success("Note salvate.")


# ── Router ─────────────────────────────────────────────────────────
view = st.session_state.view
if view == "home":
    render_home()
elif view == "discovery":
    render_discovery()
elif view == "dashboard":
    render_dashboard()
elif view == "agent":
    render_agent()
else:
    _go("home")
