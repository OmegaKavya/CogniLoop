import pytest
from unittest.mock import patch, MagicMock
import backend.quiz.rag_retriever as rag_module
from backend.quiz.rag_retriever import RAGRetriever

def test_rag_chunk_text():
    retriever = RAGRetriever(db_path="data/test_chroma_db")
    text = "one two three four five six seven eight nine ten"
    
    # Chunk size = 4, overlap = 2
    # Step = chunk_size - overlap = 2
    # Chunks:
    # 0: words[0:4] -> one two three four
    # 1: words[2:6] -> three four five six
    # 2: words[4:8] -> five six seven eight
    # 3: words[6:10] -> seven eight nine ten
    # 4: words[8:12] -> nine ten
    chunks = retriever._chunk_text(text, chunk_size=4, overlap=2)
    assert len(chunks) == 5
    assert chunks[0] == "one two three four"
    assert chunks[1] == "three four five six"
    assert chunks[2] == "five six seven eight"
    assert chunks[3] == "seven eight nine ten"
    assert chunks[4] == "nine ten"

def test_rag_disabled_fallback():
    # Save original availability
    orig_avail = rag_module.CHROMA_AVAILABLE
    try:
        rag_module.CHROMA_AVAILABLE = False
        retriever = RAGRetriever(db_path="data/test_chroma_db")
        assert retriever.index_transcript("test_vid") is False
        ctx = retriever.get_context("test_vid")
        assert "context unavailable" in ctx.lower()
    finally:
        rag_module.CHROMA_AVAILABLE = orig_avail

def test_rag_indexing_and_retrieval():
    # Save original module state
    orig_avail = rag_module.CHROMA_AVAILABLE
    orig_api = getattr(rag_module, 'YouTubeTranscriptApi', None)
    orig_chroma = getattr(rag_module, 'chromadb', None)
    orig_transformer = getattr(rag_module, 'SentenceTransformer', None)
    
    try:
        rag_module.CHROMA_AVAILABLE = True
        
        # Mock class-level imports in module
        mock_api = MagicMock()
        mock_chroma = MagicMock()
        mock_transformer = MagicMock()
        
        rag_module.YouTubeTranscriptApi = mock_api
        rag_module.chromadb = mock_chroma
        rag_module.SentenceTransformer = mock_transformer
        
        mock_api.get_transcript.return_value = [
            {"text": "In this video we discuss learning operating systems."},
            {"text": "We will cover process scheduling and virtual memory algorithms."}
        ]
        
        mock_client = MagicMock()
        mock_chroma.PersistentClient.return_value = mock_client
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        
        mock_encoder = MagicMock()
        mock_transformer.return_value = mock_encoder
        mock_encoder.encode.return_value = MagicMock(tolist=lambda: [[0.1] * 384])
        
        retriever = RAGRetriever(db_path="data/test_chroma_db")
        
        # Test 1: Indexing when not already indexed
        mock_collection.get.return_value = {'ids': []}
        
        status = retriever.index_transcript("test_vid")
        
        assert status is True
        mock_api.get_transcript.assert_called_once_with("test_vid")
        mock_collection.add.assert_called_once()
        
        # Test 2: Indexing when already indexed
        mock_collection.get.return_value = {'ids': ['test_vid_chunk_0']}
        mock_api.get_transcript.reset_mock()
        mock_collection.add.reset_mock()
        
        status_already_indexed = retriever.index_transcript("test_vid")
        assert status_already_indexed is True
        mock_api.get_transcript.assert_not_called()
        mock_collection.add.assert_not_called()
        
        # Test 3: Get context retrieval
        mock_collection.query.return_value = {
            'documents': [['In this video we discuss learning operating systems.']]
        }
        
        mock_encoder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 384)
        
        ctx = retriever.get_context("test_vid", query="operating systems")
        assert "operating systems" in ctx
        mock_collection.query.assert_called_once()
        
    finally:
        # Restore module state
        rag_module.CHROMA_AVAILABLE = orig_avail
        
        if orig_api is not None:
            rag_module.YouTubeTranscriptApi = orig_api
        elif hasattr(rag_module, 'YouTubeTranscriptApi'):
            delattr(rag_module, 'YouTubeTranscriptApi')
            
        if orig_chroma is not None:
            rag_module.chromadb = orig_chroma
        elif hasattr(rag_module, 'chromadb'):
            delattr(rag_module, 'chromadb')
            
        if orig_transformer is not None:
            rag_module.SentenceTransformer = orig_transformer
        elif hasattr(rag_module, 'SentenceTransformer'):
            delattr(rag_module, 'SentenceTransformer')
