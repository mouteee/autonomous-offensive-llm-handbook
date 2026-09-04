"""
core/http_evidence.py — the evidence contract

A finding whose exchange cannot be replayed is not evidence; it is an opinion
with a URL attached. Every layer downstream of a detector reads the dicts built
here — the severity governor grades a finding on whether the request and the
response both survived, and a human reviewer either reproduces the exchange from
them or writes the finding off — which is why the capture shape is settled before
the first detector rather than after the first argument about a severity.

**Truncation is disclosed by publishing a pair, never a flag — in
``capture_response``.** There, ``body_snippet`` is capped at ``_MAX_BODY_BYTES``
and ``body_length`` carries the length of the body that was handed in, uncapped.
A ``truncated`` boolean would tell a reader the evidence is incomplete; the pair
tells them by how much, and that is the difference between knowing a body was
clipped and knowing whether the clipped part could have mattered: a snippet at
the cap beside a length just past it is very nearly the whole exchange, while the
same snippet beside a length in the megabytes is a lead rather than a proof. A
single bit cannot separate those.

**``capture_request`` does not do this, and a reader must not carry the guarantee
across.** A text request body is capped at the same constant with no length
published beside it, so it is clipped silently — the very failure the paragraph
above says the design avoids — while a dict body is serialised whole and not
capped at all. Both are reproduced from the underlying source rather than chosen
here, and they are stated rather than smoothed over because a contract that reads
uniformly and is not would mislead exactly where evidence matters.

**The constant's name says bytes and every site applies it as a string slice.**
So a body of multi-byte characters is cut at that many CHARACTERS, and the result
can occupy more storage than the name implies: accented text hits the cap in
characters while the same snippet occupies twice that many bytes once
encoded. The name is kept
because it is the interface the callers and the tests import; the mismatch is
disclosed here rather than quietly corrected.

**A falsy input is omitted rather than emitted empty, with the exceptions named
here.** In ``capture_response`` no key is written for a header map, body or URL
that arrived absent or empty: ``"body": ""`` reads as a response that came back
with nothing in it, whereas a missing ``body_snippet`` says the capture never
held one, and this encoding refuses to collapse facts that differ. In
``capture_request`` the rule covers ``headers``, ``body`` and ``params`` but NOT
``method`` and ``url``, which are written unconditionally — an empty URL is
published as an empty string, and the suite pins that behaviour rather than the
omission.

**Both header filters can publish an empty map, by opposite mechanisms.** The
rule reads the input and not the filter's result, so a map that arrives populated
and is emptied by filtering survives as an empty map. That happens at both sites,
and the filters are mirror images of each other: the request filter is a
DENYLIST, stripping the headers that describe the client and keeping everything
else, while the response filter is an ALLOWLIST, keeping a named set of
security-relevant headers and dropping everything else. A custom header therefore
survives a request capture and is dropped from a response capture, and a reader
who learns one policy will get the other exactly backwards.

**The adapters duck-type deliberately.** ``capture_from_requests_response`` and
``capture_from_aiohttp_response`` consume objects produced by HTTP client
libraries, and this module imports neither those libraries nor anything else
outside the standard library: each adapter reads the attributes it needs off
whatever object it is handed. That is what keeps ``core/`` stdlib-only, and it
is also why both adapters can be exercised by a plain class defined in a test
file, with no client library installed at all.

Public API
----------
``capture_request``                — build a request dict from explicit fields.
``capture_response``               — build a response dict from explicit fields.
``capture_from_requests_response`` — adapter; returns a ``(request, response)`` pair.
``capture_from_aiohttp_response``  — adapter; same pair, body text passed in.
``_MAX_BODY_BYTES``                — the snippet cap.
"""
import json
from typing import Any, Dict, Optional, Tuple

# Slice bound for stored body text. The module docstring covers the unit this
# name gets wrong, and how each capture function applies it.
_MAX_BODY_BYTES = 4096

# Request headers that describe the client rather than the target. A reviewer
# replaying the exchange supplies their own, so carrying these lengthens every
# capture without making any of them more replayable.
_CLIENT_ONLY_HEADERS = frozenset({"user-agent", "accept-encoding", "connection"})

# Response headers a finding can turn on: the ones that grant something, refuse
# something, name the software, or set the policy a browser will enforce.
_SECURITY_RELEVANT_HEADERS = frozenset({
    "content-type", "server", "x-powered-by",
    "x-frame-options", "x-content-type-options", "x-xss-protection",
    "content-security-policy", "strict-transport-security",
    "permissions-policy", "referrer-policy",
    "access-control-allow-origin", "access-control-allow-credentials",
    "set-cookie", "location", "www-authenticate",
})


def capture_request(
    *,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Any = None,
    params: Optional[Dict[str, str]] = None,
) -> Dict:
    """Build a request dict from fields the caller already holds.

    Keyword-only, and that is enforced rather than stylistic: at a capture site
    the argument names are the documentation, and a positional
    ``("GET", url, None, None)`` is unreadable in a diff months later.
    ``method`` is upper-cased, so ``get`` and ``GET`` cannot leave two spellings
    of one exchange behind them.

    ``method`` and ``url`` are written unconditionally, so an empty URL is
    published as an empty string rather than omitted; the omission rule covers
    only ``headers``, ``body`` and ``params``.

    Headers that describe the client are dropped — a denylist, the mirror of the
    allowlist in ``capture_response``, so a header this module does not recognise
    survives here and would not survive there. A dict body is serialised to JSON
    and stamped with ``content_type``, since a body whose content type is unknown
    does not replay, and the serialised form is stored whole so that it stays
    parseable; a body arriving as text, or coerced to text, is capped at
    ``_MAX_BODY_BYTES`` instead.

    **A capped request body publishes no length beside it**, so unlike a response
    snippet it is clipped with nothing recording by how much. That is the
    underlying source's behaviour, reproduced rather than repaired, and it is the
    reason the module docstring scopes the disclosed-truncation guarantee to
    ``capture_response`` alone.
    """
    captured: Dict[str, Any] = {"method": method.upper(), "url": url}

    if headers:
        captured["headers"] = {
            name: value for name, value in headers.items()
            if name.lower() not in _CLIENT_ONLY_HEADERS
        }

    if body:
        if isinstance(body, dict):
            captured["body"] = json.dumps(body)
            captured["content_type"] = "application/json"
        elif isinstance(body, str):
            captured["body"] = body[:_MAX_BODY_BYTES]
        else:
            captured["body"] = str(body)[:_MAX_BODY_BYTES]

    if params:
        captured["params"] = params

    return captured


def capture_response(
    *,
    status: int,
    headers: Optional[Dict[str, str]] = None,
    body: str = "",
    url: Optional[str] = None,
) -> Dict:
    """Build a response dict from fields the caller already holds.

    ``status`` is always written, including zero, because a capture that
    recorded a failure to reach the target is a different fact from one that
    recorded nothing at all. The body becomes ``body_snippet``, capped at
    ``_MAX_BODY_BYTES``, beside ``body_length``, which is the uncapped length —
    the module docstring says why that pair replaces a flag.

    Headers are narrowed to a security-relevant allowlist, because a capture
    stored beside every finding has to stay small enough that somebody reads it.

    The omission rule reads the input and not the filter's result: a header map
    that arrives empty is left out of the output entirely, while a map that
    arrives populated and is emptied by the allowlist is published as an empty
    map. That is deliberate. The empty map records something the absent key
    cannot — headers were captured and none of them were security-relevant — and
    a reader who cannot tell those apart cannot tell a hardened response from an
    unexamined one.

    ``capture_request`` reaches the same empty map by the opposite rule, so this
    is not the only site that can produce one: its filter is a denylist and this
    one is an allowlist, which is why a custom header survives there and is
    dropped here.
    """
    captured: Dict[str, Any] = {"status": status}

    if headers:
        captured["headers"] = {
            name: value for name, value in headers.items()
            if name.lower() in _SECURITY_RELEVANT_HEADERS
        }

    if body:
        captured["body_snippet"] = body[:_MAX_BODY_BYTES]
        captured["body_length"] = len(body)

    if url:
        captured["url"] = url

    return captured


def capture_from_requests_response(
    response,
    *,
    method: Optional[str] = None,
    request_body: Any = None,
) -> Tuple[Dict, Dict]:
    """Adapt a ``requests``-shaped response into a ``(request, response)`` pair.

    Duck-typed and never imported: reads ``status_code`` — falling back to
    ``status`` — plus ``headers``, ``text`` and ``url``, and, when a prepared
    request is attached, ``request.method``, ``request.url``,
    ``request.headers`` and ``request.body``. The method is taken from the
    explicit argument first, then from the attached request, then defaults to
    ``GET``, so a caller holding only a response need not thread it through.

    The attached-request branch dereferences ``request.url`` directly, so an
    object carrying a ``request`` without one raises ``AttributeError`` instead
    of capturing half an exchange. A request whose URL is unknown is not a
    replayable request, and a test double missing it fails here rather than at
    review time.
    """
    attached = getattr(response, "request", None)
    resolved_method = (
        method
        or (getattr(attached, "method", None) if attached is not None else None)
        or "GET"
    )

    if attached is not None:
        request_headers = dict(attached.headers) if attached.headers else None
        captured_request = capture_request(
            method=resolved_method,
            url=str(attached.url),
            headers=request_headers,
            body=request_body or attached.body,
        )
    else:
        captured_request = capture_request(
            method=resolved_method,
            url=str(response.url),
            headers=None,
            body=request_body,
        )

    if hasattr(response, "status_code"):
        status = response.status_code
    else:
        status = response.status

    captured_response = capture_response(
        status=status,
        headers=dict(response.headers) if response.headers else None,
        body=response.text if hasattr(response, "text") else "",
        url=str(response.url),
    )
    return captured_request, captured_response


def capture_from_aiohttp_response(
    response,
    *,
    body_text: str = "",
    method: str = "GET",
    request_body: Any = None,
) -> Tuple[Dict, Dict]:
    """Adapt an ``aiohttp``-shaped response into a ``(request, response)`` pair.

    Duck-typed like its sibling, and asymmetric for a reason the caller cannot
    design away: an aiohttp body is readable only from a coroutine, so the text
    arrives as ``body_text`` rather than being read off the object. Request
    headers come from ``request_info`` when the object carries one, which is why
    an object without it captures a request with no headers instead of raising.
    """
    request_info = getattr(response, "request_info", None)
    captured_request = capture_request(
        method=method,
        url=str(response.url),
        headers=dict(request_info.headers) if request_info is not None else None,
        body=request_body,
    )
    captured_response = capture_response(
        status=response.status,
        headers=dict(response.headers) if response.headers else None,
        body=body_text,
        url=str(response.url),
    )
    return captured_request, captured_response
