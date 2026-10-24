"""CPU inference, multi-output heads, immutable artifact loading and extension.

Only numpy is imported eagerly. ONNX/tokenizers and torch/transformers backends
are optional and load locally, without network access or remote Python code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import threading
from typing import Callable

import numpy as np

from .taxonomy import Taxonomy
from .text import NORMALIZER_VERSION, Operation, encoder_text
from .novelty import ranks, validate_reference

ARTIFACT_VERSION = 2


def unit(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -80, 80)))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Prediction:
    embedding: np.ndarray
    category: str
    category_probs: dict[str, float]
    channel: str
    channel_probs: dict[str, float]
    tags: list[str]
    tag_probs: dict[str, float]
    attributes: dict
    novelty: float
    is_novel: bool
    taxonomy_version: str
    model_version: str

    def as_dict(self) -> dict:
        d = asdict(self)
        d["embedding"] = self.embedding.tolist()
        return d


class OnnxEncoder:
    def __init__(self, directory: Path, config: dict):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.max_length = config["max_length"]
        self.tokenizer.enable_truncation(max_length=self.max_length)
        self.tokenizer.enable_padding(pad_id=config["pad_token_id"], pad_token=config["pad_token"], direction="right")
        options = ort.SessionOptions()
        options.intra_op_num_threads = config.get("cpu_threads", 4)
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(directory / config["onnx_file"]), options,
                                            providers=["CPUExecutionProvider"])
        self.names = {x.name for x in self.session.get_inputs()}
        self.batch_size = config.get("inference_batch_size", 64)
        self.dim = config["embedding_dim"]
        # The tokenizer's dynamic padding setting is shared; serialize encode
        # calls. ONNX sessions themselves support concurrent calls.
        self.lock = threading.Lock()

    def __call__(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        # Length bucketing avoids paying the longest sequence for every row.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        for start in range(0, len(order), self.batch_size):
            ids = order[start:start + self.batch_size]
            with self.lock:
                tokens = self.tokenizer.encode_batch([texts[i] for i in ids])
            feed = {"input_ids": np.array([t.ids for t in tokens], dtype=np.int64),
                    "attention_mask": np.array([t.attention_mask for t in tokens], dtype=np.int64),
                    "token_type_ids": np.array([t.type_ids for t in tokens], dtype=np.int64)}
            embedding = self.session.run(None, {k: v for k, v in feed.items() if k in self.names})[0]
            out[ids] = embedding
        return unit(out)


class TorchEncoder:
    def __init__(self, directory: Path, config: dict):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.model = AutoModel.from_pretrained(directory / "encoder", local_files_only=True,
                                                trust_remote_code=False, attn_implementation="eager").eval().cpu()
        self.tokenizer = AutoTokenizer.from_pretrained(directory / "encoder", local_files_only=True,
                                                        trust_remote_code=False)
        torch.set_num_threads(config.get("cpu_threads", 4))
        self.config = config

    def __call__(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.config["embedding_dim"]), np.float32)
        result = []
        for start in range(0, len(texts), self.config.get("inference_batch_size", 64)):
            t = self.tokenizer(texts[start:start + self.config.get("inference_batch_size", 64)],
                               padding=True, truncation=True, max_length=self.config["max_length"], return_tensors="pt")
            with self.torch.inference_mode():
                x = self.model(**t).last_hidden_state
                if self.config.get("pooling", "cls") == "mean":
                    x = (x * t["attention_mask"].unsqueeze(-1)).sum(1) / t["attention_mask"].sum(1).clamp(min=1).unsqueeze(-1)
                else:
                    x = x[:, 0]
                result.append(x.cpu().numpy())
        return unit(np.concatenate(result))


class EncoderClassifier:
    def __init__(self, taxonomy: Taxonomy, config: dict, heads: dict[str, np.ndarray],
                 encode: Callable[[list[str]], np.ndarray]):
        self.taxonomy, self.config, self.encode = taxonomy, dict(config), encode
        self.heads = {k: np.asarray(v, np.float32).copy() for k, v in heads.items()}
        d = config["embedding_dim"]
        if not isinstance(d, int) or not 1 <= d <= 4096:
            raise ValueError("invalid embedding dimension")
        shapes = {"prototypes": (len(taxonomy.categories), d),
                  "channel_weight": (len(taxonomy.channels), d), "channel_bias": (len(taxonomy.channels),),
                  "tag_weight": (len(taxonomy.tags), d), "tag_bias": (len(taxonomy.tags),)}
        for k, shape in shapes.items():
            if k not in self.heads or self.heads[k].shape != shape or not np.isfinite(self.heads[k]).all():
                raise ValueError(f"invalid {k} shape or values")
        if (np.linalg.norm(self.heads["prototypes"], axis=1) < 1e-8).any():
            raise ValueError("category prototype must be nonzero")
        for k in ("category_scale", "category_temperature", "channel_temperature"):
            if not math.isfinite(config.get(k, float("nan"))) or config[k] <= 0:
                raise ValueError(f"invalid {k}")
        for k in ("novelty_threshold",):
            if not 0 <= config.get(k, -1) <= 1:
                raise ValueError(f"invalid {k}")
        thresholds = np.asarray(config.get("tag_thresholds"), float)
        if thresholds.shape != (len(taxonomy.tags),) or not np.isfinite(thresholds).all() or ((thresholds < 0) | (thresholds > 1)).any():
            raise ValueError("invalid tag thresholds")
        self.heads["prototypes"] = unit(self.heads["prototypes"])
        if config.get("novelty_reference") is not None:
            validate_reference(config["novelty_reference"])
        self.model_version = config.get("model_version", "encoder-v1-in-memory")

    def distributions(self, embedding: np.ndarray) -> dict[str, np.ndarray]:
        x = unit(embedding)
        if x.ndim != 2 or x.shape[1] != self.config["embedding_dim"] or not np.isfinite(x).all():
            raise ValueError("encoder produced invalid embeddings")
        similarity = x @ self.heads["prototypes"].T
        cat = similarity * self.config["category_scale"] / self.config["category_temperature"]
        ch = (x @ self.heads["channel_weight"].T + self.heads["channel_bias"]) / self.config["channel_temperature"]
        tg = x @ self.heads["tag_weight"].T + self.heads["tag_bias"]
        result = {"category": softmax(cat), "channel": softmax(ch), "tags": sigmoid(tg),
                  "novelty": np.clip(1 - similarity.max(axis=1), 0, 1)}
        if self.config.get("novelty_reference") is not None:
            result["novelty"] = ranks(result["novelty"], cat.argmax(1), self.taxonomy.categories,
                                      self.config["novelty_reference"])
        if any(not np.isfinite(value).all() for value in result.values()):
            raise ValueError("model produced nonfinite probabilities")
        return result

    def predict(self, operations: list[Operation]) -> list[Prediction]:
        if not operations:
            return []
        texts = [self.config.get("text_prefix", "") + encoder_text(op) for op in operations]
        # Deduplicate within this request only. No customer data is cached or
        # retained across requests, and benchmarking must use distinct rows.
        unique = list(dict.fromkeys(texts))
        indices = {s: i for i, s in enumerate(unique)}
        raw = self.encode(unique)
        x = unit(np.asarray(raw, np.float32))
        if x.shape != (len(unique), self.config["embedding_dim"]) or not np.isfinite(x).all():
            raise ValueError("encoder produced invalid embeddings")
        if (np.linalg.norm(x, axis=1) < .5).any():
            raise ValueError("encoder produced zero embeddings")
        x = x[[indices[s] for s in texts]]
        probs = self.distributions(x)
        categories, channels, tags = self.taxonomy.categories, self.taxonomy.channels, self.taxonomy.tags
        result = []
        for i in range(len(operations)):
            c = categories[int(probs["category"][i].argmax())]
            channel = channels[int(probs["channel"][i].argmax())]
            novelty = float(probs["novelty"][i])
            result.append(Prediction(
                x[i].copy(), c, dict(zip(categories, map(float, probs["category"][i]))),
                channel, dict(zip(channels, map(float, probs["channel"][i]))),
                [tag for j, tag in enumerate(tags) if probs["tags"][i, j] >= self.config["tag_thresholds"][j]],
                dict(zip(tags, map(float, probs["tags"][i]))), self.taxonomy.category(c)["attributes"],
                novelty, novelty > self.config["novelty_threshold"], self.taxonomy.version, self.model_version,
            ))
        return result

    @classmethod
    def load(cls, directory: Path, backend: str | None = None, verify: bool = True,
             encoder_factory: Callable | None = None) -> "EncoderClassifier":
        directory = Path(directory)
        config = json.loads((directory / "config.json").read_text())
        if config.get("artifact_version") != ARTIFACT_VERSION or config.get("normalizer_version") != NORMALIZER_VERSION:
            raise ValueError("incompatible v2 artifact")
        taxonomy = Taxonomy.load(directory / "taxonomy.json")
        if taxonomy.sha256 != config.get("taxonomy_sha256"):
            raise ValueError("taxonomy digest mismatch")
        if verify:
            manifest = json.loads((directory / "manifest.json").read_text())
            required = {"config.json", "heads.npz", "taxonomy.json", "tokenizer.json"}
            if not required <= set(manifest.get("files_sha256", {})) or manifest.get("model_version") != config.get("model_version"):
                raise ValueError("incomplete or inconsistent artifact manifest")
            for name, expected in manifest["files_sha256"].items():
                p = directory / name
                if Path(name).is_absolute() or ".." in Path(name).parts or not p.is_file() or sha256_file(p) != expected:
                    raise ValueError(f"artifact digest mismatch: {name}")
        selected_backend = config.get("runtime", "onnx")
        backend = backend or selected_backend
        if backend not in ("onnx", "torch"):
            raise ValueError("backend must be onnx or torch")
        if backend != selected_backend:
            variant = "torch-fp32" if backend == "torch" else "onnx-fp32"
            filename = None if backend == "torch" else "encoder-fp32.onnx"
            comparison = json.loads((directory / "runtime_comparison.json").read_text())
            calibration = comparison["variants"][variant]["calibration"]
            for key in ("category_temperature", "channel_temperature", "tag_thresholds", "novelty_threshold"):
                config[key] = calibration[key]
            config["novelty_reference"] = calibration.get("novelty_reference")
            config.update(runtime=backend, onnx_file=filename,
                          model_version=config["model_version"] + "+runtime-" + variant)
        if verify:
            # A manifest with a missing entry must not silently load an
            # unverified neural graph or Torch weight/config/tokenizer file.
            if backend == "onnx":
                runtime_files = {config.get("onnx_file")}
            else:
                runtime_files = {str(p.relative_to(directory)) for p in (directory / "encoder").rglob("*") if p.is_file()}
                runtime_files |= {"encoder/config.json", "encoder/model.safetensors", "encoder/tokenizer.json"}
            if not runtime_files <= set(manifest["files_sha256"]):
                raise ValueError("runtime payload missing from artifact manifest")
            if backend != selected_backend and "runtime_comparison.json" not in manifest["files_sha256"]:
                raise ValueError("runtime calibration missing from artifact manifest")
        with np.load(directory / "heads.npz", allow_pickle=False) as data:
            heads = dict(data)
        if encoder_factory is not None:
            encoder = encoder_factory(directory, config)
        elif backend == "onnx":
            encoder = OnnxEncoder(directory, config)
        else:
            encoder = TorchEncoder(directory, config)
        return cls(taxonomy, config, heads, encoder)

    def add_category(self, category: dict, center: np.ndarray, taxonomy_version: str) -> "EncoderClassifier":
        """In-memory extension after human approval; encoder object is reused.

        Persisting a new release is explicit in discovery.approve_candidate;
        the source artifact is never changed and production never self-adds.
        """
        center = np.asarray(center, np.float32)
        if center.shape != (self.config["embedding_dim"],) or not np.isfinite(center).all() or np.linalg.norm(center) < 1e-8:
            raise ValueError("new category center must be finite and nonzero")
        taxonomy = self.taxonomy.adding(category, taxonomy_version)
        heads = dict(self.heads)
        heads["prototypes"] = np.vstack([heads["prototypes"], unit(center)])
        config = dict(self.config, taxonomy_sha256=taxonomy.sha256,
                      model_version=self.model_version + "+taxonomy-" + taxonomy.sha256[:12])
        return EncoderClassifier(taxonomy, config, heads, self.encode)
