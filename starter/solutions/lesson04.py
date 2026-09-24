"""Worked solution for the lesson 4 starter. Read after your own attempt."""

import json


def my_provider(context):
    observations = context["observations"]
    surface = "about_has_meta" if "about_has_meta" in observations else \
        sorted(observations)[0]
    return json.dumps({
        "kind": "metadata-disclosure",
        "surface": surface,
        "evidence": [surface],
        "action": {"tool": "inspect_metadata",
                   "destination": "https://lab.example/about",
                   "arguments": {}},
    })
