"""
Ghaf App — Metabase signed-embedding helper.

Generates short-lived signed iframe URLs for the dashboards used in the
React "Analytics & Financial Insights" tab. Requires:
  - METABASE_SECRET_KEY: the embedding secret key from
    Metabase Admin > Settings > Embedding > Static embedding
  - Each target dashboard must have "Embedding enabled" in Metabase, and
    its ID registered in app.config.METABASE_DASHBOARDS
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import jwt

from ..config import get_settings, METABASE_DASHBOARDS


def build_embed_url(dashboard_key: str, params: Optional[Dict[str, Any]] = None) -> Tuple[str, int]:
    """Returns (iframe_url, expires_in_seconds) for the given dashboard key."""
    settings = get_settings()

    if dashboard_key not in METABASE_DASHBOARDS:
        raise KeyError(f"Unknown dashboard key: {dashboard_key}")

    if not settings.METABASE_SECRET_KEY:
        raise RuntimeError(
            "METABASE_SECRET_KEY is not configured. Set it in backend/.env "
            "(Metabase Admin > Settings > Embedding > Static embedding)."
        )

    dashboard_id = METABASE_DASHBOARDS[dashboard_key]
    expires_in = settings.METABASE_TOKEN_EXPIRY_SECONDS

    payload = {
        "resource": {"dashboard": dashboard_id},
        "params": params or {},
        "exp": round(time.time()) + expires_in,
    }
    token = jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256")

    iframe_url = f"{settings.METABASE_SITE_URL}/embed/dashboard/{token}#bordered=true&titled=true"
    return iframe_url, expires_in


def list_dashboard_keys() -> list[str]:
    return list(METABASE_DASHBOARDS.keys())
