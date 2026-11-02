import json
import unittest

import httpx

from v.providers.base import ChatMessage
from v.providers.errors import ModelNotConfiguredError
from v.providers.lm_studio import LMStudioProvider


class LMStudioProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.last_request = None

        def handler(request):
            self.last_request = request

            if request.url.path == "/v1/models":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "test-chat-model"},
                            {"id": "test-embedding-model"},
                        ]
                    },
                )

            if request.url.path == "/v1/chat/completions":
                payload = json.loads(request.content)

                if payload.get("stream"):
                    events = [
                        {"choices": [{"delta": {"content": "Hello"}}]},
                        {"choices": [{"delta": {"content": " there."}}]},
                    ]

                    content = "".join(
                        f"data: {json.dumps(event)}\n\n"
                        for event in events
                    )
                    content += "data: [DONE]\n\n"

                    return httpx.Response(
                        200,
                        headers={"content-type": "text/event-stream"},
                        content=content,
                    )

                return httpx.Response(
                    200,
                    json={
                        "model": "test-chat-model",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "Hello from V."
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 4,
                        },
                    },
                )

            return httpx.Response(404, json={"error": "Not found"})

        self.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        self.provider = LMStudioProvider(
            model="test-chat-model",
            client=self.client,
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_list_models(self):
        models = await self.provider.list_models()

        self.assertEqual(
            models,
            ["test-chat-model", "test-embedding-model"],
        )

    async def test_chat(self):
        result = await self.provider.chat([
            ChatMessage(role="user", content="Hello V")
        ])

        self.assertEqual(result.content, "Hello from V.")
        self.assertEqual(result.model, "test-chat-model")
        self.assertEqual(result.finish_reason, "stop")
        self.assertIsNotNone(result.usage)

        body = json.loads(self.last_request.content)
        self.assertFalse(body["stream"])
        self.assertEqual(body["messages"][0]["content"], "Hello V")

    async def test_chat_supports_json_object_response_format(self):
        await self.provider.chat(
            [ChatMessage(role="user", content="Return JSON")],
            response_format={"type": "json_object"},
        )

        body = json.loads(self.last_request.content)
        self.assertEqual(body["response_format"], {"type": "json_object"})

    async def test_streaming_chat(self):
        chunks = []

        async for chunk in self.provider.stream_chat([
            ChatMessage(role="user", content="Say hello")
        ]):
            chunks.append(chunk)

        self.assertEqual("".join(chunks), "Hello there.")

    async def test_remote_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            LMStudioProvider(
                base_url="https://example.com/v1",
                model="test",
            )

    async def test_chat_requires_a_model(self):
        provider = LMStudioProvider(
            client=self.client,
            model="",
        )

        with self.assertRaises(ModelNotConfiguredError):
            await provider.chat([
                ChatMessage(role="user", content="Hello")
            ])

    async def test_empty_messages_are_rejected(self):
        with self.assertRaises(ValueError):
            await self.provider.chat([])


if __name__ == "__main__":
    unittest.main()