"""HTTP mutation paths that require durable-before-ack when journaling is enabled."""

from __future__ import annotations

import re

# (method, path regex) -> kind label for the operations ledger
MUTATION_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("POST", re.compile(r"^/init$"), "init"),
    ("PATCH", re.compile(r"^/settings$"), "settings"),
    ("POST", re.compile(r"^/runs$"), "run_accept"),
    ("POST", re.compile(r"^/runs/[^/]+/approve$"), "run_approve"),
    ("POST", re.compile(r"^/runs/[^/]+/cancel$"), "run_cancel"),
    ("POST", re.compile(r"^/assets$"), "asset_upload"),
    ("POST", re.compile(r"^/skills/install$"), "skill_install"),
    ("POST", re.compile(r"^/workflows/import/comfy$"), "comfy_import"),
    ("POST", re.compile(r"^/adapt/run$"), "adapt_run"),
    ("POST", re.compile(r"^/presets$"), "preset_create"),
    ("DELETE", re.compile(r"^/presets/[^/]+$"), "preset_delete"),
    ("POST", re.compile(r"^/adapts/batch$"), "adapt_batch"),
    ("POST", re.compile(r"^/integrations/gsheet/sync$"), "gsheet_sync"),
    ("POST", re.compile(r"^/providers$"), "provider_add"),
    ("DELETE", re.compile(r"^/providers/[^/]+$"), "provider_remove"),
    ("POST", re.compile(r"^/providers/[^/]+/oauth$"), "provider_oauth"),
    ("POST", re.compile(r"^/providers/[^/]+/disconnect$"), "provider_oauth_disconnect"),
    ("GET", re.compile(r"^/providers/oauth/callback$"), "provider_oauth_callback"),
    ("POST", re.compile(r"^/collab/sessions$"), "collab_create"),
    ("PUT", re.compile(r"^/collab/sessions/[^/]+$"), "collab_put"),
    ("POST", re.compile(r"^/catalog/refresh$"), "catalog_refresh"),
    ("POST", re.compile(r"^/mcp$"), "mcp_rpc"),
)

JOURNAL_WIRED_KINDS = frozenset(kind for _method, _pattern, kind in MUTATION_RULES)


def classify_mutation(method: str, path: str) -> str | None:
    for rule_method, pattern, kind in MUTATION_RULES:
        if method.upper() == rule_method and pattern.match(path):
            return kind
    return None
