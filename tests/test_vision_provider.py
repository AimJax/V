import base64
import json
import unittest

import httpx

from v.providers.errors import ProviderAPIError, ProviderProtocolError
from v.vision.lm_studio import LMStudioVisionProvider


class LMStudioVisionProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.last_request = None

        def handler(request):
            self.last_request = request
            if request.url.path != "/v1/chat/completions":
                return httpx.Response(404, json={"error": "Not found"})
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "A small red car on a road."}}
                    ]
                },
            )

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.provider = LMStudioVisionProvider(
            model="local-vision-model",
            client=self.client,
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_image_is_sent_as_openai_compatible_data_url(self):
        image = b"sample-image-bytes"
        result = await self.provider.analyze(
            image,
            mime_type="image/png",
            prompt="What is visible?",
        )

        self.assertEqual(result, "A small red car on a road.")
        payload = json.loads(self.last_request.content)
        self.assertEqual(payload["model"], "local-vision-model")
        self.assertFalse(payload["stream"])
        image_part = payload["messages"][0]["content"][1]
        self.assertEqual(image_part["type"], "image_url")
        self.assertEqual(
            image_part["image_url"]["url"],
            "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
        )

    async def test_remote_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            LMStudioVisionProvider(
                base_url="https://example.com/v1",
                model="vision",
            )

    async def test_requires_explicit_model(self):
        with self.assertRaises(ValueError):
            LMStudioVisionProvider(model=" ")

    async def test_rejects_unsupported_mime_type(self):
        with self.assertRaises(ValueError):
            await self.provider.analyze(b"image", mime_type="image/gif")

    async def test_rejects_oversized_image_before_network_request(self):
        provider = LMStudioVisionProvider(
            model="vision",
            max_image_bytes=3,
            client=self.client,
        )
        with self.assertRaises(ValueError):
            await provider.analyze(b"1234", mime_type="image/jpeg")
        self.assertIsNone(self.last_request)

    async def test_rejects_empty_model_response(self):
        def handler(_request):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": " "}}]},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = LMStudioVisionProvider(model="vision", client=client)
        try:
            with self.assertRaises(ProviderProtocolError):
                await provider.analyze(b"img", mime_type="image/jpeg")
        finally:
            await client.aclose()

    async def test_surfaces_local_model_api_errors(self):
        def handler(_request):
            return httpx.Response(400, json={"error": {"message": "Model is text-only"}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = LMStudioVisionProvider(model="vision", client=client)
        try:
            with self.assertRaises(ProviderAPIError):
                await provider.analyze(b"img", mime_type="image/jpeg")
        finally:
            await client.aclose()


if __name__ == "__main__":
    unittest.main()
