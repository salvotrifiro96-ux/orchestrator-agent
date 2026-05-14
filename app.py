"""Orchestrator Agent — Streamlit chat UI.

Pattern:
  - History conversazionale in session_state (formato Anthropic messages)
  - Ogni input utente → chiama orchestrator.run_loop → loop tool-use → assistant final
  - Render: messaggi user/assistant + caption per tool_use/tool_result
"""
from __future__ import annotations

import json
import os
import traceback
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from agent.orchestrator import run_loop


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


# ── State ──────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []  # history conversazionale completa
if "ui_log" not in st.session_state:
    # log "human readable" del flow (testi + tool calls + risultati)
    # ogni voce: {"kind": "user|assistant|tool_use|tool_result|tool_error", ...}
    st.session_state.ui_log = []


# ── Sidebar ────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🎯 Orchestrator")
    st.caption("PM virtuale del team Marketing AI Leone.")
    st.divider()
    st.markdown("**Agenti collegati:**")
    st.markdown(
        "- 🪄 promise-writer\n"
        "- ✍️ copywriter\n"
        "- 🎨 graphic-designer *(stub V1)*\n"
        "- 🛒 media-buyer *(propose-only V1)*\n"
        "- 📊 data-analyst"
    )
    st.divider()
    st.write(f"**Claude API:** {'✅' if ANTHROPIC_KEY else '⚠️'}")
    st.write(f"**Model:** `{CLAUDE_MODEL}`")
    st.divider()
    if st.button("🔄 Nuova chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.ui_log = []
        st.rerun()


# ── Header ─────────────────────────────────────────────────────────
st.title("🎯 Orchestrator")
st.caption(
    "Dimmi cosa vuoi fare. Esempi: "
    "_'analizza la campagna 22 nicchie'_, "
    "_'scrivi 5 copy meta per il workshop 15 giugno'_, "
    "_'mostrami gli ultimi 5 brief del promessatore'_."
)


# ── Render history ─────────────────────────────────────────────────
def _render_entry(entry: dict[str, Any]) -> None:
    kind = entry.get("kind")
    if kind == "user":
        with st.chat_message("user"):
            st.markdown(entry["text"])
    elif kind == "assistant":
        with st.chat_message("assistant"):
            st.markdown(entry["text"])
    elif kind == "tool_use":
        with st.chat_message("assistant", avatar="🛠️"):
            name = entry.get("name", "")
            inp = entry.get("input", {})
            st.caption(f"**Tool call**: `{name}`")
            with st.expander("Argomenti", expanded=False):
                st.json(inp)
    elif kind == "tool_result":
        with st.chat_message("assistant", avatar="📦"):
            name = entry.get("name", "")
            res = entry.get("result", {})
            preview = _summarize_result(name, res)
            st.caption(f"**Tool result** `{name}` — {preview}")
            with st.expander("Risultato completo", expanded=False):
                st.json(res)
    elif kind == "tool_error":
        with st.chat_message("assistant", avatar="⚠️"):
            st.error(f"**Errore tool** `{entry.get('name','')}`: {entry.get('error','')}")


def _summarize_result(name: str, res: Any) -> str:
    if not isinstance(res, dict):
        return "ok"
    if "error" in res:
        return f"ERROR: {str(res['error'])[:100]}"
    # custom summaries per tool
    if name == "list_promise_briefs":
        return f"{len(res.get('briefs', []))} brief"
    if name == "list_meta_campaigns":
        return f"{res.get('total', 0)} campagne"
    if name == "generate_promises":
        return f"{len(res.get('promises', []))} promesse generate"
    if name == "analyze_campaign":
        mi = res.get("meta_insights", {})
        return f"spesa €{mi.get('spend', 0)}, lead {mi.get('leads_meta', 0)}"
    return "ok"


for entry in st.session_state.ui_log:
    _render_entry(entry)


# ── Chat input ─────────────────────────────────────────────────────
prompt = st.chat_input("Cosa vuoi che faccia?")
if prompt:
    if not ANTHROPIC_KEY:
        st.error("Manca `ANTHROPIC_API_KEY`.")
        st.stop()

    # 1. Mostra subito il messaggio user
    st.session_state.ui_log.append({"kind": "user", "text": prompt})
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Esegui il loop tool-use
    log_buffer: list[dict[str, Any]] = []
    def _on_event(ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "assistant_text":
            log_buffer.append({"kind": "assistant", "text": ev["text"]})
        elif t == "tool_use":
            log_buffer.append({"kind": "tool_use", "name": ev["name"], "input": ev.get("input", {})})
        elif t == "tool_result":
            log_buffer.append({"kind": "tool_result", "name": ev["name"], "result": ev.get("result", {})})
        elif t == "tool_error":
            log_buffer.append({"kind": "tool_error", "name": ev["name"], "error": ev.get("error", "")})

    with st.spinner("Sto coordinando il team…"):
        try:
            run_loop(
                api_key=ANTHROPIC_KEY,
                model=CLAUDE_MODEL,
                messages=st.session_state.messages,
                on_event=_on_event,
                max_iterations=8,
            )
        except Exception as e:
            log_buffer.append({"kind": "tool_error", "name": "orchestrator", "error": f"{e}\n{traceback.format_exc()}"})

    # 3. Aggiungi al log persistente e rerun
    st.session_state.ui_log.extend(log_buffer)
    st.rerun()
