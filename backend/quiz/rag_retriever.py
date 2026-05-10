import os
try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    from youtube_transcript_api import YouTubeTranscriptApi
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

class RAGRetriever:
    def __init__(self, db_path="data/chroma_db"):
        self.db_path = db_path
        if CHROMA_AVAILABLE:
            os.makedirs(db_path, exist_ok=True)
            self.client = chromadb.PersistentClient(path=db_path)
            self.collection = self.client.get_or_create_collection(name="transcripts")
            self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        
    def _chunk_text(self, text, chunk_size=300, overlap=50):
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i:i + chunk_size])
            chunks.append(chunk)
        return chunks
        
    def index_transcript(self, video_id):
        if not CHROMA_AVAILABLE: return False
        
        existing = self.collection.get(where={"video_id": video_id})
        if existing and len(existing['ids']) > 0:
            return True
            
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            full_text = " ".join([t['text'] for t in transcript_list])
            
            chunks = self._chunk_text(full_text)
            
            ids = [f"{video_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [{"video_id": video_id, "chunk_idx": i} for i in range(len(chunks))]
            embeddings = self.encoder.encode(chunks).tolist()
            
            self.collection.add(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=chunks
            )
            return True
        except Exception as e:
            print(f"Failed to index transcript for {video_id}: {e}")
            return False
            
    def get_context(self, video_id, query="Core concepts, key principles, definitions, examples, and critical comparisons", top_k=3):
        if not CHROMA_AVAILABLE:
            return "Transcript context unavailable. Use general domain knowledge."
            
        self.index_transcript(video_id)
        
        try:
            query_embedding = self.encoder.encode(query).tolist()
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"video_id": video_id}
            )
            if results and results['documents'] and len(results['documents'][0]) > 0:
                return "\n...\n".join(results['documents'][0])
            return "No relevant context found in transcript."
        except Exception as e:
            print(f"RAG Retrieval error: {e}")
            return "Error retrieving context."

rag_retriever = RAGRetriever()
