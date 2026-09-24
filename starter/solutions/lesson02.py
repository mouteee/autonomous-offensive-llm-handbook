"""Worked solution for the lesson 2 starter. Read after your own attempt."""

from core.run.policy import Policy, Tool


def build_my_policy():
    return Policy(
        reference="my-training-authorization-0001",
        origins=["https://lab.example/"],
        tools=[
            Tool(tool_id="inspect_headers", activity="passive",
                 family="fam-recon", weight=3.0, cost=1.0),
            Tool(tool_id="inspect_metadata", activity="passive",
                 requires={"has_meta": True}, family="fam-meta",
                 weight=2.0, cost=1.0),
        ],
        max_actions=6, max_model_calls=2)
