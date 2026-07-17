import os
import json
import argparse
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from src.config.settings import settings
from src.config.database import SessionLocal
from src.models.job import Job

class EmbeddingPipeline:
    def __init__(self, index_dir="data/faiss_index"):
        self.model_name = settings.embedding_model
        # Use sentence-transformers
        self.model = SentenceTransformer(self.model_name)
        self.index_dir = index_dir
        self.index_path = os.path.join(self.index_dir, "index.faiss")
        self.metadata_path = os.path.join(self.index_dir, "metadata.json")
        
        os.makedirs(self.index_dir, exist_ok=True)
        
        self.index = None
        self.metadata = {}
        
        self._load_index()
        
    def _load_index(self):
        if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
            self.index = faiss.read_index(self.index_path)
            with open(self.metadata_path, "r") as f:
                self.metadata = {int(k): v for k, v in json.load(f).items()}
                
    def embed_text(self, text: str) -> np.ndarray:
        if not text or not text.strip():
            return np.zeros(self.model.get_sentence_embedding_dimension(), dtype=np.float32)
        
        # normalize_embeddings=True makes inner product equivalent to cosine similarity
        vector = self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vector
        
    def build_index(self):
        db = SessionLocal()
        try:
            jobs = db.query(Job).filter(Job.is_spam == False).all()
            
            if not jobs:
                print("No jobs found to index.")
                # We should still create an empty index just in case
                dimension = self.model.get_sentence_embedding_dimension()
                self.index = faiss.IndexFlatIP(dimension)
                faiss.write_index(self.index, self.index_path)
                with open(self.metadata_path, "w") as f:
                    json.dump({}, f)
                return
                
            texts = []
            self.metadata = {}
            for i, job in enumerate(jobs):
                # Combine relevant fields to embed
                skills = " ".join(job.skills_required) if job.skills_required else ""
                text_to_embed = f"{job.role_title} {job.company_name} {skills} {job.jd_text}"
                texts.append(text_to_embed)
                
                self.metadata[i] = {
                    "id": str(job.id),
                    "role_title": job.role_title,
                    "company_name": job.company_name
                }
                
            print(f"Generating embeddings for {len(texts)} jobs...")
            embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension) # Inner product = cosine similarity for normalized vectors
            self.index.add(embeddings)
            
            faiss.write_index(self.index, self.index_path)
            with open(self.metadata_path, "w") as f:
                json.dump(self.metadata, f)
                
            print(f"Successfully saved FAISS index to {self.index_dir}")
        finally:
            db.close()
            
    def search(self, query: str, top_k: int = 5):
        if not self.index or self.index.ntotal == 0:
            return []
            
        query_vector = self.embed_text(query)
        if np.all(query_vector == 0):
            return []
            
        query_vector = np.expand_dims(query_vector, axis=0).astype(np.float32)
        
        # Avoid asking for more neighbors than we have
        k = min(top_k, self.index.ntotal)
        if k == 0:
            return []
            
        scores, indices = self.index.search(query_vector, k)
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1 and idx in self.metadata:
                meta = self.metadata[idx]
                results.append({
                    "id": meta["id"],
                    "role_title": meta["role_title"],
                    "company_name": meta["company_name"],
                    "score": float(scores[0][i])
                })
        return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--embed-jobs", action="store_true", help="Embed all jobs and build FAISS index")
    args = parser.parse_args()
    
    if args.embed_jobs:
        ep = EmbeddingPipeline()
        ep.build_index()
