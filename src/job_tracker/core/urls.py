"""Normalising offer URLs, so the same offer is always stored under one spelling (D-05).

The unique constraint ``uq_job_offers_url`` compares URLs character by character, while
links copied from job boards differ in letter case, tracking parameters, the fragment, the
default port or a trailing slash. The rules are listed in ``docs/decisions.md`` ("Job
offer" → "URL normalisation").
"""

from urllib.parse import urlsplit, urlunsplit

# Query parameters that only track where a click came from; every ``utm_*`` parameter is
# removed as well (see ``_is_tracking_query_param``). Compared in lower case.
TRACKING_QUERY_PARAMS: frozenset[str] = frozenset(
    [
        "gclid",
        "fbclid",
        "refid",
        "trackingid",
        "trk",
    ]
)

# The port a browser uses when an https URL names none, so ":443" adds nothing.
HTTPS_DEFAULT_PORT: int = 443


def _is_tracking_query_param(param: str) -> bool:
    """Return whether the query parameter named ``param`` is a tracking parameter.

    The name is compared in lower case, so ``UTM_Source`` counts as ``utm_source``.
    """
    return param.lower() in TRACKING_QUERY_PARAMS or param.lower().startswith("utm_")


def normalise_offer_url(url: str) -> str:
    """Return ``url`` in its canonical form, keeping what identifies the offer.

    ``url`` must already be validated: an ``https`` URL with a host. The function only
    rewrites it:

    - surrounding whitespace is trimmed;
    - the scheme and the host are lower-cased; the path keeps its case;
    - credentials (``user:password@``), the default port ``:443``, trailing slashes and the
      fragment (``#...``) are removed;
    - tracking query parameters and empty ones (``&&``) are removed; the other parameters
      are kept, unchanged and in their order.

    Normalising a normalised URL returns it unchanged, so the function can safely run more
    than once on the same value (in the schema and in the service).

    Raises ``ValueError`` when the URL has no host, i.e. when it was not validated first.
    """

    url_parts = urlsplit(url.strip())
    if url_parts.hostname is None:
        raise ValueError("URL has no host")
    scheme = url_parts.scheme.lower()
    host = url_parts.hostname.lower()
    port = url_parts.port
    netloc = host if port is None or port == HTTPS_DEFAULT_PORT else f"{host}:{port}"
    path = url_parts.path.rstrip("/")
    query = "&".join(
        fragment
        for fragment in url_parts.query.split("&")
        if fragment != "" and not _is_tracking_query_param(fragment.split("=", 1)[0])
    )
    return urlunsplit((scheme, netloc, path, query, ""))
