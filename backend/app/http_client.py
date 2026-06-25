"""Shared httpx client factory.

Centralizes the outbound-HTTP security posture in one place. The key setting is
TLS certificate verification: it is ON by default and only disabled via
TLS_VERIFY=false (e.g. behind a trusted intercepting proxy). Building clients
through this factory means every caller inherits that posture consistently,
instead of each one hand-setting `verify=False` (which silently disabled TLS
verification across the news / article-extraction fetches).
"""

import httpx

from .config import settings


def make_http_client(**kwargs) -> httpx.Client:
    """Build an httpx.Client with TLS verification governed by settings.tls_verify.

    Accepts any httpx.Client keyword args (headers, timeout, follow_redirects, …).
    A caller that passes an explicit `verify` still wins — the factory only
    supplies the secure default when the caller gives none.
    """
    kwargs.setdefault("verify", settings.tls_verify)
    return httpx.Client(**kwargs)
