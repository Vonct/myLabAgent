from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: str) -> str:
    return ' '.join(str(value or '').strip().lower().split())


def _cosine(first: list[float], second: list[float]) -> float:
    norm_first = math.sqrt(sum(value * value for value in first)) or 1.0
    norm_second = math.sqrt(sum(value * value for value in second)) or 1.0
    return sum(a * b for a, b in zip(first, second)) / (norm_first * norm_second)


class LongTermMemoryStore:
    def __init__(self, *, project_root: Path, embedding_function: Any):
        self.project_root = project_root.resolve()
        self.embedding_function = embedding_function
        self.root = self.project_root / 'app_data' / 'long_term_memory'
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_file = self.root / 'long_term_memories.json'
        self.chroma_path = str(self.root / 'chroma_db')
        self.collection_name = os.environ.get('LABAGENT_LONG_MEMORY_COLLECTION', 'long_term_memories')
        self.backend = 'memory'
        self.backend_error = ''
        self.records: list[dict[str, Any]] = []
        self.client = None
        self.collection = None

        preferred_backend = os.environ.get('LABAGENT_LONG_MEMORY_BACKEND', 'chroma').strip().lower()
        if preferred_backend not in {'auto', 'chroma', 'memory'}:
            preferred_backend = 'chroma'

        if preferred_backend != 'memory':
            try:
                import chromadb

                self.client = chromadb.PersistentClient(path=self.chroma_path)
                self.collection = self.client.get_or_create_collection(self.collection_name)
                self.backend = 'chroma'
            except Exception as exc:
                self.backend_error = repr(exc)
                self._load_records()
        else:
            self._load_records()

    def _load_records(self) -> None:
        if not self.records_file.exists():
            self.records = []
            return
        content = self.records_file.read_text(encoding='utf-8').strip()
        self.records = json.loads(content) if content else []

    def _write_records(self) -> None:
        self.records_file.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding='utf-8')

    def _embed(self, text: str) -> list[float]:
        if hasattr(self.embedding_function, 'embed_with_usage'):
            vectors, _ = self.embedding_function.embed_with_usage([text])
            return list(vectors[0])
        return list(self.embedding_function([text])[0])

    def _memory_id(self, memory: dict[str, Any]) -> str:
        parts = [
            str(memory.get('scope', 'project')),
            str(memory.get('project_id', str(self.project_root))),
            str(memory.get('kind', 'preference')),
            _normalize_text(str(memory.get('text', ''))),
        ]
        digest = hashlib.sha256('\n'.join(parts).encode('utf-8')).hexdigest()[:24]
        return f'ltm_{digest}'

    def _sanitize_candidate(
        self,
        candidate: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
    ) -> dict[str, Any] | None:
        text = str(candidate.get('text', '') or '').strip()
        if len(text) < 8:
            return None

        kind = str(candidate.get('kind', 'preference') or '').strip().lower()
        if kind not in {'preference', 'workflow', 'project_fact', 'constraint'}:
            kind = 'preference'

        scope = str(candidate.get('scope', 'project') or '').strip().lower()
        if scope not in {'global', 'project'}:
            scope = 'project'

        try:
            confidence = float(candidate.get('confidence', 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        now = _utc_now()
        memory = {
            'kind': kind,
            'scope': scope,
            'project_id': str(self.project_root) if scope == 'project' else '',
            'text': text[:320],
            'confidence': max(0.0, min(1.0, confidence)),
            'evidence': str(candidate.get('evidence', '') or '').strip()[:240],
            'source_session_id': session_id,
            'source_task_id': task_id,
            'created_at': now,
            'updated_at': now,
            'last_used_at': '',
            'use_count': 0,
        }
        memory['id'] = self._memory_id(memory)
        return memory

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
        min_score: float = 0.0,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        project_id = project_id or str(self.project_root)
        try:
            query_vector = self._embed(query)
        except Exception:
            return []

        if self.backend == 'chroma' and self.collection is not None:
            try:
                results = self.collection.query(
                    query_embeddings=[query_vector],
                    n_results=max(limit * 4, limit),
                    include=['documents', 'metadatas', 'distances'],
                )
            except Exception as exc:
                self.backend_error = repr(exc)
                return []

            memories: list[dict[str, Any]] = []
            documents = results.get('documents') or [[]]
            metadatas = results.get('metadatas') or [[]]
            distances = results.get('distances') or [[]]
            for index, document in enumerate(documents[0]):
                metadata = dict(metadatas[0][index] or {})
                scope = str(metadata.get('scope', 'project'))
                if scope == 'project' and str(metadata.get('project_id', '')) != project_id:
                    continue
                distance = float(distances[0][index]) if distances and distances[0] else 0.0
                score = 1.0 / (1.0 + max(distance, 0.0))
                if score < min_score:
                    continue
                memory = {
                    **metadata,
                    'text': str(document or metadata.get('text', '')),
                    'score': score,
                }
                memories.append(memory)
                if len(memories) >= limit:
                    break
            return memories

        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self.records:
            scope = str(item.get('scope', 'project'))
            if scope == 'project' and str(item.get('project_id', '')) != project_id:
                continue
            embedding = item.get('embedding')
            if not isinstance(embedding, list):
                continue
            score = _cosine(query_vector, embedding)
            if score >= min_score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{k: v for k, v in item.items() if k != 'embedding'} | {'score': score} for score, item in scored[:limit]]

    def upsert_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        session_id: str,
        task_id: str,
        min_confidence: float = 0.72,
    ) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            memory = self._sanitize_candidate(candidate, session_id=session_id, task_id=task_id)
            if not memory or memory['confidence'] < min_confidence:
                continue
            try:
                embedding = self._embed(memory['text'])
            except Exception:
                continue

            if self.backend == 'chroma' and self.collection is not None:
                metadata = {k: v for k, v in memory.items() if k not in {'text'}}
                self.collection.upsert(
                    ids=[memory['id']],
                    documents=[memory['text']],
                    embeddings=[embedding],
                    metadatas=[metadata],
                )
            else:
                stored = {**memory, 'embedding': embedding}
                self.records = [item for item in self.records if item.get('id') != memory['id']]
                self.records.append(stored)
                self._write_records()
            saved.append(memory)
        return saved
