from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_docs (
  asset_id TEXT PRIMARY KEY,
  kind TEXT,
  transcript TEXT,
  metadata TEXT,
  embedding TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS index_fts USING fts5(asset_id, transcript);
"""
DIM = 32


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for token in text.lower().split():
        hashed = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        vec[hashed % DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class AssetIndex:
    """Local-first index: metadata + transcript FTS + hashed embedding rows.

    sqlite-vec is optional later; this stores embedding JSON so a vec adapter can swap in.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def upsert(
        self,
        asset_id: str,
        *,
        kind: str,
        transcript: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        vector = embed(transcript or asset_id)
        self._conn.execute(
            "INSERT OR REPLACE INTO index_docs(asset_id, kind, transcript, metadata, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            (asset_id, kind, transcript, json.dumps(metadata or {}), json.dumps(vector)),
        )
        self._conn.execute("DELETE FROM index_fts WHERE asset_id=?", (asset_id,))
        self._conn.execute(
            "INSERT INTO index_fts(asset_id, transcript) VALUES (?, ?)",
            (asset_id, transcript),
        )
        self._conn.commit()

    def find(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        qvec = embed(query)
        rows = self._conn.execute(
            "SELECT asset_id, kind, transcript, metadata, embedding FROM index_docs"
        ).fetchall()
        scored: list[dict[str, Any]] = []
        needle = query.lower()
        for row in rows:
            transcript = row["transcript"] or ""
            vector = json.loads(row["embedding"])
            score = _cosine(qvec, vector)
            if needle in transcript.lower():
                score += 0.5
            scored.append(
                {
                    "asset_id": row["asset_id"],
                    "kind": row["kind"],
                    "transcript": transcript,
                    "metadata": json.loads(row["metadata"] or "{}"),
                    "score": score,
                    "uri": f"vinci://assets/{row['asset_id']}",
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        fts_ids: set[str] = set()
        try:
            fts = self._conn.execute(
                "SELECT asset_id FROM index_fts WHERE transcript MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            fts_ids = {row["asset_id"] for row in fts}
        except sqlite3.OperationalError:
            fts_ids = set()
        if fts_ids:
            scored.sort(key=lambda item: (item["asset_id"] not in fts_ids, -item["score"]))
        return scored[:limit]
