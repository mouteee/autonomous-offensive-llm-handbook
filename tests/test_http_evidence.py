"""The evidence contract: what a replayable request/response pair looks like."""
import pytest
from core.http_evidence import (
    capture_request, capture_response, capture_from_requests_response,
    capture_from_aiohttp_response, _MAX_BODY_BYTES,
)


def test_truncation_is_disclosed_by_publishing_both_lengths():
    ev = capture_response(status=200, headers={"Content-Type": "text/html"},
                          body="A" * 5000)
    assert len(ev["body_snippet"]) == _MAX_BODY_BYTES     # capped
    assert ev["body_length"] == 5000                      # the truth, not the cap
    assert "truncated" not in ev                          # no boolean; the pair says it


def test_a_short_body_reports_its_own_length():
    ev = capture_response(status=200, headers={}, body="ok")
    assert ev["body_snippet"] == "ok"
    assert ev["body_length"] == 2


def test_absent_inputs_produce_absent_keys_never_empty_ones():
    """A missing key says the capture never had one; "" would claim an empty body."""
    ev = capture_response(status=200, headers={}, body="x")
    assert "headers" not in ev                             # empty dict is omitted
    req = capture_request(method="GET", url="u")
    assert "params" not in req and "headers" not in req
    assert capture_request(method="GET", url="u", params={"a": "1"})["params"] == {"a": "1"}


def test_a_header_map_emptied_by_the_filter_is_still_published():
    """The omission rule reads the input, so an emptied map is not an absent one.

    A response header map that arrives non-empty and is then emptied by the
    security-relevant allowlist is published as an empty map. That records
    something the absent key cannot: headers were captured and none of them were
    security-relevant. Only a falsy *input* is dropped, which is why this map
    survives and the one in the test above does not.
    """
    ev = capture_response(status=200, headers={"X-Trace": "abc"}, body="")
    assert ev["headers"] == {}
    assert "body_snippet" not in ev


def test_the_signatures_are_keyword_only():
    with pytest.raises(TypeError):
        capture_response(200, {}, "x")
    with pytest.raises(TypeError):
        capture_request("GET", "u")


def test_capture_survives_garbage():
    assert capture_request(method="GET", url="", headers=None, body=None)["url"] == ""
    assert capture_response(status=0, headers=None, body=None)["status"] == 0


class _RequestsLike:
    """Duck type for a requests.Response, including the attached request."""
    status_code = 403
    headers = {"Server": "nginx"}
    text = "forbidden"
    url = "https://shop.example/admin"
    request = type("Rq", (), {"method": "GET", "url": "https://shop.example/admin",
                              "headers": {"Accept": "*/*"}, "body": None})()


class _AiohttpLike:
    status = 204
    headers = {"X-Trace": "abc"}
    url = "https://shop.example/api"


def test_the_adapters_duck_type_and_return_a_pair():
    req, resp = capture_from_requests_response(_RequestsLike())
    assert req["method"] == "GET" and req["url"].endswith("/admin")
    assert resp["status"] == 403 and resp["body_snippet"] == "forbidden"
    assert resp["body_length"] == 9
    req2, resp2 = capture_from_aiohttp_response(_AiohttpLike(), body_text="")
    assert resp2["status"] == 204


def test_the_module_imports_no_http_library():
    import pathlib
    src = pathlib.Path("core/http_evidence.py").read_text(encoding="utf-8")
    assert "import requests" not in src
    assert "import aiohttp" not in src


def test_the_response_discloses_a_clipped_body_and_the_request_does_not():
    """The disclosure asymmetry, pinned on both sides.

    The module's headline property — a capped snippet published beside the true
    length — holds in ``capture_response`` only. A future reader must not carry
    it across to ``capture_request``, where a clipped body says nothing about how
    much was lost, so both sides are asserted here rather than one.
    """
    resp = capture_response(status=200, headers={}, body="A" * 5000)
    assert len(resp["body_snippet"]) == _MAX_BODY_BYTES
    assert resp["body_length"] == 5000

    clipped = capture_request(method="POST", url="u", body="A" * 5000)
    assert len(clipped["body"]) == _MAX_BODY_BYTES
    assert "body_length" not in clipped        # clipped, and nothing says by how much

    serialised = capture_request(method="POST", url="u", body={"k": "A" * 5000})
    assert len(serialised["body"]) > _MAX_BODY_BYTES   # a dict body is not capped at all


def test_the_cap_counts_characters_though_its_name_says_bytes():
    """Every site applies the constant as a string slice, not a byte budget.

    A snippet of accented text reaches the cap in characters while occupying
    twice that many bytes once encoded, so the name understates what a capture
    can occupy. The name is kept deliberately and the mismatch is asserted here so it
    cannot be mistaken for a byte bound.
    """
    snippet = capture_response(status=200, headers={}, body="é" * 5000)["body_snippet"]
    assert len(snippet) == _MAX_BODY_BYTES
    assert len(snippet.encode("utf-8")) == 2 * _MAX_BODY_BYTES


def test_the_two_header_filters_have_opposite_polarity():
    """A denylist on the request and an allowlist on the response.

    The same unrecognised header survives one capture and is dropped by the
    other, which is the fact a reader is most likely to get backwards. Asserted
    in all four combinations so neither filter can be quietly turned into the
    other.
    """
    assert capture_request(method="GET", url="u",
                           headers={"X-Custom": "v"})["headers"] == {"X-Custom": "v"}
    assert capture_request(method="GET", url="u",
                           headers={"User-Agent": "x"})["headers"] == {}
    assert capture_response(status=200, headers={"X-Custom": "v"}, body="")["headers"] == {}
    assert capture_response(status=200, headers={"Server": "nginx"},
                            body="")["headers"] == {"Server": "nginx"}


def test_the_method_is_upper_cased_and_only_a_dict_body_carries_a_content_type():
    """Two re-expressed decisions that no other test reached.

    Upper-casing keeps one exchange from being stored under two spellings, and
    the content type is stamped only where it is derived — a text body's type is
    unknown to this module, so claiming one would be an invention.
    """
    req = capture_request(method="post", url="u", body={"a": 1})
    assert req["method"] == "POST"
    assert req["content_type"] == "application/json"
    assert "content_type" not in capture_request(method="POST", url="u", body="raw")
