import importlib


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
