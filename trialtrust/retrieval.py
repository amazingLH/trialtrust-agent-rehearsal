"""Version-filtered BM25 + optional real dense vectors + RRF, with evidence IDs."""
from __future__ import annotations

import re
import hashlib
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np
from rank_bm25 import BM25Okapi


@dataclass(frozen=True)
class Source:
    id: str
    scope: str
    title: str
    text: str
    revision: int
    active: bool = True
    synthetic: bool = True


def tokenize(text: str) -> list[str]:
    # English words and overlapping Chinese bigrams; no character-hash embeddings.
    words = re.findall(r"[a-z0-9_]+", text.lower())
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
        if len(phrase) == 1:
            words.append(phrase)
    return words or ["<empty>"]


class EvidenceIndex:
    def __init__(self, sources: list[Source], embed: Callable | None = None):
        if len({s.id for s in sources}) != len(sources):
            raise ValueError("Duplicate evidence IDs")
        self.sources, self.embed = sources, embed
        self.vector_cache: dict[str, list[float]] = {}

    @staticmethod
    def cache_key(source: Source) -> str:
        payload = repr((source.id, source.scope, source.revision, source.title, source.text))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def expanded_queries(query: str) -> list[str]:
        # Small, disclosed domain lexicon, not an LLM query generator.
        queries = [query]
        if any(word in query for word in ("费用", "总价", "预算", "价目", "单价", "材料", "收费")):
            queries.append("价目 单价 每人 每台 材料费 邮寄 上门费")
        if any(word in query for word in ("退改", "取消", "退款", "改期")):
            queries.append("取消 改期 退款 退改")
        if any(word in query for word in ("授权", "权限", "越权", "个人资料")):
            queries.append("用户 授权 查询 起草 预约 付款 手机号")
        return queries

    def search(self, query: str, scope: str, k: int = 4, expand: bool = True,
               dense_only: bool = False) -> dict:
        if dense_only and self.embed is None:
            raise ValueError("Dense-only evaluation requires real vectors")
        # Filter before any recall or embedding. Never rank other tenants' documents.
        docs = [s for s in self.sources if s.scope == scope and s.active]
        if not docs:
            return {"mode": "no_evidence", "hits": []}
        lexical_queries = self.expanded_queries(query) if expand else [query]
        bm25 = BM25Okapi([tokenize(s.title + " " + s.text) for s in docs])
        lexical_fused = {}
        for lexical_query in lexical_queries:
            scores = bm25.get_scores(tokenize(lexical_query))
            ranked = [i for i in sorted(range(len(docs)), key=lambda i: (-scores[i], docs[i].id)) if scores[i] > 0]
            for rank, i in enumerate(ranked):
                lexical_fused[i] = lexical_fused.get(i, 0) + 1 / (60 + rank + 1)
        ranking = sorted(lexical_fused, key=lambda i: (-lexical_fused[i], docs[i].id))
        rankings, mode = ([] if dense_only else [ranking]), "bm25_only"
        if self.embed:
            pending = [d for d in docs if self.cache_key(d) not in self.vector_cache]
            if pending:
                vectors = self.embed([d.title + "\n" + d.text for d in pending])
                if len(vectors) != len(pending):
                    raise ValueError("Embedding count mismatch")
                self.vector_cache.update({self.cache_key(d): v for d, v in zip(pending, vectors)})
            q = np.asarray(self.embed([query])[0], dtype=float)
            matrix = np.asarray([self.vector_cache[self.cache_key(d)] for d in docs], dtype=float)
            if matrix.ndim != 2 or matrix.shape[1] != len(q) or not np.isfinite(matrix).all() or not np.isfinite(q).all():
                raise ValueError("Embedding dimensions/values invalid")
            similarities = matrix @ q / np.maximum(np.linalg.norm(matrix, axis=1) * np.linalg.norm(q), 1e-12)
            rankings.append(sorted(range(len(docs)), key=lambda i: (-similarities[i], docs[i].id)))
            mode = "dense_only" if dense_only else "bm25_dense_rrf"
        fused = {}
        for ranked in rankings:
            for rank, i in enumerate(ranked):
                fused[i] = fused.get(i, 0) + 1 / (60 + rank + 1)
        selected = sorted(fused, key=lambda i: (-fused[i], docs[i].id))[:k]
        return {"mode": mode, "query_strategy": "domain_facets_v1" if expand else "raw_query",
                "lexical_queries": lexical_queries,
                "hits": [dict(asdict(docs[i]), rrf_score=fused[i]) for i in selected]}
