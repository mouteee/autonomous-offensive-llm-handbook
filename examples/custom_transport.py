"""A provider-neutral transport for the assembled application.

`examples/app_agent.py` already wraps one transport callable with the
proposal and verifier contracts; this module is the template for making that
transport out of YOUR model client. The whole integration surface is one
function you supply:

    def send(prompt: str) -> str:
        # One call to your model client. The prompt is a single JSON
        # document; ask the model for the JSON object it requests and
        # return the assistant's text, not the SDK's response object.
        ...

Everything provider-specific lives inside `send`: the SDK, the model name,
credentials read from your environment, timeouts and retry policy. Nothing
of that enters the packet, and nothing in the packet grants anything: the
host still parses, validates and admits every reply, executes only fixture
tools, and records refusals. Swapping `send` never changes scope, budgets
or permissions.

Runnable with no provider installed:

    python3 -m examples.custom_transport --out /tmp/custom-agent-report.json

That command runs the complete assembled application through this custom
path using an offline stand-in `send`, so you can watch the wiring work,
then replace exactly one function. With a real client, the same run is:

    from examples.custom_transport import make_transport, run

    def send(prompt):
        # return my_client.complete(model="...", input=prompt).text
        ...

    report = run(make_transport(send), out="/tmp/custom-agent-report.json")
"""

import argparse
import json
import sys
from pathlib import Path

from core.run.app import Application
from core.run.demo_app import WORLD
from .app_agent import agent_config, fake_transport, proposal_summary


def make_transport(send):
    """Wrap one `send(prompt) -> str` call as the application's transport.

    The packet the application's wrappers build (instruction, output schema,
    tool vocabulary, observations, evidence, advisory memory, validation
    error) is serialized to one deterministic JSON prompt; the model's reply
    text is returned unchanged for the host's strict parser to judge. A
    reply that is not text is refused here, because a transport that returns
    SDK objects would smuggle provider structure past the parsing boundary.
    """

    def transport(packet):
        prompt = json.dumps(packet, indent=2, sort_keys=True)
        reply = send(prompt)
        if not isinstance(reply, str):
            raise TypeError(
                "send(prompt) must return the assistant's text; got "
                f"{type(reply).__name__}")
        return reply

    return transport


def offline_send(prompt):
    """The no-provider stand-in: answers by the default fake's rules.

    It exercises this module's real path (packet to prompt to reply text)
    without any model, which is exactly what makes the template runnable
    before you have a client wired.
    """
    return fake_transport(json.loads(prompt))


def run(transport, *, out, store=None):
    """One complete assembled run through the given transport."""
    report = Application(agent_config(transport, store)).run(WORLD)
    Path(out).write_text(json.dumps(report, indent=1, sort_keys=True),
                         encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True,
                        help="where to write the run report JSON")
    parser.add_argument("--store", default=None,
                        help="optional SQLite path for durable memory")
    args = parser.parse_args(argv)

    report = run(make_transport(offline_send), out=args.out,
                 store=args.store)
    print("proposals:", json.dumps(proposal_summary(report)))
    print("completed:", report["finish"]["completed"],
          "| findings:", len(report["finish"]["report"]["run_report"]
                             ["findings"]))
    return 0 if report["finish"]["completed"] else 1


if __name__ == "__main__":
    sys.exit(main())
