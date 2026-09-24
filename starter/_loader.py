"""Load a starter module, or its worked solution under STARTER_SOLUTIONS=1.

STARTER_DIR overrides where the starter files are read from; the reference
suite uses it to check the committed pristine starters without ever touching
the learner's working copies.
"""

import importlib.util
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def load(name):
    base = pathlib.Path(os.environ.get("STARTER_DIR", HERE))
    folder = base / "solutions" if os.environ.get("STARTER_SOLUTIONS") else base
    spec = importlib.util.spec_from_file_location(f"starter_{name}",
                                                  folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
