import os
from src.config.settings import get_settings
from sentence_transformers import SentenceTransformer

class EmbeddingService:

    _instance = None  

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        settings = get_settings()
        if settings.HF_TOKEN:
            os.environ["HF_TOKEN"] = settings.HF_TOKEN
        self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self._initialized = True

    def embed(self, text: str):
        vector = self.model.encode(text)
        return vector.tolist()

embedding_service = EmbeddingService()