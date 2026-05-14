"""Tool registry: aggrega schemi e dispatch per il loop tool-use Claude."""
from __future__ import annotations

import os
from typing import Any

from tools import analyze as analyze_t
from tools import copy as copy_t
from tools import landing as landing_t
from tools import promise as promise_t
from tools import refresh as refresh_t
from tools import visual_and_launch as launch_t
from tools import workflow as workflow_t


TOOL_SCHEMAS: list[dict[str, Any]] = [
    *promise_t.SCHEMAS,
    *copy_t.SCHEMAS,
    *landing_t.SCHEMAS,
    *analyze_t.SCHEMAS,
    *refresh_t.SCHEMAS,
    *launch_t.SCHEMAS,
    *workflow_t.SCHEMAS,
]


def dispatch(name: str, args: dict[str, Any], *, anthropic_api_key: str = "") -> Any:
    """Esegue il tool richiesto. Ritorna sempre un dict serializzabile JSON."""
    api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")

    # promise
    if name == "list_promise_briefs":
        return promise_t.list_promise_briefs(**args)
    if name == "get_promise_brief":
        return promise_t.get_promise_brief(**args)
    if name == "generate_promises":
        return promise_t.generate_promises(api_key=api_key, **args)

    # copy
    if name == "write_ad_copy":
        return copy_t.write_ad_copy(api_key=api_key, **args)
    if name == "write_email_confirmation":
        return copy_t.write_email_confirmation(api_key=api_key, **args)
    if name == "write_nurturing_sequence":
        return copy_t.write_nurturing_sequence(api_key=api_key, **args)

    # analyze
    if name == "list_meta_campaigns":
        return analyze_t.list_meta_campaigns(**args)
    if name == "analyze_campaign":
        return analyze_t.analyze_campaign(**args)

    # launch + visual
    if name == "make_visual_brief":
        return launch_t.make_visual_brief(**args)
    if name == "propose_ad_launch":
        return launch_t.propose_ad_launch(**args)

    # web designer
    if name == "generate_landing_html":
        return landing_t.generate_landing_html(api_key=api_key, **args)

    # funnel refresher
    if name == "diagnose_campaign_refresh":
        return refresh_t.diagnose_campaign_refresh(**args)

    # automation specialist
    if name == "build_hubspot_funnel_workflow":
        return workflow_t.build_hubspot_funnel_workflow(**args)

    raise ValueError(f"Tool sconosciuto: {name}")
