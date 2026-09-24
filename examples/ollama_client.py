"""Local Ollama transport for the fixture bridge."""

import json
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ENDPOINT = "http://127.0.0.1:11434/api/chat"
MAX_RESPONSE_BYTES = 65536


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_proposer(model):
    if not isinstance(model, str) or not model.strip():
        raise ValueError("an installed local model name is required")
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def propose(context):
        payload = {
            "model": model, "stream": False, "format": context["output_schema"],
            "messages": [
                {"role": "system", "content": context["instruction"]},
                {"role": "user", "content": json.dumps(context, allow_nan=False)},
            ],
            "options": {"temperature": 0, "num_predict": 256},
        }
        request = Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        with opener.open(request, timeout=60) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("model response exceeded transport byte limit")
        envelope = json.loads(body)
        if envelope.get("done") is not True or envelope.get("done_reason") == "length":
            raise ValueError("model response did not finish normally")
        return envelope["message"]["content"]

    return propose
