"""Optional local-only ONNX encoder for the existing MiniLM/FAISS RAG path."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

import numpy as np


SHA256_PATTERN = re.compile(r"[a-f0-9]{64}\Z")


class OnnxEncoderError(RuntimeError):
    """Raised when the pinned ONNX encoder cannot be used safely."""


class OnnxMiniLMEncoder:
    """SentenceTransformer-compatible CPU encoder backed by one ONNX graph.

    The model graph includes MiniLM pooling and normalization. The caller must
    use normalized embeddings so the ONNX output matches the active FAISS
    index. No model or tokenizer download is permitted.
    """

    dimensions = 384
    provider = "CPUExecutionProvider"

    def __init__(
        self,
        model_dir: str | Path,
        expected_sha256: str,
        *,
        model_name: str,
        threads: int = 2,
        tokenizer=None,
        session=None,
    ):
        self.model_dir = Path(model_dir).resolve()
        self.model_path = self.model_dir / "model.onnx"
        self.model_sha256 = normalized_digest(expected_sha256)
        if type(threads) is not int or not 1 <= threads <= 8:
            raise OnnxEncoderError("ONNX thread count must be between 1 and 8")
        if not self.model_dir.is_dir() or not self.model_path.is_file():
            raise OnnxEncoderError("Pinned ONNX model file is unavailable")
        if file_sha256(self.model_path) != self.model_sha256:
            raise OnnxEncoderError("Pinned ONNX model digest mismatch")

        self.tokenizer = tokenizer or local_tokenizer(self.model_dir)
        self.session = session or local_session(self.model_path, threads)
        self.input_names = {value.name for value in self.session.get_inputs()}
        self.output_names = {value.name for value in self.session.get_outputs()}
        if not {"input_ids", "attention_mask"} <= self.input_names:
            raise OnnxEncoderError("ONNX model input contract is incomplete")
        if "sentence_embedding" not in self.output_names:
            raise OnnxEncoderError("ONNX model lacks sentence_embedding output")
        self.identity = {
            "backend": "onnx_cpu",
            "model": model_name,
            "model_sha256": self.model_sha256,
            "provider": self.provider,
            "dimensions": self.dimensions,
        }

    def encode(
        self,
        texts,
        *,
        normalize_embeddings: bool = True,
        batch_size: int = 16,
        show_progress_bar: bool = False,
        **_: object,
    ) -> np.ndarray:
        if normalize_embeddings is not True:
            raise OnnxEncoderError("The pinned MiniLM graph requires normalized embeddings")
        if type(batch_size) is not int or batch_size < 1:
            raise OnnxEncoderError("Embedding batch size must be a positive integer")
        if not isinstance(texts, (list, tuple)) or any(not isinstance(text, str) for text in texts):
            raise OnnxEncoderError("Embedding input must be a sequence of strings")
        batches = []
        for start in range(0, len(texts), batch_size):
            encoded = self.tokenizer(
                list(texts[start : start + batch_size]),
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="np",
            )
            output = self.session.run(
                ["sentence_embedding"],
                {
                    "input_ids": np.asarray(encoded["input_ids"], dtype=np.int64),
                    "attention_mask": np.asarray(encoded["attention_mask"], dtype=np.int64),
                },
            )[0]
            vector = np.asarray(output, dtype=np.float32)
            if (
                vector.ndim != 2
                or vector.shape[1] != self.dimensions
                or not np.isfinite(vector).all()
            ):
                raise OnnxEncoderError("Invalid ONNX embedding output")
            batches.append(vector)
        if not batches:
            return np.empty((0, self.dimensions), dtype=np.float32)
        return np.concatenate(batches, axis=0)


def normalized_digest(value: str) -> str:
    if not isinstance(value, str):
        raise OnnxEncoderError("A lowercase SHA-256 digest is required")
    digest = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(digest):
        raise OnnxEncoderError("A lowercase SHA-256 digest is required")
    return digest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_tokenizer(model_dir: Path):
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(
            str(model_dir),
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
    except Exception as error:
        raise OnnxEncoderError("Local ONNX tokenizer is unavailable") from error


def local_session(model_path: Path, threads: int):
    try:
        import onnxruntime as ort

        if "CPUExecutionProvider" not in ort.get_available_providers():
            raise OnnxEncoderError("ONNX CPU execution provider is unavailable")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
    except OnnxEncoderError:
        raise
    except Exception as error:
        raise OnnxEncoderError("ONNX runtime initialization failed") from error
