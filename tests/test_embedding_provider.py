import json
import unittest

import httpx

from v.memory.embedding_provider import LMStudioEmbeddingProvider
from v.providers.errors import ProviderProtocolError


class EmbeddingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_document_prefix(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))

            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2, 0.3]}
                    ]
                },
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        provider = LMStudioEmbeddingProvider(client=client)

        result = await provider.embed_documents(["I like programming."])

        self.assertEqual(
            captured["input"],
            ["search_document: I like programming."],
        )
        self.assertEqual(result, [[0.1, 0.2, 0.3]])

        await client.aclose()

    async def test_query_prefix(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.content))

            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.4, 0.5, 0.6]}
                    ]
                },
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        provider = LMStudioEmbeddingProvider(client=client)

        await provider.embed_queries(["How do I program?"])

        self.assertEqual(
            captured["input"],
            ["search_query: How do I program?"],
        )

        await client.aclose()

    async def test_multiple_vectors_are_ordered_by_index(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.4, 0.5]},
                        {"index": 0, "embedding": [0.1, 0.2]},
                    ]
                },
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        provider = LMStudioEmbeddingProvider(client=client)

        result = await provider.embed_queries(["First", "Second"])

        self.assertEqual(result, [[0.1, 0.2], [0.4, 0.5]])

        await client.aclose()

    async def test_wrong_vector_count_is_rejected(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"data": []},
            )

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        provider = LMStudioEmbeddingProvider(client=client)

        with self.assertRaises(ProviderProtocolError):
            await provider.embed_queries(["Query"])

        await client.aclose()


if __name__ == "__main__":
    unittest.main()