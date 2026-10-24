"""Optional real backend check using random tiny BERT, never network weights."""
import json
from pathlib import Path
import importlib.util
import os
import subprocess
import sys

import numpy as np
import pytest


def run_backend_checks(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("onnx")
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    from zavozik_ml.classify_v2.artifact import seal
    from zavozik_ml.classify_v2.export import export
    from zavozik_ml.classify_v2.model import EncoderClassifier, OnnxEncoder, TorchEncoder
    from zavozik_ml.classify_v2.taxonomy import Taxonomy
    from zavozik_ml.classify_v2.text import NORMALIZER_VERSION, Operation
    from zavozik_ml.classify_v2.data import write_rows
    torch.set_num_threads(2)
    torch.manual_seed(11)
    taxonomy = Taxonomy.load()
    selected = tmp_path / "selected"; selected.mkdir()
    config = transformers.BertConfig(vocab_size=32, hidden_size=24, num_hidden_layers=1,
                                     num_attention_heads=4, intermediate_size=32,
                                     max_position_embeddings=64, pad_token_id=0)
    encoder = transformers.BertModel(config).eval()
    # MPS fitting keeps one sequence shape to avoid graph/cache growth. Test
    # the batch policy without allocating another real MPS training process,
    # and verify masked padding leaves active-token representations unchanged.
    from types import SimpleNamespace
    from zavozik_ml.classify_v2 import train as training
    tokens = {"input_ids": np.array([[2, 4, 3] + [0] * 13]),
              "attention_mask": np.array([[1] * 3 + [0] * 13])}
    original_torch = training.torch
    try:
        training.torch = SimpleNamespace(from_numpy=lambda x: SimpleNamespace(to=lambda device: x))
        padded = training.batch_tokens(tokens, np.array([0]), SimpleNamespace(type="mps"))
        trimmed = training.batch_tokens(tokens, np.array([0]), SimpleNamespace(type="cpu"))
    finally:
        training.torch = original_torch
    assert padded["input_ids"].shape == (1, 16)
    assert trimmed["input_ids"].shape == (1, 3)
    with torch.inference_mode():
        short = encoder(**{k: torch.tensor(v) for k, v in trimmed.items()}).last_hidden_state
        long = encoder(**{k: torch.tensor(v) for k, v in padded.items()}).last_hidden_state[:, :3]
    torch.testing.assert_close(short, long, atol=1e-5, rtol=1e-5)
    encoder.save_pretrained(selected / "encoder", safe_serialization=True)
    raw_tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3, "оплата": 4, "тест": 5}, unk_token="[UNK]"))
    raw_tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    raw_tokenizer.post_processor = tokenizers.processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)])
    tokenizer = transformers.PreTrainedTokenizerFast(tokenizer_object=raw_tokenizer,
                unk_token="[UNK]", pad_token="[PAD]", cls_token="[CLS]", sep_token="[SEP]")
    tokenizer.save_pretrained(selected / "encoder")
    raw_tokenizer.save(str(selected / "tokenizer.json"))
    rng = np.random.default_rng(11)
    heads = dict(prototypes=rng.normal(size=(len(taxonomy.categories), 24)).astype(np.float32),
                 channel_weight=rng.normal(size=(len(taxonomy.channels), 24)).astype(np.float32),
                 channel_bias=np.zeros(len(taxonomy.channels), np.float32),
                 tag_weight=rng.normal(size=(len(taxonomy.tags), 24)).astype(np.float32),
                 tag_bias=np.zeros(len(taxonomy.tags), np.float32))
    np.savez_compressed(selected / "heads.npz", **heads)
    cfg = dict(artifact_version=2, normalizer_version=NORMALIZER_VERSION, embedding_dim=24,
               category_scale=25., category_temperature=1., channel_temperature=1.,
               novelty_threshold=.2, tag_thresholds=[.5]*len(taxonomy.tags), max_length=32,
               pooling="cls", pad_token_id=0, pad_token="[PAD]", taxonomy_sha256=taxonomy.sha256,
               runtime="torch", cpu_threads=2, inference_batch_size=32,
               base_source=dict(model_id="test/tiny-bert-random", revision="0"*40))
    (selected / "config.json").write_text(json.dumps(cfg))
    (selected / "taxonomy.json").write_text(taxonomy.dumps())
    prepared = tmp_path / "prepared"; prepared.mkdir()
    rows = [dict(text=f"оплата тест пример{i}", label=taxonomy.categories[i % len(taxonomy.categories)],
                 channel="unknown", tags=[]) for i in range(300)]
    write_rows(prepared / "calibration.jsonl", rows)
    destination = tmp_path / "candidate"
    report = export(selected, destination, prepared)
    assert set(report["variants"]) == {"torch-fp32", "onnx-fp32", "onnx-int8"}
    classifier = EncoderClassifier.load(destination)
    for batch in [[Operation("in")], [Operation("out", "оплата")]*3,
                  [Operation("out", "тест " * 100)]*5]:
        predicted = classifier.predict(batch)
        assert len(predicted) == len(batch)
        assert all(np.isfinite(p.embedding).all() for p in predicted)
        assert all(len(p.embedding) == 24 for p in predicted)
    # Verify both optional runtime loaders independently of auto-selection.
    backend_values = {}
    for backend in ("torch", "onnx"):
        if backend == "onnx":
            c = json.loads((destination / "config.json").read_text())
            c["onnx_file"] = "encoder-fp32.onnx"
            encode = OnnxEncoder(destination, c)
        else:
            encode = TorchEncoder(destination, cfg)
        values = encode(["оплата", "оплата тест тест", "тест " * 60])
        backend_values[backend] = values
        assert values.shape == (3, 24)
        assert np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-5)
    np.testing.assert_allclose(backend_values["torch"], backend_values["onnx"], rtol=1e-4, atol=1e-5)
    p = classifier.predict([Operation("out", "оплата")])[0]
    extended = classifier.add_category(dict(key="experimental", title_ru="Эксперимент", description_ru="Новый вид.",
        attributes=dict(flow="business", direction="out", mandatory=False, regular_hint=False)),
        p.embedding, classifier.taxonomy.version + "+experimental")
    assert extended.encode is classifier.encode
    assert extended.predict([Operation("out", "оплата")])[0].category == "experimental"
    from zavozik_ml.serving.torch_process import TorchProcessEncoder
    process_encoder = TorchProcessEncoder(destination, cfg)
    try:
        sample_texts = ["оплата", "оплата тест тест", "тест " * 60]
        np.testing.assert_allclose(process_encoder(sample_texts), backend_values["torch"], rtol=1e-4, atol=1e-5)
        old = process_encoder.process
        old.kill(); old.wait(timeout=5)
        np.testing.assert_allclose(process_encoder(sample_texts), backend_values["torch"], rtol=1e-4, atol=1e-5)
        assert process_encoder.process.pid != old.pid
    finally:
        process_encoder.close()
    assert process_encoder.process is None
    with pytest.raises(RuntimeError, match="unavailable"):
        process_encoder(["оплата"])

    # A fresh main-server process imports LightGBM normally; Torch stays in its
    # own worker. This reproduces the environment of the native deadlock fix.
    import grpc
    import socket
    from categorize.v2 import categorizer_pb2 as p2, categorizer_pb2_grpc as g2
    from categorize.v1 import categorizer_pb2 as p1, categorizer_pb2_grpc as g1
    from forecast.v1 import forecaster_pb2 as pf, forecaster_pb2_grpc as gf
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    ml_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, ML_LISTEN=f"127.0.0.1:{port}", ML_CLASSIFIER_V2=str(destination),
               ML_CLASSIFIER_V2_BACKEND="torch", ML_ARTIFACTS=str(ml_root / "artifacts"),
               PYTHONPATH=os.pathsep.join([str(ml_root / "gen"), str(ml_root)]))
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-u", "-m", "zavozik_ml.serving.server"],
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
                ready = grpc.channel_ready_future(ch)
                try:
                    ready.result(timeout=45)
                    result = g2.CategorizerServiceStub(ch).Classify(p2.ClassifyRequest(operations=[
                        p2.Operation(direction="out", payment_purpose="оплата")]), timeout=10)
                    assert len(result.results[0].embedding) == 24
                    assert g1.CategorizerServiceStub(ch).Classify(p1.ClassifyRequest(operations=[
                        p1.Operation(direction="out", payment_purpose="Оплата поставщику за товар")]), timeout=10).results[0].category == "supplier"
                    assert gf.ForecasterServiceStub(ch).ListModels(pf.ListModelsRequest(), timeout=10).models
                finally:
                    ready.cancel()
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=5)
        assert server.returncode == 0, (tmp_path / "server.log").read_text()


def test_real_onnx_export_load_dynamic_shapes_and_new_prototype(tmp_path):
    # Optional native frameworks must not enter a pytest process that already
    # imported LightGBM during collection. Run this real-backend integration in
    # a fresh child with its own initialization order and bounded timeout.
    for module in ("torch", "transformers", "onnxruntime", "onnx", "tokenizers"):
        if importlib.util.find_spec(module) is None:
            pytest.skip(f"optional backend missing: {module}")
    code = "from pathlib import Path; from tests.test_classifier_v2_export import run_backend_checks; run_backend_checks(Path(__import__('sys').argv[1]))"
    result = subprocess.run([sys.executable, "-u", "-c", code, str(tmp_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    assert result.returncode == 0, result.stdout
