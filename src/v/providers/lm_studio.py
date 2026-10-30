"""Local LM Studio provider using its OpenAI-compatible API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from v.core.network import validate_local_http_url

from v.providers.base import ChatMessage, ChatResult
from v.providers.errors import (
    ModelNotConfiguredError,
    ProviderAPIError,
    ProviderConnectionError,
    ProviderProtocolError,
)


class LMStudioProvider:
    """Communicate with a local LM Studio inference server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "",
        timeout_seconds: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = validate_local_http_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds

        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json"},
            trust_env=False,
        )

    def _messages_payload(
        self,
        messages: Sequence[ChatMessage],
    ) -> list[dict[str, str]]:
        if not messages:
            raise ValueError("At least one chat message is required.")

        allowed_roles = {"system", "user", "assistant", "tool"}
        result: list[dict[str, str]] = []

        for message in messages:
            if message.role not in allowed_roles:
                raise ValueError(f"Unsupported message role: {message.role}")

            if not isinstance(message.content, str):
                raise TypeError("Message content must be a string.")

            result.append({
                "role": message.role,
                "content": message.content,
            })

        return result

    def _resolve_model(self, model: str | None) -> str:
        selected = model or self.model

        if not selected:
            raise ModelNotConfiguredError(
                "No chat model is configured. Select a conversational "
                "model in LM Studio and configure its model identifier."
            )

        return selected

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            error = payload.get("error", payload)

            if isinstance(error, dict):
                return str(error.get("message", error))

            return str(error)
        except (ValueError, AttributeError):
            return response.text[:1000] or "Unknown API error."

    @staticmethod
    def _extract_text(value: object) -> str:
        if isinstance(value, str):
            return value

        if isinstance(value, list):
            parts: list[str] = []

            for item in value:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)

            return "".join(parts)

        return ""

    def _check_response(self, response: httpx.Response) -> None:
        if response.is_error:
            raise ProviderAPIError(
                response.status_code,
                self._error_message(response),
            )

    def _request_error(self, error: httpx.RequestError) -> ProviderConnectionError:
        return ProviderConnectionError(
            f"Could not reach LM Studio at {self.base_url}: {error}"
        )

    async def list_models(self) -> list[str]:
        """Return models currently exposed by the local API."""
        try:
            response = await self._client.get(
                f"{self.base_url}/models"
            )
        except httpx.RequestError as error:
            raise self._request_error(error) from error

        self._check_response(response)

        try:
            payload = response.json()
            entries = payload["data"]

            if not isinstance(entries, list):
                raise TypeError("Model data is not a list.")

            models = []

            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    models.append(entry["id"])

            return models

        except (ValueError, KeyError, TypeError) as error:
            raise ProviderProtocolError(
                f"Unexpected response from LM Studio model endpoint: {error}"
            ) from error

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Send a non-streaming conversation request."""
        payload = {
            "model": self._resolve_model(model),
            "messages": self._messages_payload(messages),
            "temperature": temperature,
            "stream": False,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            )
        except httpx.RequestError as error:
            raise self._request_error(error) from error

        self._check_response(response)

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]

            return ChatResult(
                content=self._extract_text(message.get("content")),
                model=data.get("model", payload["model"]),
                finish_reason=choice.get("finish_reason"),
                usage=data.get("usage"),
            )

        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderProtocolError(
                f"Unexpected chat response from LM Studio: {error}"
            ) from error

    async def _iterate_stream(
        self,
        payload: dict,
    ) -> AsyncIterator[str]:
        """Parse server-sent events from the chat completion endpoint."""
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Accept": "text/event-stream"},
            ) as response:
                self._check_response(response)

                async for line in response.aiter_lines():
                    line = line.strip()

                    if not line or line.startswith(":"):
                        continue

                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if data == "[DONE]":
                        return

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as error:
                        raise ProviderProtocolError(
                            "LM Studio returned invalid streaming JSON."
                        ) from error

                    if isinstance(event, dict) and "error" in event:
                        error = event["error"]

                        if isinstance(error, dict):
                            message = str(error.get("message", error))
                        else:
                            message = str(error)

                        raise ProviderProtocolError(message)

                    choices = event.get("choices", [])

                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    text = self._extract_text(delta.get("content"))

                    if text:
                        yield text

        except httpx.RequestError as error:
            raise self._request_error(error) from error

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream generated text as it arrives."""
        payload = {
            "model": self._resolve_model(model),
            "messages": self._messages_payload(messages),
            "temperature": temperature,
            "stream": True,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        return self._iterate_stream(payload)

    async def aclose(self) -> None:
        """Close the HTTP client when this provider owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> LMStudioProvider:
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()