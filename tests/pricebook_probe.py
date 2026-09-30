"""Pytest plugin that hides the operator's ценовая база for a whole run.

Only ``data/price_base`` is hidden — the verified norm base in ``data/smeta_base`` stays
reachable — so a failure under this plugin can only mean one thing: a pinned amount was
read from whatever parquet happens to be installed on this machine instead of from the
deterministic book the test hands in (``tests/test_rim_lsr_trace_service.py`` ``_Book``,
``tests/lsr_gold_pricebook.py``).

Why the patching happens here and not with ``monkeypatch``: ``available_pricebooks`` and
``resolve_pricebook_path`` bind ``DEFAULT_PRICE_ROOT`` as a *default argument*, frozen at
import time, so replacing the module attribute alone leaves the call sites untouched.
The defaults have to be rewritten on the function objects (positional for one,
keyword-only for the other).

Used by ``tests/test_pricebook_hermeticity_830.py``; run by hand:

    PYTHONPATH=tests .venv/.../python -m pytest -p pricebook_probe -q <tests>
"""

from pathlib import Path

# A missing directory: `available_pricebooks` returns [] for a root that does not exist.
EMPTY_PRICE_ROOT = Path(".test-tmp/pricebook-probe-absent-root")


def pytest_configure(config):
    from proxy.services import fgis_price_service as fps

    fps.DEFAULT_PRICE_ROOT = EMPTY_PRICE_ROOT

    defaults = list(fps.available_pricebooks.__defaults__)
    defaults[0] = EMPTY_PRICE_ROOT
    fps.available_pricebooks.__defaults__ = tuple(defaults)

    fps.resolve_pricebook_path.__kwdefaults__ = {
        **fps.resolve_pricebook_path.__kwdefaults__,
        "root": EMPTY_PRICE_ROOT,
    }
    fps.get_pricebook.cache_clear()

    if fps.available_pricebooks() != []:
        raise RuntimeError("pricebook probe failed: installed books are still resolvable")

    # Tells a nested pytest run (the hermeticity guard itself) that this process already
    # has no book, so the guard does not spawn another one.
    import os

    os.environ["LES_PRICEBOOK_PROBE"] = "1"
