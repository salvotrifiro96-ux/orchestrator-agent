"""Renderizza la sub-pagina di ciascun agente nella dashboard del progetto.

Ogni agent page:
  - mostra eventuale output gia` salvato in `project_agent.output`
  - permette di raccogliere input aggiuntivi (form)
  - lancia il tool corrispondente
  - aggiorna lo stato (received → work_in_progress → pending_approval)
  - salva l'output in Supabase

Il dispatch e` su `agent_slug`.
"""
from __future__ import annotations

import os
import traceback
from typing import Any

import streamlit as st

from agent.projects import AgentDef, Project, ProjectAgent, ProjectStore

from tools import analyze as analyze_t
from tools import copy as copy_t
from tools import landing as landing_t
from tools import promise as promise_t
from tools import refresh as refresh_t
from tools import visual_and_launch as launch_t
from tools import workflow as workflow_t


def _anthropic_key() -> str:
    try:
        return os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        return os.getenv("ANTHROPIC_API_KEY", "")


def _set_running(store: ProjectStore, project_id: str, slug: str) -> None:
    store.update_agent(project_id, slug, status="work_in_progress")


def _save_output_pending(store: ProjectStore, project_id: str, slug: str, output: dict[str, Any], user_input: dict[str, Any] | None = None) -> None:
    kwargs: dict[str, Any] = {"status": "pending_approval", "output": output}
    if user_input is not None:
        kwargs["user_input"] = user_input
    store.update_agent(project_id, slug, **kwargs)


def render_agent_page(
    *,
    slug: str,
    project: Project,
    agent_def: AgentDef,
    project_agent: ProjectAgent,
    store: ProjectStore,
) -> None:
    handler = {
        "promise": _render_promise,
        "copy": _render_copy,
        "landing": _render_landing,
        "graphic": _render_graphic,
        "media": _render_media,
        "analyst": _render_analyst,
        "refresher": _render_refresher,
        "automation": _render_automation,
    }.get(slug)
    if not handler:
        st.error(f"No renderer for agent slug={slug}")
        return
    handler(project=project, agent_def=agent_def, project_agent=project_agent, store=store)


# ── 1. Promise Writer ────────────────────────────────────────────
def _render_promise(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    ctx = project.context
    promises = (project_agent.output or {}).get("promises") or []
    selected = project.selected_promise

    if selected:
        st.success("✅ Promessa ufficiale del progetto scelta — visibile a tutti gli altri agenti.")
        with st.container(border=True):
            _render_promise_card(selected)
        cols = st.columns([1, 1, 3])
        if cols[0].button("🔄 Cambia promessa", use_container_width=True):
            # Riapro la scelta: rimuovo selected dal progetto + status agent torna pending_approval
            store.update_project(project.id, selected_promise=None)
            store.update_agent(project.id, "promise", status="pending_approval")
            st.rerun()
        if cols[1].button("🔁 Rigenera tutte", use_container_width=True):
            _regenerate_all_promises(store, project, ctx)
            st.rerun()
        st.caption("Cambiando promessa, gli output degli agenti che la usavano resteranno (puoi rigenerarli).")
        return

    # Nessuna promessa ufficiale scelta ancora
    if not promises:
        st.info("Nessuna promessa generata ancora. Clicca qui per produrne 10 ora.")
        if st.button("🪄 Genera 10 promesse", type="primary"):
            _regenerate_all_promises(store, project, ctx, n=10)
            st.rerun()
        return

    st.subheader(f"🪄 {len(promises)} promesse generate — scegli quella ufficiale del progetto")
    st.caption(
        "Tutti gli altri agenti (Copywriter, Web Designer, Graphic, Media Buyer) "
        "useranno la promessa che selezioni qui. Puoi cambiarla in qualunque "
        "momento. Per editing fine (rigenera solo la headline / il sub / l'USP) "
        "usa il [Promise Writer standalone](https://promise-writer-agent.streamlit.app)."
    )

    # Bottoni rigenera/aggiungi
    bc = st.columns([1, 1, 3])
    if bc[0].button("🔁 Rigenera tutte (10)", use_container_width=True):
        _regenerate_all_promises(store, project, ctx, n=10)
        st.rerun()
    if bc[1].button("➕ Aggiungi 5", use_container_width=True):
        _add_more_promises(store, project, ctx, project_agent, n=5)
        st.rerun()

    st.divider()

    for i, p in enumerate(promises):
        with st.container(border=True):
            _render_promise_card(p)
            if st.button("🎯 Approva questa come promessa ufficiale", key=f"approve_promise_{i}", type="primary"):
                store.update_project(project.id, selected_promise=p)
                store.update_agent(project.id, "promise", status="completed")
                st.success(f"Promessa #{i+1} approvata come ufficiale.")
                st.rerun()


def _render_promise_card(p: dict[str, Any]) -> None:
    if p.get("pre_headline"):
        st.caption(f"_{p['pre_headline']}_")
    if p.get("usp_name"):
        st.markdown(
            f"<div style='font-size:1.4rem; font-weight:800; color:#16a34a;'>{p['usp_name']}</div>",
            unsafe_allow_html=True,
        )
    st.markdown(f"### {p.get('headline','')}")
    if p.get("sub_headline"):
        st.markdown(f"_{p['sub_headline']}_")


def _regenerate_all_promises(store: ProjectStore, project: Project, ctx: dict[str, Any], n: int = 10) -> None:
    store.update_agent(project.id, "promise", status="work_in_progress")
    try:
        with st.spinner(f"Rigenero {n} promesse…"):
            res = promise_t.generate_promises(
                api_key=_anthropic_key(),
                context=_context_to_blob(ctx),
                target_audience=ctx.get("target_audience", ""),
                brand_voice=ctx.get("brand_voice", ""),
                n_headlines=n,
                save_to_archive=True,
                project_id=project.id,
            )
        store.update_agent(
            project.id, "promise",
            status="pending_approval",
            output=res,
            user_input={"n_headlines": n},
        )
    except Exception as e:
        st.error(f"Rigenerazione fallita: {e}")
        store.update_agent(project.id, "promise", status="pending_approval")


def _add_more_promises(store: ProjectStore, project: Project, ctx: dict[str, Any], project_agent: ProjectAgent, n: int = 5) -> None:
    store.update_agent(project.id, "promise", status="work_in_progress")
    try:
        with st.spinner(f"Aggiungo {n} promesse…"):
            res = promise_t.generate_promises(
                api_key=_anthropic_key(),
                context=_context_to_blob(ctx),
                target_audience=ctx.get("target_audience", ""),
                brand_voice=ctx.get("brand_voice", ""),
                n_headlines=n,
                save_to_archive=False,  # estensione: non riapro un nuovo brief
                project_id=project.id,
            )
        existing = (project_agent.output or {}).get("promises") or []
        new = res.get("promises") or []
        store.update_agent(
            project.id, "promise",
            status="pending_approval",
            output={**(project_agent.output or {}), "promises": existing + new},
        )
    except Exception as e:
        st.error(f"Aggiunta fallita: {e}")
        store.update_agent(project.id, "promise", status="pending_approval")


# ── 2. Copywriter ────────────────────────────────────────────────
def _render_copy(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    ctx = project.context
    if not _require_selected_promise(project):
        return
    promise = project.selected_promise or {}

    st.subheader("✍️ Genera copy")
    st.caption("Usa la promessa ufficiale del progetto (in alto). Cambia canale e varianti.")
    with st.container(border=True):
        _render_promise_card(promise)

    cols = st.columns(2)
    channel = cols[0].selectbox("Canale", ["meta", "google", "tiktok", "linkedin"],
                                  index=["meta", "google", "tiktok", "linkedin"].index(project_agent.user_input.get("channel", "meta")))
    n_variants = cols[1].slider("Varianti", 3, 10, value=int(project_agent.user_input.get("n_variants", 5)))
    extra = st.text_input("Indicazioni extra (opzionale)", value=project_agent.user_input.get("extra_instructions", ""))

    if st.button("✍️ Genera copy", type="primary"):
        _set_running(store, project.id, "copy")
        try:
            with st.spinner(f"Genero {n_variants} copy {channel}…"):
                res = copy_t.write_ad_copy(
                    api_key=_anthropic_key(),
                    channel=channel,
                    context=_context_to_blob(ctx),
                    promise=_promise_to_text(promise),
                    target_audience=ctx.get("target_audience", ""),
                    brand_voice=ctx.get("brand_voice", ""),
                    n_variants=n_variants,
                    extra_instructions=extra,
                )
            _save_output_pending(
                store, project.id, "copy", res,
                user_input={"channel": channel, "n_variants": n_variants, "extra_instructions": extra},
            )
            st.rerun()
        except Exception as e:
            st.error(f"Generazione fallita: {e}")

    out = project_agent.output or {}
    if out.get("ads"):
        st.divider()
        st.subheader(f"📦 Output: {len(out['ads'])} copy {out.get('channel','')}")
        for i, a in enumerate(out["ads"]):
            with st.container(border=True):
                st.markdown(f"**Variante #{i+1}**")
                st.json(a)


# ── 3. Web Designer (landing) ────────────────────────────────────
def _render_landing(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    ctx = project.context
    st.subheader("🌐 Genera landing")
    cols = st.columns(2)
    slug = cols[0].text_input("Slug URL", value=project_agent.user_input.get("slug", ctx.get("campaign_name_proposal", "").lower().replace(" ", "-")))
    font = cols[1].text_input("Font family", value=project_agent.user_input.get("font_family", "Inter"))

    cc = st.columns(2)
    primary = cc[0].color_picker("Colore primario", value=project_agent.user_input.get("primary_color", "#16a34a"))
    accent = cc[1].color_picker("Colore accent", value=project_agent.user_input.get("accent_color", "#0f172a"))

    form_html = st.text_area("Form HTML embed (opzionale)", value=project_agent.user_input.get("form_html", ""), height=120)
    references = st.text_area("References / esempi (opzionale)", value=project_agent.user_input.get("references", ""), height=80)

    if st.button("🌐 Genera landing HTML", type="primary"):
        if not _anthropic_key():
            st.error("Manca ANTHROPIC_API_KEY")
            return
        _set_running(store, project.id, "landing")
        try:
            with st.spinner("Genero HTML…"):
                res = landing_t.generate_landing_html(
                    api_key=_anthropic_key(),
                    client_name=ctx.get("client_name", "Leone Master School"),
                    slug=slug,
                    project_context=_context_to_blob(ctx),
                    form_html=form_html,
                    brand_colors_hex={"primary": primary, "accent": accent},
                    font_family=font,
                    style_keywords=ctx.get("brand_voice", "diretto, premium, italiano"),
                    references=references,
                )
            _save_output_pending(
                store, project.id, "landing", res,
                user_input={
                    "slug": slug, "font_family": font, "primary_color": primary, "accent_color": accent,
                    "form_html": form_html, "references": references,
                },
            )
            st.rerun()
        except Exception as e:
            st.error(f"Generazione fallita: {e}")

    out = project_agent.output or {}
    if out.get("html"):
        st.divider()
        st.subheader("📦 Output landing")
        st.caption(f"Slug: `{out.get('slug')}` · {len(out['html'])} char")
        with st.expander("👀 Preview HTML (iframe)", expanded=True):
            st.components.v1.html(out["html"], height=800, scrolling=True)
        with st.expander("📜 HTML sorgente"):
            st.code(out["html"], language="html")


# ── 4. Graphic Designer (visual brief) ───────────────────────────
def _render_graphic(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    ctx = project.context
    if not _require_selected_promise(project):
        return
    promise = project.selected_promise or {}

    st.subheader("🎨 Brief visivo")
    st.caption("Usa la promessa ufficiale del progetto.")
    with st.container(border=True):
        _render_promise_card(promise)

    cols = st.columns(3)
    ratio = cols[0].selectbox("Aspect ratio", ["1:1", "4:5", "9:16", "16:9"],
                              index=["1:1", "4:5", "9:16", "16:9"].index(project_agent.user_input.get("aspect_ratio", "1:1")))
    channel = cols[1].selectbox("Canale", ["meta", "google", "tiktok", "linkedin"], index=0)
    mood = cols[2].text_input("Mood", value=project_agent.user_input.get("mood", "diretto premium italiano"))
    must_have = st.text_input("Must-have (separati da virgola)", value=", ".join(project_agent.user_input.get("must_have", [])))
    must_avoid = st.text_input("Must-avoid (separati da virgola)", value=", ".join(project_agent.user_input.get("must_avoid", [])))

    if st.button("🎨 Genera brief visivo", type="primary"):
        try:
            res = launch_t.make_visual_brief(
                promise=_promise_to_text(promise),
                target_audience=ctx.get("target_audience", ""),
                channel=channel,
                aspect_ratio=ratio,
                mood=mood,
                must_have=[s.strip() for s in must_have.split(",") if s.strip()],
                must_avoid=[s.strip() for s in must_avoid.split(",") if s.strip()],
            )
            _save_output_pending(
                store, project.id, "graphic", res,
                user_input={"aspect_ratio": ratio, "channel": channel, "mood": mood,
                            "must_have": [s.strip() for s in must_have.split(",") if s.strip()],
                            "must_avoid": [s.strip() for s in must_avoid.split(",") if s.strip()]},
            )
            st.rerun()
        except Exception as e:
            st.error(f"Errore: {e}")

    out = project_agent.output or {}
    if out:
        st.divider()
        st.subheader("📦 Brief visivo")
        st.json(out)


def _require_selected_promise(project: Project) -> bool:
    """Helper UX: se la promessa ufficiale non e` stata scelta, mostra warning."""
    if project.selected_promise:
        return True
    st.warning(
        "⏳ Devi prima scegliere la **promessa ufficiale** del progetto. "
        "Vai sull'agente 🪄 Promise Writer e clicca '🎯 Approva questa come "
        "promessa ufficiale' sulla promessa che vuoi usare."
    )
    return False


# ── 5. Media Buyer (propose launch) ──────────────────────────────
def _render_media(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    ctx = project.context
    st.subheader("🛒 Proposta lancio Meta")
    cols = st.columns(2)
    account = cols[0].selectbox(
        "Account Meta",
        ["SWAT", "PATATINO", "LRES", "GEN", "MEP", "ICMD"],
        index=["SWAT", "PATATINO", "LRES", "GEN", "MEP", "ICMD"].index(project_agent.user_input.get("account_slug", "SWAT")),
    )
    budget = cols[1].number_input("Budget giornaliero EUR", min_value=1, max_value=1000,
                                   value=int(project_agent.user_input.get("budget_daily_eur", 50)))
    objective = st.selectbox(
        "Objective",
        ["OUTCOME_LEADS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_SALES"],
        index=["OUTCOME_LEADS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_SALES"].index(project_agent.user_input.get("objective", "OUTCOME_LEADS")),
    )
    target = st.text_input("Target descrittivo", value=project_agent.user_input.get("target", "Broad Italia 25-65 Advantage"))
    start = st.text_input("Start date (ISO o 'subito')", value=project_agent.user_input.get("start_date", "subito"))
    placements = st.text_input("Placements", value=project_agent.user_input.get("placements", "advantage_plus"))

    if st.button("🛒 Componi proposta", type="primary"):
        try:
            res = launch_t.propose_ad_launch(
                account_slug=account,
                campaign_name=ctx.get("campaign_name_proposal", "lms_campaign"),
                budget_daily_eur=int(budget),
                objective=objective,
                target=target,
                placements=placements,
                start_date=start,
            )
            _save_output_pending(
                store, project.id, "media", res,
                user_input={"account_slug": account, "budget_daily_eur": int(budget), "objective": objective,
                            "target": target, "placements": placements, "start_date": start},
            )
            st.rerun()
        except Exception as e:
            st.error(f"Errore: {e}")

    out = project_agent.output or {}
    if out:
        st.divider()
        st.subheader("📦 Proposta")
        st.warning("⚠️ Proposta preview-only. Per lanciare davvero usa il [Media Buyer Agent](https://media-buyer-agent.streamlit.app).")
        st.json(out)


# ── 6. Data Analyst ──────────────────────────────────────────────
def _render_analyst(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    st.subheader("📊 Analisi campagna")
    campaigns_cache = st.session_state.get("_meta_campaigns_cache")
    if campaigns_cache is None or st.button("🔄 Ricarica campagne attive"):
        with st.spinner("Carico campagne Meta…"):
            try:
                campaigns_cache = analyze_t.list_meta_campaigns(days_paused=30)
                st.session_state["_meta_campaigns_cache"] = campaigns_cache
            except Exception as e:
                st.error(f"Errore: {e}")
                return

    camps = campaigns_cache.get("campaigns", []) if campaigns_cache else []
    options = [c for c in camps if "id" in c]
    if not options:
        st.warning("Nessuna campagna trovata.")
        return
    selected = st.selectbox(
        "Campagna da analizzare",
        options=list(range(len(options))),
        format_func=lambda i: f"[{options[i]['account_slug']}] {options[i]['name']}",
        index=0,
    )
    days = st.slider("Periodo (giorni)", 7, 90, value=int(project_agent.user_input.get("days", 30)))

    if st.button("📊 Analizza", type="primary"):
        c = options[selected]
        _set_running(store, project.id, "analyst")
        try:
            with st.spinner("Analizzo…"):
                res = analyze_t.analyze_campaign(
                    campaign_id=c["id"],
                    account_slug=c["account_slug"],
                    days=days,
                )
            _save_output_pending(
                store, project.id, "analyst", res,
                user_input={"campaign_id": c["id"], "account_slug": c["account_slug"], "days": days},
            )
            st.rerun()
        except Exception as e:
            st.error(f"Errore: {e}")

    out = project_agent.output or {}
    if out and out.get("campaign_name"):
        st.divider()
        st.subheader(f"📦 {out.get('campaign_name')}")
        mi = out.get("meta_insights", {})
        cc = st.columns(5)
        cc[0].metric("Spesa", f"€ {mi.get('spend', 0):.2f}")
        cc[1].metric("Lead Meta", mi.get('leads_meta', 0))
        cc[2].metric("CPL Meta", f"€ {mi.get('cpl_meta', 0):.2f}" if mi.get('cpl_meta') else "—")
        cc[3].metric("CTR", f"{mi.get('ctr', 0):.2f}%")
        cc[4].metric("CPM", f"€ {mi.get('cpm', 0):.2f}")
        fd = out.get("funnel_db", {})
        if isinstance(fd, dict) and "errore" not in fd:
            cf = st.columns(4)
            cf[0].metric("Risposte", fd.get("risposte", 0))
            cf[1].metric("App. set", fd.get("app_set", 0))
            cf[2].metric("Vendite", fd.get("vendite", 0))
            cf[3].metric("ROAS", f"{fd.get('roas', 0):.2f}x")
        with st.expander("📜 Payload completo"):
            st.json(out)


# ── 7. Funnel Refresher ──────────────────────────────────────────
def _render_refresher(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    st.subheader("🔁 Diagnostica creative")
    campaigns_cache = st.session_state.get("_meta_campaigns_cache")
    if campaigns_cache is None or st.button("🔄 Ricarica campagne attive", key="reload_camps_ref"):
        try:
            campaigns_cache = analyze_t.list_meta_campaigns(days_paused=30)
            st.session_state["_meta_campaigns_cache"] = campaigns_cache
        except Exception as e:
            st.error(f"Errore: {e}")
            return

    camps = campaigns_cache.get("campaigns", []) if campaigns_cache else []
    options = [c for c in camps if "id" in c]
    if not options:
        st.warning("Nessuna campagna trovata.")
        return
    selected = st.selectbox(
        "Campagna",
        options=list(range(len(options))),
        format_func=lambda i: f"[{options[i]['account_slug']}] {options[i]['name']}",
        index=0,
        key="ref_camp_sel",
    )
    days = st.slider("Periodo (giorni)", 7, 90, value=int(project_agent.user_input.get("days", 14)), key="ref_days")

    if st.button("🔁 Diagnostica", type="primary"):
        c = options[selected]
        _set_running(store, project.id, "refresher")
        try:
            with st.spinner("Diagnostico…"):
                res = refresh_t.diagnose_campaign_refresh(
                    campaign_id=c["id"],
                    account_slug=c["account_slug"],
                    days=days,
                )
            _save_output_pending(
                store, project.id, "refresher", res,
                user_input={"campaign_id": c["id"], "account_slug": c["account_slug"], "days": days},
            )
            st.rerun()
        except Exception as e:
            st.error(f"Errore: {e}")

    out = project_agent.output or {}
    if out and out.get("report"):
        st.divider()
        st.subheader("📦 Diagnosi creative")
        st.json(out["report"])


# ── 8. Automation Specialist ─────────────────────────────────────
def _render_automation(*, project: Project, agent_def: AgentDef, project_agent: ProjectAgent, store: ProjectStore) -> None:
    st.subheader("⚙️ Workflow HubSpot")
    cols = st.columns(2)
    name = cols[0].text_input("Nome workflow", value=project_agent.user_input.get("name", project.context.get("campaign_name_proposal", "")))
    form_id = cols[1].text_input("Form HubSpot ID (triggering)", value=project_agent.user_input.get("triggering_form_id", ""))
    conf_email = st.text_input("Email conferma ID (opzionale)", value=project_agent.user_input.get("confirmation_email_id", ""))
    conf_delay = st.number_input("Delay conferma (min)", min_value=0, max_value=180,
                                  value=int(project_agent.user_input.get("confirmation_delay_minutes", 1)))

    st.markdown("**Sequenza nurturing** (1 per riga: `day,email_id,subject`)")
    nurturing_raw = st.text_area(
        "Es. `3,abc-123,Subject mail giorno 3`",
        value=project_agent.user_input.get("nurturing_raw", ""),
        height=120,
    )
    nurturing: list[dict[str, Any]] = []
    for line in nurturing_raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0].isdigit():
            nurturing.append({"day": int(parts[0]), "email_id": parts[1], "subject": ",".join(parts[2:])})

    if st.button("⚙️ Costruisci workflow", type="primary", disabled=not form_id or not name):
        try:
            res = workflow_t.build_hubspot_funnel_workflow(
                name=name,
                triggering_form_id=form_id,
                confirmation_email_id=conf_email or None,
                confirmation_delay_minutes=int(conf_delay),
                nurturing_sequence=nurturing,
            )
            _save_output_pending(
                store, project.id, "automation", res,
                user_input={"name": name, "triggering_form_id": form_id, "confirmation_email_id": conf_email,
                            "confirmation_delay_minutes": int(conf_delay), "nurturing_raw": nurturing_raw},
            )
            st.rerun()
        except Exception as e:
            st.error(f"Errore: {e}")

    out = project_agent.output or {}
    if out and out.get("workflow_payload"):
        st.divider()
        st.subheader("📦 Workflow payload")
        st.warning("⚠️ Preview-only. Pubblicalo manualmente nel [Automation Specialist Agent](https://automation-specialist-agent.streamlit.app).")
        with st.expander("📜 Markdown spec", expanded=True):
            st.markdown(out.get("spec_markdown", ""))
        with st.expander("🔧 Payload JSON"):
            st.json(out["workflow_payload"])


# ── Helpers condivisi ────────────────────────────────────────────
def _context_to_blob(ctx: dict[str, Any]) -> str:
    """Serializza il contesto in un testo strutturato che gli agent prompt possono leggere."""
    lines = []
    for key, val in (ctx or {}).items():
        if not val:
            continue
        pretty = ", ".join(val) if isinstance(val, list) else str(val)
        lines.append(f"## {key.replace('_', ' ').title()}\n{pretty}")
    return "\n\n".join(lines)


def _promise_to_text(p: dict[str, Any]) -> str:
    return (
        f"PRE: {p.get('pre_headline','')}\n"
        f"USP: {p.get('usp_name','')}\n"
        f"HEADLINE: {p.get('headline','')}\n"
        f"SUB: {p.get('sub_headline','')}"
    )


def _get_completed_promises(store: ProjectStore, project_id: str) -> list[dict[str, Any]]:
    """Cerca l'output del Promise Writer di questo progetto (anche se non ancora approved)."""
    pa = store.get_agent(project_id, "promise")
    if not pa:
        return []
    out = pa.output or {}
    return out.get("promises", []) or []
