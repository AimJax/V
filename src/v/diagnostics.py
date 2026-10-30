from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from v import __version__
from v.core.config import load_settings


def main() -> None:
    settings = load_settings()
    llm = settings["llm"]

    endpoint = llm["base_url"].rstrip("/") + "/models"

    print(f"V {__version__}")
    print(f"Project: configured")
    print(f"Provider: {llm['provider']}")
    print(f"Endpoint: {endpoint}")
    print("Checking local inference server...")

    request = Request(
        endpoint,
        headers={"Accept": "application/json"},
    )

    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)

        models = payload.get("data", [])

        print("LM Studio API: CONNECTED")
        print(f"Available model entries: {len(models)}")

        for model in models:
            print(f"  - {model.get('id', 'Unknown model')}")

        print("\nDiagnostic completed.")
    except (URLError, TimeoutError, OSError, ValueError) as error:
        print("LM Studio API: NOT CONNECTED")
        print(f"Reason: {error}")
        print("Check that LM Studio's local server is running.")