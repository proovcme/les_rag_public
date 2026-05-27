import importlib
import sys
import time

import pytest


def test_unload_peer_for_val_unloads_main(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")

    class Engine:
        def __init__(self, loaded):
            self.model = object() if loaded else None
            self.unloaded = False

        def _unload_model(self):
            self.model = None
            self.unloaded = True

    main = Engine(loaded=True)
    val = Engine(loaded=False)
    monkeypatch.setattr(mlx_host, "main_engine", main)
    monkeypatch.setattr(mlx_host, "val_engine", val)
    monkeypatch.setattr(mlx_host, "KEEP_SINGLE_LLM_LOADED", True)

    assert mlx_host._unload_peer_for(val) == ["main"]
    assert main.unloaded is True


def test_unload_peer_for_main_unloads_val(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")

    class Engine:
        def __init__(self, loaded):
            self.model = object() if loaded else None
            self.unloaded = False

        def _unload_model(self):
            self.model = None
            self.unloaded = True

    main = Engine(loaded=False)
    val = Engine(loaded=True)
    monkeypatch.setattr(mlx_host, "main_engine", main)
    monkeypatch.setattr(mlx_host, "val_engine", val)
    monkeypatch.setattr(mlx_host, "KEEP_SINGLE_LLM_LOADED", True)

    assert mlx_host._unload_peer_for(main) == ["val"]
    assert val.unloaded is True


def test_unload_peer_for_respects_disabled_policy(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")

    class Engine:
        model = object()

        def _unload_model(self):
            raise AssertionError("should not unload")

    main = Engine()
    val = Engine()
    monkeypatch.setattr(mlx_host, "main_engine", main)
    monkeypatch.setattr(mlx_host, "val_engine", val)
    monkeypatch.setattr(mlx_host, "KEEP_SINGLE_LLM_LOADED", False)

    assert mlx_host._unload_peer_for(val) == []


def test_unload_peer_for_skips_busy_peer(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")

    class Engine:
        def __init__(self, loaded, busy=False):
            self.model = object() if loaded else None
            self.busy = busy
            self.unloaded = False

        def is_busy(self):
            return self.busy

        def _unload_model(self):
            self.model = None
            self.unloaded = True

    main = Engine(loaded=True, busy=True)
    val = Engine(loaded=False)
    monkeypatch.setattr(mlx_host, "main_engine", main)
    monkeypatch.setattr(mlx_host, "val_engine", val)
    monkeypatch.setattr(mlx_host, "KEEP_SINGLE_LLM_LOADED", True)

    assert mlx_host._unload_peer_for(val) == []
    assert main.unloaded is False


@pytest.mark.asyncio
async def test_validate_answer_uses_configured_context_limit(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")
    monkeypatch.setenv("VALIDATOR_BACKEND", "mlx")
    monkeypatch.setenv("MLX_VALIDATE_CONTEXT_CHARS", "4096")
    captured = {}

    class MainEngine:
        model = None

    class ValEngine:
        model = None
        model_path = "val"

        def apply_chat_template(self, messages, enable_thinking=False):
            captured["messages"] = messages
            captured["enable_thinking"] = enable_thinking
            return "prompt"

        async def generate_text(self, prompt, max_tokens):
            captured["prompt"] = prompt
            captured["max_tokens"] = max_tokens
            return "VERIFIED"

    monkeypatch.setattr(mlx_host, "main_engine", MainEngine())
    monkeypatch.setattr(mlx_host, "val_engine", ValEngine())

    result = await mlx_host.validate_answer(
        mlx_host.ValidateRequest(
            question="q",
            answer="a",
            context="x" * 5000,
        )
    )

    user_content = captured["messages"][1]["content"]
    context_block = user_content.split("Контекст: ", 1)[1].split("\nОтвет для проверки:", 1)[0]
    assert result["status"] == "VERIFIED"
    assert captured["enable_thinking"] is False
    assert captured["max_tokens"] == 64
    assert len(context_block) == 4096


@pytest.mark.asyncio
async def test_validate_answer_rules_backend_verified(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")
    monkeypatch.setenv("VALIDATOR_BACKEND", "rules")

    result = await mlx_host.validate_answer(
        mlx_host.ValidateRequest(
            question="Какая минимальная ширина прохода?",
            answer="Минимальная ширина прохода 0,8 м.",
            context="Минимальная ширина прохода 0,8 м.",
        )
    )

    assert result["status"] == "VERIFIED"
    assert result["backend"] == "rules"


@pytest.mark.asyncio
async def test_validate_answer_rules_backend_no_data(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")
    monkeypatch.setenv("VALIDATOR_BACKEND", "rules")

    result = await mlx_host.validate_answer(
        mlx_host.ValidateRequest(
            question="Какая минимальная ширина прохода?",
            answer="Минимальная ширина прохода 0,8 м.",
            context="",
        )
    )

    assert result["status"] == "NO_DATA"
    assert result["backend"] == "rules"


@pytest.mark.asyncio
async def test_coreml_validator_falls_back_to_mlx(monkeypatch):
    mlx_host = importlib.import_module("mlx_host")
    monkeypatch.setenv("VALIDATOR_BACKEND", "coreml")
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_ISOLATE_PROCESS", False)
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_FALLBACK", True)
    monkeypatch.setattr(mlx_host, "_coreml_validator_fallback_active", False)
    monkeypatch.setattr(mlx_host, "_coreml_validator_last_error", "")

    class BrokenCoreMLValidator:
        def validate(self, req):
            raise FileNotFoundError("missing validator package")

    class MainEngine:
        model = None

    class ValEngine:
        model = None
        model_path = "val"

        def apply_chat_template(self, messages, enable_thinking=False):
            return "prompt"

        async def generate_text(self, prompt, max_tokens):
            return "NO_DATA"

    monkeypatch.setattr(mlx_host, "_coreml_validator_instance", lambda: BrokenCoreMLValidator())
    monkeypatch.setattr(mlx_host, "main_engine", MainEngine())
    monkeypatch.setattr(mlx_host, "val_engine", ValEngine())

    result = await mlx_host.validate_answer(
        mlx_host.ValidateRequest(question="q", answer="a", context="c")
    )

    assert result["status"] == "NO_DATA"
    assert result["backend"] == "mlx"
    assert result["fallback_from"] == "coreml"
    assert "missing validator package" in result["fallback_error"]
    status = mlx_host._validator_status()
    assert status["fallback_active"] is True
    assert "missing validator package" in status["last_fallback_error"]


def test_validator_status_reports_guardrails(monkeypatch, tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    missing_model = tmp_path / "missing.mlpackage"

    class ValEngine:
        model = None
        model_path = "mlx-val-model"

    monkeypatch.setenv("VALIDATOR_BACKEND", "coreml")
    monkeypatch.setattr(mlx_host, "val_engine", ValEngine())
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_MODEL", str(missing_model))
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_TOKENIZER", "nli-model-id")
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_VERSION", "nli-model-id@test-package")
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_MIN_CONFIDENCE", 0.73)
    monkeypatch.setattr(mlx_host, "COREML_VALIDATOR_FALLBACK", True)
    monkeypatch.setattr(mlx_host, "_coreml_validator_fallback_active", True)
    monkeypatch.setattr(mlx_host, "_coreml_validator_last_error", "package missing")

    status = mlx_host._validator_status()

    assert status["backend"] == "coreml"
    assert status["validator_backend"] == "coreml"
    assert status["model_id"] == "mlx-val-model"
    assert status["model_version"] == "nli-model-id@test-package"
    assert status["active_model"] == str(missing_model)
    assert status["active_model_id"] == "nli-model-id"
    assert status["active_model_version"] == "nli-model-id@test-package"
    assert status["coreml_model_id"] == "nli-model-id"
    assert status["coreml_model_version"] == "nli-model-id@test-package"
    assert status["coreml_model_exists"] is False
    assert status["fallback_enabled"] is True
    assert status["fallback_active"] is True
    assert status["last_fallback_error"] == "package missing"
    assert status["coreml_min_confidence"] == 0.73
    assert status["coreml_context_mode"] in {"full", "windows"}
    assert status["coreml_pair_mode"] in {"answer", "qa", "claim"}
    assert status["coreml_entailment_threshold"] >= 0
    assert status["coreml_contradiction_threshold"] >= 0
    assert status["coreml_isolated_process"] in {True, False}
    assert "coreml_worker_failure_count" in status


def test_coreml_validator_low_confidence_maps_to_no_data():
    import numpy as np

    mlx_host = importlib.import_module("mlx_host")

    class FakeTokenizer:
        def __call__(self, *args, **kwargs):
            return {
                "input_ids": np.array([[1, 2, 3]], dtype=np.int32),
                "attention_mask": np.array([[1, 1, 1]], dtype=np.int32),
            }

    class FakeModel:
        def predict(self, payload):
            return {"logits": np.array([[0.2, 0.1, 0.0]], dtype=np.float32)}

    validator = mlx_host.CoreMLValidator(
        labels=["ENTAILMENT", "NEUTRAL", "CONTRADICTION"],
        min_confidence=0.9,
    )
    validator._tokenizer = FakeTokenizer()
    validator._model = FakeModel()

    result = validator.validate(
        mlx_host.ValidateRequest(question="q", answer="a", context="c")
    )

    assert result["raw"].startswith("WINDOW_")
    assert result["status"] == "NO_DATA"
    assert result["confidence_thresholded"] is True
    assert result["score"] < 0.9


def test_coreml_validator_worker_success(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "fake_validator_worker.py"
    worker.write_text(
        """
import json
import sys

for line in sys.stdin:
    req = json.loads(line)
    result = {"status": "VERIFIED", "raw": "fake", "backend": "coreml", "score": 0.99}
    print(json.dumps({"id": req["id"], "result": result}), flush=True)
""".strip()
    )

    validator = mlx_host.CoreMLValidatorWorker(
        worker_cmd=[sys.executable, "-u", str(worker)],
        worker_timeout_sec=2,
    )
    try:
        result = validator.validate(mlx_host.ValidateRequest(question="q", answer="a", context="c"))
        assert result["status"] == "VERIFIED"
        assert validator.worker_alive() is True
        assert validator.worker_start_count == 1
        assert validator.worker_failure_count == 0
    finally:
        validator.force_unload()


def test_coreml_validator_worker_circuit_after_exit(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "dead_validator_worker.py"
    worker.write_text("import sys\nsys.exit(42)\n")
    validator = mlx_host.CoreMLValidatorWorker(
        worker_cmd=[sys.executable, "-u", str(worker)],
        worker_timeout_sec=1,
        max_failures=1,
        failure_cooldown_sec=60,
    )

    with pytest.raises(Exception):
        validator.validate(mlx_host.ValidateRequest(question="q", answer="a", context="c"))
    assert validator.worker_failure_count == 1
    assert validator.circuit_open() is True
    with pytest.raises(RuntimeError, match="circuit open"):
        validator.validate(mlx_host.ValidateRequest(question="q", answer="a", context="c"))
    assert validator.worker_start_count == 1


def test_coreml_embedder_isolated_worker_success(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "fake_embed_worker.py"
    worker.write_text(
        """
import json
import sys

for line in sys.stdin:
    req = json.loads(line)
    vectors = [[1.0, 0.0, 0.0] for _ in req["texts"]]
    print(json.dumps({"id": req["id"], "vectors": vectors, "dim": 3}), flush=True)
""".strip()
    )

    embedder = mlx_host.CoreMLEmbedder(
        model_id="fake-model",
        model_path="fake.mlpackage",
        isolate_process=True,
        worker_timeout_sec=2,
        worker_cmd=[sys.executable, "-u", str(worker)],
        fallback=None,
    )

    try:
        assert embedder.encode(["one", "two"]) == [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        assert embedder.worker_alive() is True
        assert embedder.worker_pid() is not None
        assert embedder.worker_start_count == 1
        assert embedder.worker_failure_count == 0
    finally:
        embedder.force_unload()


def test_coreml_embedder_isolated_worker_falls_back_after_exit(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "dead_embed_worker.py"
    worker.write_text("import sys\nsys.exit(42)\n")

    class Fallback:
        backend = "sentence_transformers"
        _model = object()

        def __init__(self):
            self.called_with = None
            self.unloaded = False

        def encode(self, texts):
            self.called_with = list(texts)
            return [[0.0, 1.0, 0.0] for _ in texts]

        def force_unload(self):
            self.unloaded = True

    fallback = Fallback()
    embedder = mlx_host.CoreMLEmbedder(
        model_id="fake-model",
        model_path="fake.mlpackage",
        isolate_process=True,
        worker_timeout_sec=1,
        worker_cmd=[sys.executable, "-u", str(worker)],
        fallback=fallback,
    )

    assert embedder.encode(["one"]) == [[0.0, 1.0, 0.0]]
    assert fallback.called_with == ["one"]
    assert embedder.fallback_active is True
    assert embedder.last_fallback_error
    assert embedder.worker_failure_count == 1
    assert embedder.worker_alive() is False


def test_coreml_embedder_observes_worker_exit_after_success(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "one_shot_embed_worker.py"
    worker.write_text(
        """
import json
import sys

line = sys.stdin.readline()
req = json.loads(line)
print(json.dumps({"id": req["id"], "vectors": [[1.0]], "dim": 1}), flush=True)
sys.exit(42)
""".strip()
    )
    embedder = mlx_host.CoreMLEmbedder(
        model_id="fake-model",
        model_path="fake.mlpackage",
        isolate_process=True,
        worker_timeout_sec=2,
        worker_cmd=[sys.executable, "-u", str(worker)],
        fallback=None,
    )

    assert embedder.encode(["one"]) == [[1.0]]
    time.sleep(0.1)
    assert embedder.worker_alive() is False
    assert embedder.worker_exit_count == 1
    assert embedder.worker_last_returncode == 42
    assert embedder.worker_failure_count == 1
    assert "rc=42" in embedder.last_worker_error


def test_coreml_embedder_invalid_worker_vector_falls_back(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "zero_vector_embed_worker.py"
    worker.write_text(
        """
import json
import sys

for line in sys.stdin:
    req = json.loads(line)
    print(json.dumps({"id": req["id"], "vectors": [[0.0, 0.0]], "dim": 2}), flush=True)
""".strip()
    )

    class Fallback:
        _model = object()

        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def force_unload(self):
            pass

    embedder = mlx_host.CoreMLEmbedder(
        model_id="fake-model",
        model_path="fake.mlpackage",
        isolate_process=True,
        worker_timeout_sec=2,
        worker_cmd=[sys.executable, "-u", str(worker)],
        fallback=Fallback(),
    )

    assert embedder.encode(["one"]) == [[1.0, 0.0]]
    assert embedder.fallback_active is True
    assert "invalid vector norm" in embedder.last_fallback_error
    assert embedder.worker_failure_count == 1
    assert embedder.worker_alive() is False


def test_coreml_embedder_circuit_bypasses_worker_after_failures(tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    worker = tmp_path / "zero_vector_embed_worker.py"
    worker.write_text(
        """
import json
import sys

for line in sys.stdin:
    req = json.loads(line)
    print(json.dumps({"id": req["id"], "vectors": [[0.0]], "dim": 1}), flush=True)
""".strip()
    )

    class Fallback:
        _model = object()

        def __init__(self):
            self.calls = 0

        def encode(self, texts):
            self.calls += 1
            return [[1.0] for _ in texts]

        def force_unload(self):
            pass

    fallback = Fallback()
    embedder = mlx_host.CoreMLEmbedder(
        model_id="fake-model",
        model_path="fake.mlpackage",
        isolate_process=True,
        worker_timeout_sec=2,
        max_failures=1,
        failure_cooldown_sec=60,
        worker_cmd=[sys.executable, "-u", str(worker)],
        fallback=fallback,
    )

    assert embedder.encode(["one"]) == [[1.0]]
    assert embedder.circuit_open() is True
    starts_after_failure = embedder.worker_start_count
    assert embedder.encode(["two"]) == [[1.0]]
    assert embedder.worker_start_count == starts_after_failure
    assert fallback.calls == 2
    assert "circuit open" in embedder.last_fallback_error


def test_embedder_status_reports_coreml_worker_guardrails(monkeypatch, tmp_path):
    mlx_host = importlib.import_module("mlx_host")
    model = tmp_path / "embed.mlpackage"
    model.mkdir()
    embedder = mlx_host.CoreMLEmbedder(
        model_id="fake-model",
        model_path=str(model),
        isolate_process=True,
        worker_timeout_sec=7,
        worker_cmd=[sys.executable, "-c", "pass"],
        fallback=None,
    )
    embedder.worker_failure_count = 2
    embedder.worker_exit_count = 1
    embedder.worker_last_returncode = -11
    embedder.last_worker_error = "worker died"
    embedder.fallback_active = True
    embedder.last_fallback_error = "fallback used"

    monkeypatch.setattr(mlx_host, "embedder", embedder)

    status = mlx_host._embedder_status()

    assert status["backend"] == "coreml"
    assert status["coreml_model"] == str(model)
    assert status["coreml_model_exists"] is True
    assert status["coreml_model_id"] == "fake-model"
    assert status["coreml_isolated_process"] is True
    assert status["coreml_worker_timeout_sec"] == 7
    assert status["coreml_min_norm"] == mlx_host.COREML_EMBED_MIN_NORM
    assert status["coreml_max_norm"] == mlx_host.COREML_EMBED_MAX_NORM
    assert status["coreml_max_failures"] == mlx_host.COREML_EMBED_MAX_FAILURES
    assert status["coreml_failure_cooldown_sec"] == mlx_host.COREML_EMBED_FAILURE_COOLDOWN_SEC
    assert status["coreml_circuit_open"] is False
    assert status["coreml_worker_failure_count"] == 2
    assert status["coreml_worker_exit_count"] == 1
    assert status["coreml_worker_last_returncode"] == -11
    assert status["coreml_worker_last_error"] == "worker died"
    assert status["fallback_active"] is True
    assert status["last_fallback_error"] == "fallback used"
