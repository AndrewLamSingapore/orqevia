from app.rag_grounding import DocumentStore


def _store():
    store = DocumentStore()
    store.ingest(
        doc_id="d1",
        text="The Straits of Malacca is one of the busiest shipping lanes. It connects the Indian Ocean and the South China Sea.",
        source="https://example.gov/malacca",
        authority_class="PUBLIC_REFERENCE",
        scope="APPLICATION",
        geometry={"type": "Point", "coordinates": [100.5, 2.5]},
        observed_at="2026-01-01T00:00:00+00:00",
    )
    return store


def test_retrieval_returns_cited_passage_without_authority():
    store = _store()
    result = store.retrieve("busiest shipping lanes", actor_scopes={"APPLICATION"})
    assert result["status"] == "GROUNDED"
    assert result["results"][0]["content_is_authority"] is False
    assert result["results"][0]["instructions_may_execute"] is False
    assert result["results"][0]["citation"].startswith("https://example.gov/malacca#d1")


def test_insufficient_evidence_when_no_match():
    result = _store().retrieve("quantum entanglement", actor_scopes={"APPLICATION"})
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["results"] == []


def test_access_control_blocks_private_documents():
    store = _store()
    store.ingest(doc_id="d2", text="Owner secret notes.", source="local", authority_class="OWNER", scope="OWNER_PRIVATE")
    result = store.retrieve("secret notes", actor_scopes={"APPLICATION"})
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_geographic_filter():
    result = _store().retrieve("shipping lanes", actor_scopes={"APPLICATION"}, near=(2.5, 100.5), radius_km=100)
    assert result["status"] == "GROUNDED"


def test_deleted_document_is_excluded():
    store = _store()
    store.delete("d1")
    assert store.retrieve("shipping lanes", actor_scopes={"APPLICATION"})["status"] == "INSUFFICIENT_EVIDENCE"
