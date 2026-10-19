"""Contract tests for the optional hash-pinned ONNX MiniLM encoder."""
import hashlib

import numpy as np
import pytest

from app.onnx_embedding import OnnxEncoderError, OnnxMiniLMEncoder
from app.local_knowledge import KnowledgeEngine


class Value:
    def __init__(self, name):
        self.name = name


class Tokenizer:
    def __init__(self):
        self.batch_sizes = []

    def __call__(self, texts, **kwargs):
        self.batch_sizes.append(len(texts))
        return {
            "input_ids": np.ones((len(texts), 3), dtype=np.int64),
            "attention_mask": np.ones((len(texts), 3), dtype=np.int64),
        }


class Session:
    def __init__(self, dimensions=384):
        self.dimensions = dimensions

    def get_inputs(self):
        return [Value("input_ids"), Value("attention_mask")]

    def get_outputs(self):
        return [Value("sentence_embedding")]

    def run(self, outputs, feeds):
        assert outputs == ["sentence_embedding"]
        count = len(feeds["input_ids"])
        return [np.ones((count, self.dimensions), dtype=np.float32)]


def encoder(tmp_path, session=None):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"bounded ONNX fixture")
    return OnnxMiniLMEncoder(
        tmp_path,
        hashlib.sha256(model.read_bytes()).hexdigest(),
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        tokenizer=Tokenizer(),
        session=session or Session(),
    )


def test_onnx_encoder_batches_and_returns_float32_embeddings(tmp_path):
    value = encoder(tmp_path)
    result = value.encode(["one", "two", "three"], batch_size=2)

    assert result.shape == (3, 384)
    assert result.dtype == np.float32
    assert value.tokenizer.batch_sizes == [2, 1]
    assert value.identity["backend"] == "onnx_cpu"
    assert value.identity["dimensions"] == 384


def test_onnx_encoder_fails_closed_on_digest_contract_and_dimensions(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"bounded ONNX fixture")
    with pytest.raises(OnnxEncoderError, match="digest mismatch"):
        OnnxMiniLMEncoder(
            tmp_path,
            "0" * 64,
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            tokenizer=Tokenizer(),
            session=Session(),
        )

    value = encoder(tmp_path)
    with pytest.raises(OnnxEncoderError, match="normalized"):
        value.encode(["one"], normalize_embeddings=False)
    with pytest.raises(OnnxEncoderError, match="Invalid ONNX embedding output"):
        encoder(tmp_path, Session(dimensions=7)).encode(["one"])


def test_onnx_selection_requires_explicit_directory_and_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_MINILM_BACKEND", "onnx-cpu")
    monkeypatch.setenv("ORQEVIA_MINILM_ONNX_DIR", str(tmp_path))
    monkeypatch.delenv("ORQEVIA_MINILM_ONNX_SHA256", raising=False)
    with pytest.raises(ValueError, match="directory and digest"):
        KnowledgeEngine(tmp_path)._encoder()

    monkeypatch.setenv("ORQEVIA_MINILM_BACKEND", "unsupported")
    with pytest.raises(ValueError, match="Unknown MiniLM embedding backend"):
        KnowledgeEngine(tmp_path)._encoder()
