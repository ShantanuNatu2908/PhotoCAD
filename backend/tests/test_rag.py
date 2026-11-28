"""
Unit Tests for build123d RAG Retriever Service
Document ID: PCAD-LG-004
"""

from app.agents.rag import Build123dRAGService


def test_rag_retrieval_matching():
    # Query for fillet and hole operations
    docs = Build123dRAGService.retrieve_context_for_operations(["fillet", "hole"])
    symbols = [d["symbol"] for d in docs]
    
    assert "fillet" in symbols
    assert "hole" in symbols
    assert "BuildPart" in symbols  # Foundation inclusion

    # Verify each chunk has code example
    for doc in docs:
        assert len(doc["canonical_pattern"]) > 10
        assert "build123d" in doc["canonical_pattern"] or "part" in doc["canonical_pattern"]

def test_rag_fallback_empty_query():
    # Empty query should still return fundamental BuildPart context
    docs = Build123dRAGService.retrieve_context_for_operations([])
    assert len(docs) >= 1
    assert docs[0]["symbol"] == "BuildPart"
