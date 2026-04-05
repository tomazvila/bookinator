"""Local ONNX-based embedding model (all-MiniLM-L6-v2).

Runs entirely locally — no API calls. Uses ONNX Runtime for inference
and HuggingFace tokenizers for text tokenization.
"""

import logging
import os
import struct
import threading

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

EMBEDDING_DIMS = 384
MODEL_NAME = "all-MiniLM-L6-v2"
MAX_SEQ_LENGTH = 256
EMBEDDING_BATCH_SIZE = 64

_lock = threading.Lock()
_embedder: "LocalEmbedder | None" = None


class LocalEmbedder:
    """Sentence embedding using a local ONNX model."""

    def __init__(self, model_dir: str):
        model_path = os.path.join(model_dir, "model.onnx")
        tokenizer_path = os.path.join(model_dir, "tokenizer.json")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"ONNX model not found: {model_path}")
        if not os.path.exists(tokenizer_path):
            raise FileNotFoundError(f"Tokenizer not found: {tokenizer_path}")

        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_padding(length=MAX_SEQ_LENGTH)
        self.tokenizer.enable_truncation(max_length=MAX_SEQ_LENGTH)

        sess_opts = ort.SessionOptions()
        sess_opts.inter_op_num_threads = 1
        sess_opts.intra_op_num_threads = 2
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            model_path, sess_options=sess_opts, providers=["CPUExecutionProvider"]
        )

        # Verify output dimensions
        output_shape = self.session.get_outputs()[0].shape
        if len(output_shape) >= 2 and output_shape[-1] is not None:
            actual_dims = output_shape[-1]
            if actual_dims != EMBEDDING_DIMS:
                raise ValueError(
                    f"Model output dim {actual_dims} != expected {EMBEDDING_DIMS}"
                )

        logger.info("Loaded embedding model from %s (%d dims)", model_dir, EMBEDDING_DIMS)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Returns list of float vectors."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i : i + EMBEDDING_BATCH_SIZE]
            all_embeddings.extend(self._embed_batch(batch))
        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        """Embed a single search query."""
        return self._embed_batch([query])[0]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        encodings = self.tokenizer.encode_batch(texts)

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

        outputs = self.session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )

        # Mean pooling over token embeddings, masked by attention
        token_embeddings = outputs[0]  # (batch, seq_len, hidden_dim)
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        summed = (token_embeddings * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        sentence_embeddings = summed / counts

        # L2 normalize
        norms = np.linalg.norm(sentence_embeddings, axis=1, keepdims=True).clip(min=1e-9)
        sentence_embeddings = sentence_embeddings / norms

        return sentence_embeddings.tolist()


def get_embedder(model_dir: str | None = None) -> LocalEmbedder | None:
    """Get or create the singleton embedder. Returns None if model not available."""
    global _embedder
    if _embedder is not None:
        return _embedder

    with _lock:
        if _embedder is not None:
            return _embedder

        if model_dir is None:
            model_dir = os.environ.get("EMBEDDING_MODEL_DIR", "/model")

        try:
            _embedder = LocalEmbedder(model_dir)
            return _embedder
        except Exception as e:
            logger.warning("Could not load embedding model from %s: %s", model_dir, e)
            return None


def serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize embedding to bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def deserialize_embedding(data: bytes) -> list[float]:
    """Deserialize embedding bytes from sqlite-vec."""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))
