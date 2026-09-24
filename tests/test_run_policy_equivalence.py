"""The policy's origin twin, held to the fixture lab's canonicalizer.

core/run/policy.py restates harness/runtime.py's `origin` because the
import-consistency gate keeps core/ standard-library and core-only. A restated
function is a transcription risk, so this file holds the two to identical
behavior over a shared case table -- accepted URLs canonicalize identically,
and the turned-away URLs are turned away by both.
"""

import pytest

from core.run import policy as course_policy
from harness import runtime as lab_runtime


def chapter_claim(chapter, *sentences):
    """Anchor a test to the verbatim lesson sentence(s) it backs.

    Same declaration shape as tests/test_chapter_claims.py: verify_claims.sh's
    Check C parses these decorators and goes red when a declared sentence is
    no longer present in its chapter.
    """
    def deco(fn):
        return fn
    return deco


ACCEPTED = [
    "https://lab.example/",
    "http://lab.example",
    "https://lab.example:8443/path?query=1",
    "https://LAB.Example./",
    "http://xn--nxasmq6b.example/",
    "https://bücher.example/",
]

REJECTED = [
    "ftp://lab.example/",
    "https://user:pass@lab.example/",
    "https://lab.example/#fragment",
    "https://lab.example:0/",
    "https:///nohost",
    "https://lab example/",
    "relative/path",
    "",
    "https://lab.example\\evil",
]


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "The policy's origin twin agrees with the fixture lab's canonicalizer "
    "across the shared case table.",
)
@pytest.mark.parametrize("url", ACCEPTED)
def test_accepted_urls_canonicalize_identically(url):
    assert course_policy.origin(url) == lab_runtime.origin(url)


@chapter_claim(
    "handbook/course/02-policy-and-records.md",
    "The policy's origin twin agrees with the fixture lab's canonicalizer "
    "across the shared case table.",
)
@pytest.mark.parametrize("url", REJECTED)
def test_rejected_urls_are_rejected_by_both(url):
    with pytest.raises(course_policy.PolicyError):
        course_policy.origin(url)
    with pytest.raises(lab_runtime.PolicyError):
        lab_runtime.origin(url)
