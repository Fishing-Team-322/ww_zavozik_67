"""Bounded, serialized stdio IPC to a separate optional Torch process."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import threading
import time

import numpy as np

from zavozik_ml.classify_v2.model import EncoderClassifier, sha256_file, ARTIFACT_VERSION
from zavozik_ml.classify_v2.taxonomy import Taxonomy
from zavozik_ml.classify_v2.text import NORMALIZER_VERSION


class TorchProcessEncoder:
    def __init__(self, directory: Path, config: dict, timeout: float = 30):
        self.directory, self.dim, self.timeout = Path(directory).resolve(), config["embedding_dim"], timeout
        self.lock = threading.Lock()
        self.process = None
        self.closed = False
        self._start()
        atexit.register(self.close)

    def _read_exact(self, size: int, deadline: float) -> bytes:
        result = bytearray()
        process = self.process
        if process is None:
            raise RuntimeError("neural worker unavailable")
        stream = process.stdout
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
                raise RuntimeError("neural worker response timed out")
            part = os.read(stream.fileno(), size - len(result))
            if not part:
                raise RuntimeError("neural worker exited")
            result.extend(part)
        return bytes(result)

    def _write_exact(self, value: bytes, deadline: float):
        stream = self.process.stdin
        offset = 0
        while offset < len(value):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [stream], [], remaining)[1]:
                raise RuntimeError("neural worker request timed out")
            written = os.write(stream.fileno(), value[offset:offset + 65536])
            if written <= 0:
                raise RuntimeError("neural worker pipe closed")
            offset += written

    def _frame(self, deadline):
        header = self._read_exact(5, deadline)
        size = struct.unpack("!I", header[1:])[0]
        if size > 32 << 20:
            raise RuntimeError("invalid neural worker response length")
        payload = self._read_exact(size, deadline)
        return header[:1], payload

    def _start(self):
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-m", "zavozik_ml.classify_v2.torch_worker", "--directory", str(self.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, bufsize=0,
            env=dict(os.environ, TOKENIZERS_PARALLELISM="false"),
        )
        try:
            status, payload = self._frame(time.monotonic() + self.timeout)
            if status != b"R" or len(payload) != 4 or struct.unpack("!I", payload)[0] != self.dim:
                raise RuntimeError("neural worker initialization failed")
        except Exception:
            self._stop()
            raise

    def __call__(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), np.float32)
        if not self.lock.acquire(timeout=self.timeout):
            raise RuntimeError("neural worker queue timed out")
        try:
            if self.closed:
                raise RuntimeError("neural worker is closed")
            if self.process is not None and self.process.poll() is not None:
                self._stop()
            if self.process is None:
                self._start()
            payload = json.dumps(texts, ensure_ascii=False).encode()
            self._write_exact(struct.pack("!I", len(payload)) + payload, time.monotonic() + self.timeout)
            status, data = self._frame(time.monotonic() + self.timeout)
            if status != b"O" or len(data) < 8:
                raise RuntimeError("neural worker inference failed")
            n, d = struct.unpack("!II", data[:8])
            if (n, d) != (len(texts), self.dim) or len(data) != 8 + n*d*4:
                raise RuntimeError("neural worker produced invalid shape")
            return np.frombuffer(data[8:], dtype="<f4").reshape(n, d).copy()
        except (OSError, RuntimeError, ValueError):
            self._stop()
            raise RuntimeError("neural worker unavailable") from None
        finally:
            self.lock.release()

    def close(self):
        self.closed = True
        self._stop()

    def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        for pipe in (process.stdin, process.stdout):
            if pipe:
                pipe.close()


def load_isolated_classifier(directory: Path) -> EncoderClassifier:
    """Verify locally before launching the worker. Consolidate with model.load
    after active training source snapshots have finished (see worklog).
    """
    directory = Path(directory)
    config = json.loads((directory / "config.json").read_text())
    if config.get("artifact_version") != ARTIFACT_VERSION or config.get("normalizer_version") != NORMALIZER_VERSION:
        raise ValueError("incompatible v2 artifact")
    taxonomy = Taxonomy.load(directory / "taxonomy.json")
    if taxonomy.sha256 != config.get("taxonomy_sha256"):
        raise ValueError("taxonomy digest mismatch")
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("model_version") != config.get("model_version"):
        raise ValueError("artifact manifest version mismatch")
    if not {"config.json", "heads.npz", "taxonomy.json", "tokenizer.json"} <= set(manifest.get("files_sha256", {})):
        raise ValueError("incomplete artifact manifest")
    for name, digest in manifest["files_sha256"].items():
        path = directory / name
        if Path(name).is_absolute() or ".." in Path(name).parts or not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"artifact digest mismatch: {name}")
    with np.load(directory / "heads.npz", allow_pickle=False) as values:
        heads = dict(values)
    if config.get("runtime") != "torch":
        comparison = json.loads((directory / "runtime_comparison.json").read_text())
        calibration = comparison["variants"]["torch-fp32"]["calibration"]
        for key in ("category_temperature", "channel_temperature", "tag_thresholds", "novelty_threshold"):
            config[key] = calibration[key]
        config["runtime"] = "torch"
        config["model_version"] += "+runtime-torch-fp32"
    return EncoderClassifier(taxonomy, config, heads, TorchProcessEncoder(directory, config))
