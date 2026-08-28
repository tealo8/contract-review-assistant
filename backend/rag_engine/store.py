from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any

from backend.database import Database


class KnowledgeStore:
    """Small deterministic retrieval layer; can be replaced with ChromaDB without changing callers."""

    def __init__(self, database: Database):
        self.database = database
        self._client: Any | None = None
        self._collection: Any | None = None
        self._connection_key = ""
        self.last_sync_error = ""

    @staticmethod
    def _embedding(text: str, dimensions: int = 256) -> list[float]:
        vector = [0.0] * dimensions
        tokens = re.findall(r"[\u4e00-\u9fff]{1,4}|[A-Za-z0-9]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            vector[index] += -1.0 if digest[4] & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _chroma(self):
        if os.getenv("CHROMA_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
            return None
        config = self.database.system_config()
        values = {key: item["value"] for key, item in config.items()}
        connection_key = "|".join((values.get("chroma_host", "localhost"), values.get("chroma_port", "8001"), values.get("chroma_collection", "contract_knowledge")))
        if self._collection is not None and self._connection_key == connection_key:
            return self._collection
        try:
            import chromadb

            self._client = chromadb.HttpClient(host=values.get("chroma_host", "localhost"), port=int(values.get("chroma_port", "8001")))
            self._collection = self._client.get_or_create_collection(values.get("chroma_collection", "contract_knowledge"))
            self._connection_key = connection_key
            self.last_sync_error = ""
            return self._collection
        except Exception as exc:
            self._client = None
            self._collection = None
            self.last_sync_error = str(exc)
            return None

    def reset_chroma_connection(self) -> None:
        self._client = None
        self._collection = None
        self._connection_key = ""

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        items = self.database.list_knowledge(include_disabled=False)
        collection = self._chroma()
        if collection is not None and items:
            try:
                result = collection.query(query_embeddings=[self._embedding(query)], n_results=min(limit, len(items)))
                hit_ids = [int(value) for value in (result.get("ids") or [[]])[0]]
                by_id = {int(item["id"]): item for item in items}
                hits = [by_id[item_id] for item_id in hit_ids if item_id in by_id]
                if hits:
                    return hits
            except Exception as exc:
                self.last_sync_error = str(exc)
        terms = [t for t in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query.lower()) if len(t) > 1]
        scored = []
        for item in items:
            haystack = f"{item['title']} {item['content']} {item['reference_no']}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def sync_item(self, item: dict[str, Any]) -> bool:
        collection = self._chroma()
        if collection is None:
            return False
        item_id = str(item["id"])
        try:
            if not item.get("enable", 1):
                collection.delete(ids=[item_id])
                return True
            document = f"{item['title']}\n{item['content']}\n{item['reference_no']}"
            collection.upsert(
                ids=[item_id],
                embeddings=[self._embedding(document)],
                documents=[document],
                metadatas=[{"category": item["category"], "reference_no": item["reference_no"]}],
            )
            self.last_sync_error = ""
            return True
        except Exception as exc:
            self.last_sync_error = str(exc)
            return False

    def delete_item(self, knowledge_id: int) -> bool:
        collection = self._chroma()
        if collection is None:
            return False
        try:
            collection.delete(ids=[str(knowledge_id)])
            self.last_sync_error = ""
            return True
        except Exception as exc:
            self.last_sync_error = str(exc)
            return False

    def sync_all(self) -> bool:
        collection = self._chroma()
        if collection is None:
            return False
        enabled = self.database.list_knowledge(include_disabled=False)
        try:
            existing = set((collection.get(include=[]).get("ids") or []))
            expected = {str(item["id"]) for item in enabled}
            stale = sorted(existing - expected)
            if stale:
                collection.delete(ids=stale)
            for item in enabled:
                self.sync_item(item)
            return not self.last_sync_error
        except Exception as exc:
            self.last_sync_error = str(exc)
            return False

    def ensure_seed(self, laws: list[dict[str, Any]], rules: list[dict[str, Any]]) -> None:
        if self.database.list_knowledge():
            return
        for item in laws:
            self.database.create_knowledge(("law", item["title"], item["content"], item["reference_no"], item.get("created_at", "")))
        for item in rules:
            self.database.create_knowledge(("enterprise_spec", item["title"], item["content"], item["reference_no"], item.get("created_at", "")))
