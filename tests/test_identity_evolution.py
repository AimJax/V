import json
import unittest
from pathlib import Path

from support import temporary_directory
from v.conversations.store import ConversationStore
from v.identity import IdentityStore
from v.identity_evolution import IdentityEvolution
from v.providers.base import ChatResult


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.last_kwargs = None

    async def chat(self, messages, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return ChatResult(content=self.response, model="local-test-model")


class IdentityEvolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = temporary_directory()
        root = Path(self.temp_dir.name)
        self.conversations = ConversationStore(root / "conversations.sqlite3")
        self.identity = IdentityStore(root / "identity.sqlite3")
        self.conversation = self.conversations.create_conversation("Identity review")

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_turn(self, user_text, assistant_text):
        self.conversations.add_message(self.conversation.id, "user", user_text)
        return self.conversations.add_message(self.conversation.id, "assistant", assistant_text)

    def make_provider(self):
        records = self.conversations.list_recent_message_records(limit=10)
        assistant = [item for item in records if item.role == "assistant"][-2:]
        payload = {
            "candidates": [{
                "category": "communication",
                "description": "Explains technical trade-offs before recommending an implementation.",
                "rationale": "This pattern appears in separate assistant responses.",
                "confidence": 0.86,
                "evidence": [
                    {"message_id": item.id, "quote": item.content[:30]}
                    for item in assistant
                ],
            }]
        }
        class Provider:
            def __init__(self, response):
                self.response = response
                self.calls = 0
                self.kwargs = None
            async def chat(inner, messages, **kwargs):
                inner.calls += 1
                inner.kwargs = kwargs
                return ChatResult(content=json.dumps(inner.response), model="local")
        return Provider(payload)

    def evaluator(self, provider, **kwargs):
        return IdentityEvolution(provider, self.conversations, self.identity, **kwargs)

    async def test_proposes_only_after_two_assistant_evidence_messages(self):
        self.add_turn("Which architecture?", "I will compare the trade-offs first.")
        self.add_turn("What about storage?", "I will explain the operational trade-offs.")
        provider = self.make_provider()
        proposals = await self.evaluator(provider).evaluate_recent_behavior()
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].status, "pending")
        self.assertEqual(len(proposals[0].evidence_refs), 2)
        self.assertEqual(len(self.identity.get_snapshot().traits), 8)
        self.assertEqual(provider.kwargs["response_format"], {"type": "json_object"})

    async def test_rejects_evidence_that_does_not_match_assistant_text(self):
        self.add_turn("Question one", "First assistant response.")
        self.add_turn("Question two", "Second assistant response.")
        provider = self.make_provider()
        payload = json.loads(json.dumps(provider.response))
        payload["candidates"][0]["evidence"][0]["quote"] = "invented text"
        provider.response = payload
        proposals = await self.evaluator(provider).evaluate_recent_behavior()
        self.assertEqual(proposals, [])

    async def test_requires_two_distinct_assistant_message_ids(self):
        first = self.add_turn("Question one", "First assistant response.")
        self.add_turn("Question two", "Second assistant response.")
        provider = self.make_provider()
        payload = json.loads(provider.response)
        payload["candidates"][0]["evidence"][0]["message_id"] = first
        payload["candidates"][0]["evidence"][1]["message_id"] = first
        provider.response = payload
        proposals = await self.evaluator(provider).evaluate_recent_behavior()
        self.assertEqual(proposals, [])

    async def test_evaluation_interval_and_duplicate_suppression(self):
        self.add_turn("Question one", "First response with detail.")
        self.add_turn("Question two", "Second response with detail.")
        provider = self.make_provider()
        evaluator = self.evaluator(provider, evaluation_interval_turns=3)
        self.assertEqual(await evaluator.evaluate_if_due(), [])
        self.assertEqual(provider.calls, 0)
        self.assertEqual(len(await evaluator.evaluate_recent_behavior()), 1)
        self.assertEqual(await evaluator.evaluate_recent_behavior(), [])
