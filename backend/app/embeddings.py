from __future__ import annotations

from typing import Iterable

from . import db

_model = None


def _get():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        # 첫 사용 시 HF 캐시로 지연 다운로드한다. 모델 교체는 재인덱싱이 필요하다.
        _model = TextEmbedding(model_name=db.EMBEDDING_MODEL)
    return _model


def embed_passages(texts: Iterable[str]) -> list[list[float]]:
    return [v.tolist() for v in _get().passage_embed(list(texts))]


def embed_query(text: str) -> list[float]:
    return list(_get().query_embed([text]))[0].tolist()
