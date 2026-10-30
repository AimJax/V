"""Local Nomic embeddings through LM Studio's OpenAI-compatible API."""

from __future__ import annotations

import math


import httpx

from v.core.network import validate_local_http_url

from v.providers.errors import (
    ProviderAPIError,
    ProviderConnectionError,
    ProviderProtocolError,
)


class LMStudioEmbeddingProvider:
    """Generate Nomic document and query embeddings locally."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "text-embedding-nomic-embed-text-v1.5",
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:

        if not model or not model.strip():
            raise ValueError("An embedding model identifier is required.")

        self.base_url = validate_local_http_url(base_url)
        self.model = model.strip()
        self._owns_client = client is None

        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json"},
            trust_env=False,
        )

    async def _embed(
        self,
        texts: list[str],
        *,
        prefix: str,
    ) -> list[list[float]]:
        if not texts:
            return []

        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding input texts cannot be empty.")

        payload = {
            "model": self.model,
            "input": [f"{prefix}{text}" for text in texts],
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/embeddings",
                json=payload,
            )
        except httpx.RequestError as error:
            raise ProviderConnectionError(
                f"Could not reach local embedding API: {error}"
            ) from error

        if response.is_error:
            try:
                data = response.json()
                error = data.get("error", data)
                message = (
                    error.get("message", str(error))
                    if isinstance(error, dict)
                    else str(error)
                )
            except ValueError:
                message = response.text[:1000]

            raise ProviderAPIError(response.status_code, message)

        try:
            data = response.json()["data"]

            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError("Unexpected embedding count.")

            ordered = sorted(
                data,
                key=lambda item: item["index"],
            )

            vectors = []

            for item in ordered:
                vector = item["embedding"]

                if not isinstance(vector, list) or not vector:
                    raise ValueError("Empty embedding vector.")

                values = []

                for number in vector:
                    if isinstance(number, bool):
                        raise ValueError("Invalid embedding value.")

                    number = float(number)

                    if not math.isfinite(number):
                        raise ValueError("Non-finite embedding value.")

                    values.append(number)

                vectors.append(values)

            dimensions = len(vectors[0])

            if any(len(vector) != dimensions for vector in vectors):
                raise ValueError("Inconsistent embedding dimensions.")

            return vectors

        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ProviderProtocolError(
                f"Unexpected embedding response: {error}"
            ) from error

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Embed memory records with Nomic's document task prefix."""
        return await self._embed(
            texts,
            prefix="search_document: ",
        )

    async def embed_queries(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Embed user queries with Nomic's query task prefix."""
        return await self._embed(
            texts,
            prefix="search_query: ",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()