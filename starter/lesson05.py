"""Lesson 5 starter: give the tool an adapter and follow one record through.

Starting state: your lesson 2 policy declares `inspect_metadata` and lesson
4's provider proposes it. This exercise runs it: an adapter, the candidate
table, the dispatch door, and the capture your marker travels in.

The contract, two functions:
  - `metadata_adapter(url)` returns {"status": 200, "body": ...} where the
    body contains the exact marker "X-Meta-Notes: fictional-metadata-v1".
  - `run_my_plan()` builds candidates over one surface
    ({"surface_id": "about", "url": "https://lab.example/about",
      "facts": {"has_meta": True}}) with your policy, dispatches every
    eligible candidate through a Dispatcher wired with your adapter for
    inspect_metadata (reuse it for inspect_headers too), and returns
    (table, results, recorder_snapshot).

The observable change: `python3 -m pytest starter/lesson05_test.py -q` goes
from failing to a table whose eligible rows include your tool, a clean
dispatch, and a capture carrying your marker -- one record identity,
followed from declaration to evidence. Worked answer:
starter/solutions/lesson05.py.
"""

from core.run.candidates import build_candidates
from core.run.dispatch import Dispatcher
from core.run.recorder import Recorder
from core.run.records import make_run


def metadata_adapter(url):
    raise NotImplementedError(
        "build starter/lesson05.py: return a fixture response carrying the "
        "marker the module docstring specifies")


def run_my_plan():
    raise NotImplementedError(
        "build starter/lesson05.py: candidates, dispatch, and the snapshot, "
        "as the module docstring specifies")
