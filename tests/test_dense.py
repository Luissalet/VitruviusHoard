"""Multilingual dense vectors fused with bm25 (fake embedder: tiny ES→EN glossary)."""
import numpy as np

from vitruvius_hoard.config import Config
from vitruvius_hoard.dense import DenseIndex, FakeEmbedder, NoneEmbedder, rrf, text_hash
from vitruvius_hoard.db import Database
from vitruvius_hoard import library


def seed(db: Database):
    db.execute("INSERT INTO sources(id, kind, url, license) VALUES ('s1','local','x','MIT')")
    db.execute("INSERT INTO documents(source_id, path, title, kind, lang, bytes, hash, updated_ts) VALUES ('s1','a.md','A','skill','',1,'h',0)")
    doc = db.one("SELECT id FROM documents")["id"]
    texts = [("Buttons", "Make every button look clickable with a clear pressed state."),
             ("Contrast", "Body text needs a contrast ratio of at least 4.5 to 1."),
             ("Motion", "Keep animation under 300 ms and respect reduced motion.")]
    for i, (h, t) in enumerate(texts):
        db.execute("INSERT INTO chunks(document_id, heading, ordinal, text, tokens) VALUES (?,?,?,?,?)", (doc, h, i, t, 10))


def test_rrf_rewards_agreement():
    fused = dict(rrf([[1, 2, 3], [3, 1]]))
    assert fused[1] > fused[2] and fused[3] > fused[2]


def test_build_embeds_each_distinct_text_once_and_is_incremental(tmp_path):
    db = Database(tmp_path / "v.db")
    seed(db)
    dense = DenseIndex(db, FakeEmbedder())
    assert not dense.usable()
    first = dense.build()
    assert first["state"] == "ready" and first["total"] == 3
    assert dense.counts() == {"chunks": 3, "vectors": 3}
    assert dense.build()["total"] == 0  # nothing new to embed
    assert dense.usable()


def test_spanish_question_finds_english_chunk_only_with_vectors(tmp_path):
    db = Database(tmp_path / "v.db")
    seed(db)
    dense = DenseIndex(db, FakeEmbedder())
    q = "¿cómo hago botones pulsables?"
    assert library.search(db, q, dense=dense) == []  # bm25 alone: no Spanish words in the corpus
    dense.build()
    hits = library.search(db, q, dense=dense, limit=3)
    assert hits and hits[0]["heading"] == "Buttons" and hits[0]["match"] == "dense"
    assert hits[0]["cite"].startswith("[vitruvius: s1/a.md")
    both = library.search(db, "contrast ratio", dense=dense, limit=3)
    assert both[0]["heading"] == "Contrast" and both[0]["match"] == "both"
    kw = library.search(db, "contrast ratio", dense=dense, mode="bm25", limit=3)
    assert kw[0]["match"] == "bm25"


def test_matrix_follows_new_chunks(tmp_path):
    db = Database(tmp_path / "v.db")
    seed(db)
    dense = DenseIndex(db, FakeEmbedder())
    dense.build()
    assert len(dense.query("animation", k=5)) == 3
    doc = db.one("SELECT id FROM documents")["id"]
    db.execute("INSERT INTO chunks(document_id, heading, ordinal, text, tokens) VALUES (?,?,?,?,?)", (doc, "New", 9, "animation easing", 3))
    dense.build()
    assert len(dense.query("animation", k=5)) == 4


def test_none_backend_keeps_keyword_search(tmp_path):
    db = Database(tmp_path / "v.db")
    seed(db)
    dense = DenseIndex(db, NoneEmbedder())
    assert not dense.usable()
    assert library.search(db, "contrast", dense=dense)[0]["match"] == "bm25"


def test_vectors_survive_reingest_by_text_hash(tmp_path):
    db = Database(tmp_path / "v.db")
    seed(db)
    dense = DenseIndex(db, FakeEmbedder())
    dense.build()
    db.execute("DELETE FROM chunks")
    seed_doc = db.one("SELECT id FROM documents")["id"]
    db.execute("INSERT INTO chunks(document_id, heading, ordinal, text, tokens) VALUES (?,?,?,?,?)",
               (seed_doc, "Buttons", 0, "Make every button look clickable with a clear pressed state.", 10))
    assert dense.build()["total"] == 0  # same text, same vector
    assert len(dense.query("button", k=5)) == 1


def test_tool_and_routes(client):
    client.svc.config.embed_backend = "fake"
    from vitruvius_hoard.dense import DenseIndex as DI
    client.svc.embedder = FakeEmbedder()
    client.svc.dense = DI(client.svc.db, client.svc.embedder)
    r = client.get("/api/library/embeddings")
    assert r.status_code == 200 and r.json()["active"] is False
    r = client.get("/api/library/search", params={"query": "x", "mode": "nope"})
    assert r.status_code == 400
    token = client.svc.token
    out = client.post("/api/agent/call", json={"name": "source_ingest", "arguments": {"embeddings": True}},
                      headers={"Authorization": f"Bearer {token}"})
    assert out.status_code == 200 and "embeddings" in out.json()
