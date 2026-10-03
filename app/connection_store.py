"""Encrypted MongoDB persistence for a user's active Twynity project connection."""

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from cryptography.fernet import Fernet, InvalidToken
from pymongo import ASCENDING

_active_store: "ConnectionStore | None" = None


def set_active_store(store: "ConnectionStore | None") -> None:
    """Set the process-scoped store created/closed by the ASGI lifespan."""
    global _active_store
    _active_store = store


def get_active_store() -> "ConnectionStore | None":
    return _active_store


class ConnectionStore:
    """Store one upserted connection per exact ``(user_id, persona_id)`` pair."""

    def __init__(self, collection: Any, encryption_key: str):
        self.collection = collection
        self.cipher = Fernet(encryption_key.encode("ascii"))

    async def setup(self) -> None:
        """Create the compound uniqueness constraint at application startup."""
        await self.collection.create_index(
            [("user_id", ASCENDING), ("persona_id", ASCENDING)], unique=True
        )

    async def save(self, user_id: str, persona_id: str, values: dict[str, str]) -> str:
        """Encrypt credential values and upsert only this user/persona connection."""
        now = datetime.now(UTC)
        encrypted = {
            key: self.cipher.encrypt(value.encode("utf-8")).decode("ascii")
            for key, value in values.items()
        }
        result = await self.collection.update_one(
            {"user_id": user_id, "persona_id": persona_id},
            {
                "$set": {"values": encrypted, "modified": now},
                "$setOnInsert": {"created": now},
            },
            upsert=True,
        )
        return str(result.upserted_id) if result.upserted_id else "updated"

    async def get(self, user_id: str, persona_id: str) -> dict[str, Any] | None:
        """Read and decrypt only the exact identity pair; never search by user alone."""
        document = await self.collection.find_one(
            {"user_id": user_id, "persona_id": persona_id}
        )
        if not document:
            return None
        try:
            values = {
                key: self.cipher.decrypt(value.encode("ascii")).decode("utf-8")
                for key, value in document["values"].items()
            }
        except (InvalidToken, KeyError, TypeError) as exc:
            raise RuntimeError("Stored connection could not be decrypted; check ENCRYPTION_KEY") from exc
        return {"id": str(document.get("_id", ObjectId())), **values}

    async def public_metadata(self, user_id: str, persona_id: str) -> dict[str, Any] | None:
        """Return safe display fields only, excluding all credentials."""
        document = await self.collection.find_one(
            {"user_id": user_id, "persona_id": persona_id},
            {"values.name": 1, "values.base_url": 1, "created": 1, "modified": 1},
        )
        if not document:
            return None
        values = document.get("values", {})
        safe = {}
        for key in ("name", "base_url"):
            encrypted_value = values.get(key)
            if encrypted_value:
                safe[key] = self.cipher.decrypt(encrypted_value.encode("ascii")).decode("utf-8")
        return {"id": str(document["_id"]), **safe}
