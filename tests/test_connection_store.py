"""Credential encryption, upsert shape, and strict persona isolation tests."""

import pytest
from cryptography.fernet import Fernet

from app.connection_store import ConnectionStore


class FakeCollection:
    def __init__(self):
        self.documents = {}

    async def create_index(self, *_args, **_kwargs):
        return "user_persona_unique"

    async def update_one(self, query, update, upsert=False):
        key = (query["user_id"], query["persona_id"])
        document = self.documents.setdefault(key, {"_id": f"{key[0]}:{key[1]}"})
        document.update(update["$set"])
        return type("Result", (), {"upserted_id": None})()

    async def find_one(self, query, projection=None):
        document = self.documents.get((query["user_id"], query["persona_id"]))
        if not document:
            return None
        if projection:
            values = document.get("values", {})
            return {"_id": document["_id"], "values": {
                key: values[key] for key in ("name", "base_url") if key in values
            }}
        return document


@pytest.mark.asyncio
async def test_credentials_are_encrypted_and_only_retrieved_for_exact_pair():
    collection = FakeCollection()
    store = ConnectionStore(collection, Fernet.generate_key().decode())
    await store.setup()
    await store.save("user-1", "persona-a", {
        "name": "CRM", "base_url": "https://crm.example", "api_key": "secret-key",
        "api_secret": "secret-value",
    })

    stored = collection.documents[("user-1", "persona-a")]["values"]
    assert "secret-key" not in stored["api_key"]
    assert await store.get("user-1", "persona-b") is None
    assert (await store.get("user-1", "persona-a"))["api_secret"] == "secret-value"
    assert (await store.public_metadata("user-1", "persona-a")) == {
        "id": "user-1:persona-a", "name": "CRM", "base_url": "https://crm.example"
    }
