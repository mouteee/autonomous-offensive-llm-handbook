"""The graph lesson's arm comparison: one seeded episode per arm, one world.

Five arms over the same committed toy topology and the same decoy-delay world:
the toy graph learning, its degree-preserving shuffle, its density-matched
random rewiring, the no-hop control, and the toy graph frozen. The output is a
mechanism demonstration -- which arm earned what on one seed of one synthetic
world -- and the lesson forbids reading it as evidence that any topology is
better. The originating experiments' record on that question lives in the
evidence register.

Run it from the repository root:

    python3 -m core.controller.demo_graph --out /tmp/graph-demo.json

The committed copy is data/course/graph-demo.json; a sync test re-derives it.
"""

import argparse
import json
import pathlib

from .graph import GraphController, ToyGraph, random_variant, shuffled_variant
from .research import run_condition
from .worlds import make_world


SEED = 7
FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "data" / "course" / "graph-toy.json"


def build_arms(seed=SEED):
    """The five arms, every control anchored to the toy graph's own scale."""
    toy = ToyGraph.load(FIXTURE)
    anchor = toy.w95()
    return {
        "toy": GraphController(graph=toy, seed=seed, learn=True,
                               w95_anchor=anchor),
        "shuffled": GraphController(graph=shuffled_variant(toy, seed + 1000),
                                    seed=seed, learn=True, w95_anchor=anchor),
        "random": GraphController(graph=random_variant(toy, seed + 1000),
                                  seed=seed, learn=True, w95_anchor=anchor),
        "no-hop": GraphController(graph=toy, seed=seed, learn=True, hop=False,
                                  w95_anchor=anchor),
        "toy-frozen": GraphController(graph=toy, seed=seed, learn=False,
                                      w95_anchor=anchor),
    }


def run_demo():
    arms = {}
    for label, controller in build_arms().items():
        world = make_world("decoy-delay", seed=SEED)
        trace, total = run_condition(controller, world)
        families = {}
        for row in trace:
            families[row["family"]] = families.get(row["family"], 0) + 1
        arms[label] = {
            "total_reward": total,
            "chosen_families": families,
            "parity": controller.parity(),
        }
    return {
        "schema": "graph-lesson-demo/v1",
        "seed": SEED,
        "world": "decoy-delay",
        "fixture": "data/course/graph-toy.json",
        "arms": arms,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_demo(), indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
