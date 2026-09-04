"""ScopeGuard — the scope decision as a function: a URL in, a boolean out.

Read this paragraph before you copy this file, because it travels without the
chapter that explains it. Admission is computed at the registrable domain, which
this module derives as the last two dot-separated labels of the hostname, and
never at the host the scan was actually pointed at. A target of
`app.corp.example` yields a base of `corp.example`, so `other.corp.example` and
`corp.example` both answer in-scope. That is the structural case, and it holds
for every target whose hostname carries three or more labels. The dramatic case
is a target under a two-label public suffix: `shop.co.uk` yields a base of
`co.uk`, and an unrelated company's site under that suffix answers in-scope.
A public-suffix list fixes the dramatic case and leaves the structural case
exactly as it is. Neither fix is in this code. Chapter 04 publishes both cases,
the cost of each, and the reasoning.

The operator whose system this re-expresses works to a narrower discipline than
that: test the host you were handed. This module's default admission is wider
than that discipline, and wider as a fact rather than a possibility. It admits
exactly the hosts whose own last two labels equal the base, so for any target
carrying a dot it admits hosts the operator would not have touched: the target's
subdomains at two labels, and at three or more labels the target's siblings and
the base host itself. A run that means literal-host testing gets it from
somewhere other than this default. Narrowing per engagement is manual, and the
out-of-scope list is the only one that can take admission away: an in-scope
pattern only ever adds.

Distinct in kind from a program-database scope tracker, which decides from a
bounty program's registered assets and answers no for any host no program
covers — a target typed on a command line among them. This guard is seeded from
the scan's own target instead, so a bare target is judged rather than refused.
Neither authorises on the other's behalf, and this one authorises nothing at
all: it answers whether a URL is inside the scope it was given.

Precedence, in this order: an out-of-scope pattern match answers no, then an
in-scope pattern match answers yes, then the answer is whether the URL's
registrable domain equals the base. Out-of-scope is consulted before in-scope,
so a host named on both lists answers no. That ordering is the safety property
of the whole module: consult the lists the other way round and the same pair of
declarations admits the host the operator wrote down to exclude.

Two fail-open paths, both fixed before any URL is seen: the guard is disabled
when the `AUTOMATOR_SCOPE_TRACKING` environment variable is set to `0`, and it
is unseeded when it has no base. Unseeded is a statement about the base and not
about the argument: the base is empty when the target is empty and also when the
target reduces to no host, so a caller that checked only for a missing target
has not prevented the second path. On either path every URL answers in-scope,
and the out-of-scope list cannot take that back — both are read before it is.

One further non-judgement is per URL and is named here rather than left to be
discovered: a URL that yields no host — a relative path, an empty string —
answers in-scope because the comparison has no left-hand side. That is the
whole set. A seeded and enabled guard handed a URL with a host in it always
reaches the three questions above.

`is_in_scope` returns a fact. It logs no suggestion, asks no model, and has no
partial answer.
"""
from __future__ import annotations

import fnmatch
import os
from typing import List, Optional
from urllib.parse import urlparse

_ENV_SWITCH = "AUTOMATOR_SCOPE_TRACKING"
_OFF = "0"


def _host_of(url_or_host: str) -> str:
    """Reduce a URL or a bare authority to a bare lowercase hostname.

    The result is a string in every case, never None: an input with no host in
    it — the empty string, a relative path — reduces to the empty string, which
    is the value `is_in_scope` reads as nothing to judge.

    A `://` in the input routes it through `urlparse`, whose hostname already
    drops the userinfo, the port and the path. Anything else, and anything
    `urlparse` returns no hostname for, is cut at the first `/` and then at the
    first `:`. Case and a trailing root dot are removed last, so both are gone
    before any comparison sees the host and neither `_matches` nor the
    registrable-domain check has to handle them. The lowercasing is there for the
    second branch: `urlparse` already lowercases the hostname it returns.
    """
    text = (url_or_host or "").strip()
    if not text:
        return ""
    host = urlparse(text).hostname if "://" in text else ""
    if not host:
        host = text.split("/", 1)[0].split(":", 1)[0]
    return host.lower().strip(".")


def _registrable(host: str) -> str:
    """The last two dot-separated labels of a host, or the whole host below two.

    That is the entire rule. It counts labels and checks no public-suffix list,
    so the base it derives is a function of how many dots the hostname happens
    to contain — which is the disclosed defect the module docstring opens with.
    """
    host = _host_of(host)
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _matches(host: str, pattern: str) -> bool:
    """True when the host equals the pattern, ends with a dot and the pattern,
    or matches it as a shell-style glob; False otherwise.

    Those three are the whole match condition. They overlap rather than
    partition it: a pattern carrying no wildcard already matches its own host as
    a glob, so no one of the three is the only route to a True. The pattern is
    lowercased and stripped of a trailing dot here as well as at construction,
    so a pattern handed straight to this helper is treated the same as one that
    arrived through `ScopeGuard`.
    """
    p = pattern.lower().strip(".")
    if host == p or host.endswith("." + p):
        return True
    return fnmatch.fnmatch(host, p)


class ScopeGuard:

    def __init__(self, target: str = "", out_of_scope: Optional[List[str]] = None,
                 in_scope: Optional[List[str]] = None):
        self.enabled = os.getenv(_ENV_SWITCH, "1").strip() != _OFF
        self.base = _registrable(target) if target else ""
        self.out_of_scope = [p.lower().strip(".") for p in (out_of_scope or [])]
        self.in_scope = [p.lower().strip(".") for p in (in_scope or [])]

    def is_in_scope(self, url: str) -> bool:
        """Is this URL inside the scope this guard was constructed with?

        The two fail-open conditions are read before the URL is: a disabled
        guard and an unseeded one answer True for everything, and each is one
        of the two the module docstring names. A URL yielding no host answers
        True as well, having nothing to compare.

        Then the three questions, in the order the module docstring fixes:
        out-of-scope, in-scope, registrable domain against the base. The first
        loop returns False, so an out-of-scope pattern decides the answer for a
        host that a later in-scope pattern would have admitted.
        """
        if not self.enabled or not self.base:
            return True
        host = _host_of(url)
        if not host:
            return True
        if any(_matches(host, pattern) for pattern in self.out_of_scope):
            return False
        if any(_matches(host, pattern) for pattern in self.in_scope):
            return True
        return _registrable(host) == self.base
