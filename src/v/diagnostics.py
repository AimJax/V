"""Local runtime diagnostics for V."""

from __future__ import annotations

import httpx

from v import __version__
from v.core.config import load_settings
from v.core.network import NetworkPolicy


def main() -> int:
    settings = load_settings()
    llm = settings["llm"]

    try:
        network_policy = NetworkPolicy.from_settings(settings)
        base_url = network_policy.authorize_local_endpoint(
            llm.get("base_url", "")
        )
    except (TypeError, ValueError) as error:
        print(f"V {__version__}")
        print("LM Studio API: REFUSED")
        print(f"Reason: {error}")
        return 1

    endpoint = base_url + "/models"

    print(f"V {__version__}")
    print("Project: configured")
    print(f"Provider: {llm['provider']}")
    print(f"Network policy: {network_policy.mode_label}")
    print(f"Endpoint: {endpoint}")
    print("Checking local inference server...")

    try:
        with httpx.Client(
            timeout=5.0,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(
                endpoint,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Model endpoint returned an invalid JSON object.")

        models = payload.get("data", [])

        if not isinstance(models, list):
            raise ValueError("Model endpoint returned an invalid model list.")

        print("LM Studio API: CONNECTED")
        print(f"Available model entries: {len(models)}")

        for model in models:
            if isinstance(model, dict):
                print(f"  - {model.get('id', 'Unknown model')}")

        print("\nDiagnostic completed.")
        return 0

    except (httpx.HTTPError, ValueError, TypeError) as error:
        print("LM Studio API: NOT CONNECTED")
        print(f"Reason: {error}")
        print("Check that LM Studio's local server is running.")
        return 1
