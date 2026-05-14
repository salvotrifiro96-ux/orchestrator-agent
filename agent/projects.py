"""Progetti orchestrator: CRUD su Supabase (orchestrator_projects + _project_agents).

Modello mentale:
  - Un PROGETTO ha uno status (discovery|active|completed) e un context jsonb
    che e` il "contesto ufficiale" del marketing una volta approvato.
  - Per ogni progetto ci sono 8 PROJECT_AGENTS (un record per agente del team)
    con il proprio status + user_input + output.

Stati agente:
  - received           : contesto appena distribuito
  - waiting_input      : agente aspetta info dall'utente (es. colori per landing)
  - work_in_progress   : sta eseguendo (di solito breve, sync chiamata Claude)
  - pending_approval   : output pronto da approvare
  - completed          : approvato dall'utente
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import requests

PROJECTS_TABLE = "orchestrator_projects"
AGENTS_TABLE = "orchestrator_project_agents"


# Definizioni degli 8 agenti del team
@dataclass(frozen=True)
class AgentDef:
    slug: str
    name: str
    emoji: str
    description: str
    # Se True, basta il contesto di progetto per partire (no input aggiuntivo dall'utente).
    auto_runnable_on_context: bool = False
    # Chiavi (in user_input) che servono prima di poter eseguire
    required_inputs: tuple[str, ...] = ()
    # Riferimenti esterni (link al singolo agente Streamlit standalone)
    external_url: str = ""


AGENT_DEFS: list[AgentDef] = [
    AgentDef(
        slug="promise",
        name="Promise Writer",
        emoji="🪄",
        description="Promesse Hormozi-style a 4 livelli (pre / USP-name / headline / sub).",
        auto_runnable_on_context=True,
        required_inputs=(),
        external_url="https://promise-writer-agent.streamlit.app",
    ),
    AgentDef(
        slug="copy",
        name="Copywriter",
        emoji="✍️",
        description="Copy ads (Meta/Google/TikTok/LinkedIn), mail conferma, sequenze nurturing.",
        required_inputs=("channel", "selected_promise"),
        external_url="https://copywriter-agent.streamlit.app",
    ),
    AgentDef(
        slug="landing",
        name="Web Designer",
        emoji="🌐",
        description="Landing page HTML/Tailwind partendo dal contesto + brand colors.",
        required_inputs=("slug", "brand_colors_hex"),
    ),
    AgentDef(
        slug="graphic",
        name="Graphic Designer",
        emoji="🎨",
        description="Brief visivo per l'immagine ads (V1: brief; V2: immagine diretta).",
        required_inputs=("aspect_ratio",),
        external_url="https://graphic-designer-agent.streamlit.app",
    ),
    AgentDef(
        slug="media",
        name="Media Buyer",
        emoji="🛒",
        description="Propone lancio campagna Meta (preview-only V1, conferma manuale).",
        required_inputs=("account_slug", "budget_daily_eur"),
        external_url="https://media-buyer-agent.streamlit.app",
    ),
    AgentDef(
        slug="analyst",
        name="Data Analyst",
        emoji="📊",
        description="Performance + funnel + ROAS + breakdown di una campagna Meta.",
        required_inputs=("campaign_id", "account_slug"),
    ),
    AgentDef(
        slug="refresher",
        name="Funnel Refresher",
        emoji="🔁",
        description="Diagnosi creative: cosa pausare, scalare, testare.",
        required_inputs=("campaign_id", "account_slug"),
        external_url="https://funnel-refresher-agent.streamlit.app",
    ),
    AgentDef(
        slug="automation",
        name="Automation Specialist",
        emoji="⚙️",
        description="Costruisce payload workflow HubSpot (form -> conferma -> nurturing).",
        required_inputs=("triggering_form_id",),
    ),
]


AGENT_DEFS_BY_SLUG: dict[str, AgentDef] = {a.slug: a for a in AGENT_DEFS}


# ── Domain types ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class ProjectAgent:
    id: str
    project_id: str
    agent_slug: str
    status: str
    user_input: dict[str, Any]
    output: dict[str, Any]
    notes: str
    updated_at: str


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    status: str  # discovery | active | completed
    context: dict[str, Any]
    discovery_messages: list[dict[str, Any]]
    created_at: str
    updated_at: str
    agents: list[ProjectAgent] = field(default_factory=list)


class ProjectStore:
    def __init__(self, url: str, secret_key: str) -> None:
        if not url or not secret_key:
            raise ValueError("SUPABASE_URL e SUPABASE_SECRET_KEY obbligatori")
        self.url = url.rstrip("/")
        self.secret_key = secret_key
        self._rest = f"{self.url}/rest/v1"
        self._h_read = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
        }
        self._h_write = {
            **self._h_read,
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    @classmethod
    def from_env(cls) -> "ProjectStore | None":
        try:
            import streamlit as st
            url = os.getenv("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
            key = (
                os.getenv("SUPABASE_SECRET_KEY")
                or os.getenv("SUPABASE_SERVICE_KEY")
                or st.secrets.get("SUPABASE_SECRET_KEY", "")
                or st.secrets.get("SUPABASE_SERVICE_KEY", "")
            )
        except Exception:
            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            return None
        return cls(url=url, secret_key=key)

    # ── Projects ──────────────────────────────────────────────────────
    @staticmethod
    def _row_to_project(row: dict[str, Any], agents: list[ProjectAgent] | None = None) -> Project:
        return Project(
            id=str(row["id"]),
            name=row.get("name", "") or "(senza titolo)",
            status=row.get("status", "discovery"),
            context=row.get("context", {}) or {},
            discovery_messages=row.get("discovery_messages", []) or [],
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            agents=agents or [],
        )

    @staticmethod
    def _row_to_agent(row: dict[str, Any]) -> ProjectAgent:
        return ProjectAgent(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            agent_slug=row["agent_slug"],
            status=row.get("status", "received"),
            user_input=row.get("user_input", {}) or {},
            output=row.get("output", {}) or {},
            notes=row.get("notes", "") or "",
            updated_at=row.get("updated_at", ""),
        )

    def list_projects(self, limit: int = 50) -> list[Project]:
        r = requests.get(
            f"{self._rest}/{PROJECTS_TABLE}",
            params={"select": "*", "order": "updated_at.desc", "limit": str(limit)},
            headers=self._h_read, timeout=30,
        )
        r.raise_for_status()
        return [self._row_to_project(row) for row in (r.json() or [])]

    def create_project(self, name: str) -> Project:
        r = requests.post(
            f"{self._rest}/{PROJECTS_TABLE}",
            data=json.dumps({"name": name, "status": "discovery"}),
            headers=self._h_write, timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Create project fallito: {r.status_code} {r.text[:200]}")
        return self._row_to_project(r.json()[0])

    def get_project(self, project_id: str) -> Project | None:
        r = requests.get(
            f"{self._rest}/{PROJECTS_TABLE}",
            params={"select": "*", "id": f"eq.{project_id}", "limit": "1"},
            headers=self._h_read, timeout=30,
        )
        r.raise_for_status()
        rows = r.json() or []
        if not rows:
            return None
        agents = self.list_agents(project_id)
        return self._row_to_project(rows[0], agents=agents)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        status: str | None = None,
        context: dict[str, Any] | None = None,
        discovery_messages: list[dict[str, Any]] | None = None,
    ) -> Project:
        body: dict[str, Any] = {"updated_at": "now()"}
        if name is not None: body["name"] = name
        if status is not None: body["status"] = status
        if context is not None: body["context"] = context
        if discovery_messages is not None: body["discovery_messages"] = discovery_messages
        r = requests.patch(
            f"{self._rest}/{PROJECTS_TABLE}",
            params={"id": f"eq.{project_id}"},
            data=json.dumps(body),
            headers=self._h_write, timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Update project fallito: {r.status_code} {r.text[:200]}")
        return self._row_to_project(r.json()[0])

    def delete_project(self, project_id: str) -> None:
        r = requests.delete(
            f"{self._rest}/{PROJECTS_TABLE}",
            params={"id": f"eq.{project_id}"},
            headers=self._h_read, timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Delete project fallito: {r.status_code} {r.text[:200]}")

    # ── Project agents ────────────────────────────────────────────────
    def list_agents(self, project_id: str) -> list[ProjectAgent]:
        r = requests.get(
            f"{self._rest}/{AGENTS_TABLE}",
            params={
                "select": "*",
                "project_id": f"eq.{project_id}",
                "order": "agent_slug.asc",
            },
            headers=self._h_read, timeout=30,
        )
        r.raise_for_status()
        return [self._row_to_agent(row) for row in (r.json() or [])]

    def get_agent(self, project_id: str, agent_slug: str) -> ProjectAgent | None:
        r = requests.get(
            f"{self._rest}/{AGENTS_TABLE}",
            params={
                "select": "*",
                "project_id": f"eq.{project_id}",
                "agent_slug": f"eq.{agent_slug}",
                "limit": "1",
            },
            headers=self._h_read, timeout=30,
        )
        r.raise_for_status()
        rows = r.json() or []
        return self._row_to_agent(rows[0]) if rows else None

    def init_agents_for_project(self, project_id: str, context: dict[str, Any]) -> list[ProjectAgent]:
        """Crea (idempotente) i record di tutti gli 8 agenti per il progetto.

        Calcola lo status iniziale: 'received' se basta il contesto, 'waiting_input'
        se l'agente ha required_inputs non ancora forniti.
        """
        rows: list[dict[str, Any]] = []
        for ad in AGENT_DEFS:
            status = "received" if not ad.required_inputs else "waiting_input"
            rows.append({
                "project_id": project_id,
                "agent_slug": ad.slug,
                "status": status,
                "user_input": {},
                "output": {},
                "notes": "",
            })
        r = requests.post(
            f"{self._rest}/{AGENTS_TABLE}",
            data=json.dumps(rows),
            headers={**self._h_write, "Prefer": "return=representation,resolution=merge-duplicates"},
            timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Init agents fallito: {r.status_code} {r.text[:200]}")
        return [self._row_to_agent(row) for row in (r.json() or [])]

    def update_agent(
        self,
        project_id: str,
        agent_slug: str,
        *,
        status: str | None = None,
        user_input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> ProjectAgent:
        body: dict[str, Any] = {"updated_at": "now()"}
        if status is not None: body["status"] = status
        if user_input is not None: body["user_input"] = user_input
        if output is not None: body["output"] = output
        if notes is not None: body["notes"] = notes
        r = requests.patch(
            f"{self._rest}/{AGENTS_TABLE}",
            params={
                "project_id": f"eq.{project_id}",
                "agent_slug": f"eq.{agent_slug}",
            },
            data=json.dumps(body),
            headers=self._h_write, timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Update agent fallito: {r.status_code} {r.text[:200]}")
        rows = r.json() or []
        if not rows:
            raise RuntimeError("Update agent: nessuna riga aggiornata")
        return self._row_to_agent(rows[0])
