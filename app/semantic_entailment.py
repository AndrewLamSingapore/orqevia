"""Optional, offline NLI observation. It grants no authority and is not formal proof."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time

MODEL = "cross-encoder/nli-deberta-v3-base"
REVISION = "6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
FILES = {
    "config.json": "897e756eb59d3183adb505952e7910e7cbc7750a43f3b3747a96b688d2b02a47",
    "tokenizer_config.json": "f3eecd07c370ef0bf7dd3780d3cd68cf9c8b00c267e21a208ddcd8f82bfec1a6",
    "tokenizer.json": "5124ef2ead1a10a717703bc436de7f353da76d6340e4587719b42b1693707964",
    "spm.model": "c679fbf93643d19aab7ee10c0b99e460bdbc02fedf34b92b05af343b4af586fd",
    "model.onnx": "369ebf04fce8206c83b8fd62e9dc860144f10351a7f885ed3076beb17b7c6dda",
}
LABELS = {0: "contradiction", 1: "entailment", 2: "neutral"}
QUALIFICATION = {
    "status": "BOUNDED_SYNTHETIC_PASS",
    "scope": "16 synthetic premise-relative English NLI pairs; not formal proof or broad model certification",
    "top_label_matches": 14,
    "cases": 16,
    "confident_false_entailments": 0,
    "known_failures": "Two neutral cases were classified as contradictions; inspect the complete receipt",
    "receipt_sha256": "7b6d952bf67c570438d02890d17cc0a683e8f44e32b3ed81d63d04be0d64aec8",
    "receipt": "docs/evidence/orqevia2-20261023/nli-standard-qualification.json",
}


def verdict(logits):
    import numpy as np

    values = np.asarray(logits, dtype="float64")
    if values.shape != (3,) or not np.isfinite(values).all():
        raise RuntimeError("Invalid entailment model output")
    weights = np.exp(values - values.max())
    scores = weights / weights.sum()
    order = np.argsort(scores)
    strongest = int(order[-1])
    return {
        "relation": LABELS[strongest],
        "assessment": LABELS[strongest].upper()
        if scores[strongest] >= 0.8 and scores[strongest] - scores[order[-2]] >= 0.15
        else "UNCERTAIN",
        "uncalibrated_model_scores": {LABELS[i]: round(float(scores[i]), 6) for i in LABELS},
    }


class EntailmentEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None
        self.tokenizer = None
        self.last_error = None

    def load(self):
        with self.lock:
            if self.session is not None:
                return
            root = os.getenv("ORQEVIA_NLI_MODEL_DIR", "").strip()
            if not root:
                raise RuntimeError("Local entailment artifacts are not configured")
            directory = Path(root).resolve()
            for name, expected in FILES.items():
                path = directory / name
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError("Entailment artifact integrity verification failed")
                with path.open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != expected:
                    raise RuntimeError("Entailment artifact integrity verification failed")
            config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
            if config.get("id2label") != {str(k): v for k, v in LABELS.items()}:
                raise RuntimeError("Entailment label binding failed")
            from transformers import AutoTokenizer
            import onnxruntime as ort

            ort.disable_telemetry_events()
            try:
                tokenizer = AutoTokenizer.from_pretrained(
                    str(directory), local_files_only=True, trust_remote_code=False
                )
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                session = ort.InferenceSession(
                    str(directory / "model.onnx"), options, providers=["CPUExecutionProvider"]
                )
                if set(i.name for i in session.get_inputs()) - {"input_ids", "attention_mask", "token_type_ids"}:
                    raise RuntimeError("Unsupported entailment model inputs")
            except Exception:
                self.last_error = "MODEL_INITIALIZATION_FAILED"
                raise RuntimeError("Local entailment runtime unavailable") from None
            self.tokenizer, self.session = tokenizer, session
            self.last_error = None

    def health(self):
        configured = bool(os.getenv("ORQEVIA_NLI_MODEL_DIR", "").strip())
        return {
            "protocol": "orqevia.semantic.v1",
            "status": "LOADED"
            if self.session is not None
            else "UNAVAILABLE"
            if self.last_error
            else "CONFIGURED_NOT_LOADED"
            if configured
            else "NOT_CONFIGURED",
            "model": MODEL,
            "revision": REVISION,
            "model_sha256": FILES["model.onnx"],
            "runtime": "ONNX_CPU",
            "scope": "Premise-relative natural-language entailment",
            "max_pair_tokens": 512,
            "input_persistence": False,
            "formal_proof": False,
            "truth_or_source_authenticity_verified": False,
            "grants_execution_authority": False,
            "qualification": dict(QUALIFICATION),
        }

    def assess(self, premise: str, claim: str):
        if (
            not isinstance(premise, str)
            or not 1 <= len(premise.strip()) <= 5000
            or not isinstance(claim, str)
            or not 1 <= len(claim.strip()) <= 2000
        ):
            raise ValueError("A premise of 1–5000 and claim of 1–2000 characters are required")
        started = time.monotonic()
        with self.lock:
            self.load()
            encoded = self.tokenizer(premise, claim, return_tensors="np", truncation=False, padding=False)
            if encoded["input_ids"].shape[1] > 512:
                raise ValueError("Premise and claim exceed the 512-token bound; no silent truncation is performed")
            feed = {entry.name: encoded[entry.name] for entry in self.session.get_inputs()}
            try:
                output = self.session.run(None, feed)[0]
            except Exception:
                self.last_error = "MODEL_INFERENCE_FAILED"
                raise RuntimeError("Local entailment inference unavailable") from None
            if output.shape != (1, 3):
                raise RuntimeError("Invalid entailment output shape")
            result = verdict(output[0])
        return {
            "protocol": "orqevia.semantic.v1",
            **result,
            "model": MODEL,
            "revision": REVISION,
            "model_sha256": FILES["model.onnx"],
            "elapsed_seconds": round(time.monotonic() - started, 4),
            "premise_sha256": hashlib.sha256(premise.encode()).hexdigest(),
            "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
            "formal_proof": False,
            "source_authenticity_verified": False,
            "may_persist_as_verified_fact": False,
            "grants_execution_authority": False,
            "disclosure": "Model interpretation relative to the supplied premise. Scores are uncalibrated, not probabilities of factual truth. This does not authenticate the premise or prove a real-world claim.",
        }


ENGINE = EntailmentEngine()
