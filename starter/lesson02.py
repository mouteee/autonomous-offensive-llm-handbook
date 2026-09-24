"""Lesson 2 starter: declare your own policy, with one new fictional tool.

Starting state: the reference policy in core/run/policy.py is complete and its
lesson explains every field. Your edit happens HERE, in this file only.

The contract: `build_my_policy()` returns a `Policy` that
  - carries a nonempty authorization reference of your choosing,
  - authorizes exactly one origin, https://lab.example/,
  - declares the reference tool `inspect_headers` (passive, family
    "fam-recon", weight 3.0, cost 1.0), and
  - declares one NEW fictional tool: `inspect_metadata`, passive, family
    "fam-meta", weight 2.0, cost 1.0, requiring the observed field
    {"has_meta": True} -- a page must be seen to carry metadata before the
    tool is eligible,
  - under budgets max_actions=6 and max_model_calls=2.

The observable change: `python3 -m pytest starter/lesson02_test.py -q` goes
from failing (this file raises) to passing (your policy answers the door's
questions). The worked answer is starter/solutions/lesson02.py -- after your
attempt.
"""

from core.run.policy import Policy, Tool


def build_my_policy():
    raise NotImplementedError(
        "build starter/lesson02.py: return a Policy with the two tools and "
        "budgets the module docstring specifies")
