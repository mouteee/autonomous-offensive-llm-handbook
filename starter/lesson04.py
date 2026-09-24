"""Lesson 4 starter: write the provider that proposes your fictional tool.

Starting state: lesson 2's starter policy declares `inspect_metadata`; the
reference session in core/run/proposals.py parses, validates and admits.
Your edit happens HERE.

The contract: `my_provider(context)` is a provider callable -- one argument,
the proposal context -- returning JSON TEXT (a string) for exactly one
hypothesis proposal:
  - kind: "metadata-disclosure"
  - surface: the name of one observation present in
    context["observations"] (pick "about_has_meta")
  - evidence: a list naming only recorded observations
  - action: tool "inspect_metadata", destination
    "https://lab.example/about", arguments {}

The observable change: `python3 -m pytest starter/lesson04_test.py -q` goes
from failing to a session report with admitted=True and the normalized action
identity your lesson 2 policy authorizes. Worked answer:
starter/solutions/lesson04.py.
"""

import json


def my_provider(context):
    raise NotImplementedError(
        "build starter/lesson04.py: return json.dumps of the hypothesis the "
        "module docstring specifies, bound to the context's observations")
