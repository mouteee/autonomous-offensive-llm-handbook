"""Scope as a function: it returns a fact, and its fail-open paths are named."""
import pytest
from core.scope_guard import ScopeGuard


def test_out_of_scope_beats_in_scope_for_the_same_host():
    g = ScopeGuard(target="https://shop.example", out_of_scope=["pay.shop.example"],
                   in_scope=["pay.shop.example"])
    assert g.is_in_scope("https://pay.shop.example/x") is False


def test_the_registrable_default_admits_subdomains_of_the_target():
    g = ScopeGuard(target="https://shop.example")
    assert g.is_in_scope("https://api.shop.example/x") is True
    assert g.is_in_scope("https://other.example/x") is False


def test_both_fail_open_paths_and_only_those(monkeypatch):
    """The two paths the module names, plus the exhaustiveness part of "only".

    "Only those" was the undefended part. The seeded-and-enabled arm probed a
    single two-label host, so a third fail-open keyed on any other host shape --
    a single-label intranet name is the obvious one -- left this test green
    while silently admitting a host the caller had written down as out of scope.
    The arm below therefore probes one host of each label count with an explicit
    exclusion declared, which is what a third fail-open would overrule.

    The unseeded arm probes the CONDITION and not the constructor argument: the
    guard is unseeded when its base came out empty, and an absent target and a
    target that reduces to no host both produce that.
    """
    monkeypatch.setenv("HARNESS_SCOPE_TRACKING", "0")
    assert ScopeGuard(target="https://shop.example").is_in_scope("https://anything.else/") is True
    monkeypatch.setenv("HARNESS_SCOPE_TRACKING", "1")
    for unseeded in ("", "   ", "/some/path", "."):                                     # unseeded
        assert ScopeGuard(target=unseeded).is_in_scope("https://anything.else/") is True
    # Seeded and enabled: no third fail-open, at any label count, and not even
    # for a host the caller declared out of scope.
    g = ScopeGuard(target="https://shop.example",
                   out_of_scope=["intranet", "anything.else"])
    assert g.is_in_scope("http://intranet/admin") is False
    assert g.is_in_scope("https://anything.else/") is False
    assert g.is_in_scope("https://deep.nested.other.example/x") is False


def test_a_url_with_no_host_is_not_judged():
    """Measured rather than left open: nothing host-like means the guard does
    not block. An earlier draft asserted `is True or is False`, which accepts
    every answer and therefore tests nothing."""
    g = ScopeGuard(target="https://shop.example")
    assert g.is_in_scope("/relative/path") is True
    assert g.is_in_scope("") is True


def test_the_registrable_defect_reaches_a_two_label_public_suffix_as_well():
    """The dramatic variant chapter 04 names, made executable. A target under a
    two-label public suffix derives that suffix as the base, so an unrelated
    company's site under it answers in-scope. Asserted as current behaviour, for
    the same reason as the structural case: a fix should turn this red on
    purpose."""
    g = ScopeGuard(target="https://shop.co.uk")
    assert g.is_in_scope("https://unrelated.co.uk/") is True     # DEFECT


def test_host_extraction_tolerates_ports_paths_case_and_trailing_dots():
    g = ScopeGuard(target="https://shop.example")
    assert g.is_in_scope("https://api.shop.example:8443/deep/path?q=1") is True
    assert g.is_in_scope("HTTPS://API.SHOP.EXAMPLE./x") is True


def test_the_registrable_defect_is_present_and_named():
    """DEFECT, disclosed in chapter 04: _registrable() takes the last two labels,
    so a three-label target admits its siblings and its parent. Asserted as
    current behaviour so that FIXING it turns this test red deliberately."""
    g = ScopeGuard(target="https://app.corp.example")
    assert g.is_in_scope("https://other.corp.example/x") is True     # sibling: defect
    assert g.is_in_scope("https://corp.example/x") is True           # parent: defect
