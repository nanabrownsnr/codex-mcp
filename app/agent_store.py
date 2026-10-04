"""Persist the Codex session and executor identity for each Twyn."""

from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo import ASCENDING, ReturnDocument


class AgentStore:
    """Store one long-lived Codex session per verified user/persona pair."""

    def __init__(self, collection: Any):
        self.collection = collection

    async def setup(self) -> None:
        await self.collection.create_index(
            [("user_id", ASCENDING), ("persona_id", ASCENDING)], unique=True
        )

    async def get(self, user_id: str, persona_id: str) -> dict[str, Any] | None:
        document = await self.collection.find_one(
            {"user_id": user_id, "persona_id": persona_id}
        )
        if not document:
            return None
        return {key: value for key, value in document.items() if key not in {"_id", "user_id", "persona_id"}}

    async def save(
        self, user_id: str, persona_id: str, values: dict[str, Any]
    ) -> None:
        now = datetime.now(UTC)
        await self.collection.update_one(
            {"user_id": user_id, "persona_id": persona_id},
            {
                "$set": {**values, "modified": now},
                "$setOnInsert": {"created": now},
            },
            upsert=True,
        )

    async def update_status(
        self, user_id: str, persona_id: str, *, status: str, last_error: str | None = None
    ) -> None:
        await self.collection.update_one(
            {"user_id": user_id, "persona_id": persona_id},
            {"$set": {"status": status, "last_error": last_error, "modified": datetime.now(UTC)}},
        )

    async def acquire_run(self, user_id: str, persona_id: str, seconds: int) -> bool:
        now = datetime.now(UTC)
        document = await self.collection.find_one_and_update(
            {
                "user_id": user_id,
                "persona_id": persona_id,
                "$or": [
                    {"run_lock_until": {"$exists": False}},
                    {"run_lock_until": {"$lt": now}},
                ],
            },
            {"$set": {"run_lock_until": now + timedelta(seconds=seconds)}},
            return_document=ReturnDocument.AFTER,
        )
        return document is not None

    async def release_run(self, user_id: str, persona_id: str) -> None:
        await self.collection.update_one(
            {"user_id": user_id, "persona_id": persona_id},
            {"$unset": {"run_lock_until": ""}},
        )
