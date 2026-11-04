from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from v import __version__
from v.core.config import load_settings


def main() -> None:
    settings = load_settings()
    llm = settings["llm"]
    base_url = llm["base_url"].rstrip("/")
    parsed = urlsplit(base_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Diagnostics only permits a loopback local inference endpoint.")

    endpoint = base_url + "/models"
    print(f"V {__version__}")
    print("Project: configured")
    print(f"Provider: {llm['provider']}")
    print(f"Endpoint: {endpoint}")
    print("Checking configured local inference server...")

    request = Request(endpoint, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
        models = payload.get("data", [])
        print("Local inference API: CONNECTED")
        print(f"Available model entries: {len(models)}")
        for model in models:
            print(f"  - {model.get('id', 'Unknown model')}")
        print("\nDiagnostic completed.")
    except (URLError, TimeoutError, OSError, ValueError) as error:
        print("Local inference API: NOT CONNECTED")
        print(f"Reason: {error}")
        print("Check that the configured local inference server is running.")
