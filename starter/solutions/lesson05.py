"""Worked solution for the lesson 5 starter. Read after your own attempt."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.run.candidates import build_candidates
from core.run.dispatch import Dispatcher
from core.run.recorder import Recorder
from core.run.records import make_run

from starter._loader import load

build_my_policy = load("lesson02").build_my_policy


def metadata_adapter(url):
    return {"status": 200,
            "body": f"fixture page {url}\nX-Meta-Notes: fictional-metadata-v1"}


def run_my_plan():
    policy = build_my_policy()
    run = make_run(policy.snapshot(), {"world": "starter-metadata"})
    recorder = Recorder(run, policy)
    surfaces = [{"surface_id": "about", "url": "https://lab.example/about",
                 "facts": {"has_meta": True}}]
    table = build_candidates(policy=policy, surfaces=surfaces)
    dispatcher = Dispatcher(recorder, policy,
                            {"inspect_metadata": metadata_adapter,
                             "inspect_headers": metadata_adapter})
    results = [dispatcher.dispatch(c.features["tool"],
                                   c.features["destination"])
               for c in table["eligible"]]
    return table, results, recorder.snapshot()
