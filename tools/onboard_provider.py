"""First-run provider onboarding (L2 wizard).

The desktop bootstrap (Mac/Win) runs this once before the stack starts so the
very first launch has a working chat backend instead of an empty key. It is the
*minimal* counterpart to the full provider panel in the Sovushka GUI
(``proxy/routers/settings.py``): pick a provider, paste a key/model, write it to
``.env``. Everything finer (live model switching, presets, mail) stays in the
GUI per the gui-first principle — this only covers the cold-start gap the GUI
cannot, because the GUI isn't up yet.

LLM-minimalism (ADR-11): the recommended default is local (MLX on Mac, ollama on
Win) — cloud is opt-in and requires an explicit key. We never invent a key.

Env keys written here mirror the GUI contract exactly:
    LES_LLM_PROVIDER  ∈ {mlx, ollama, openrouter, openai, lemonade}
    <PROVIDER>_MODEL / <PROVIDER>_API_KEY / <PROVIDER>_BASE_URL
    LES_CLOUD_CONSENT  (true when a cloud provider is chosen)

Usage:
    uv run python tools/onboard_provider.py                 # interactive
    uv run python tools/onboard_provider.py --provider mlx  # non-interactive
    uv run python tools/onboard_provider.py --show          # print current choice
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

# provider -> (label, is_cloud, default_model, default_base_url)
PROVIDERS: dict[str, tuple[str, bool, str, str]] = {
    "mlx": ("MLX (локально, Apple Silicon) — рекомендуется на Mac", False,
            "mlx-community/Qwen3.5-4B-MLX-4bit", ""),
    "ollama": ("Ollama (локально, любой ПК) — рекомендуется на Windows", False,
               "", "http://127.0.0.1:11434"),
    "openrouter": ("OpenRouter (облако) — нужен ключ", True,
                   "", "https://openrouter.ai/api/v1"),
    "openai": ("OpenAI / OpenAI-совместимый (облако) — нужен ключ", True,
               "", "https://api.openai.com/v1"),
    "lemonade": ("Lemonade Server (локальный OpenAI-совместимый)", False,
                 "", "http://127.0.0.1:13305/api/v1"),
}

# Per-provider env-key prefixes (mlx has no key/base_url — it runs in-process).
_PREFIX = {
    "ollama": "OLLAMA",
    "openrouter": "OPENROUTER",
    "openai": "OPENAI",
    "lemonade": "LEMONADE",
}


def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or ENV_PATH
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def persist_env(updates: dict[str, str], path: Path | None = None) -> None:
    """Idempotently update keys in .env (replace existing, append new).

    Mirrors ``proxy.routers.settings._persist_env`` so first-run and the GUI
    write the same file the same way.
    """
    path = path or ENV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_updates(provider: str, *, api_key: str = "", model: str = "", base_url: str = "") -> dict[str, str]:
    """Compute the .env updates for a provider choice. Pure → unit-testable."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {sorted(PROVIDERS)}")
    _label, is_cloud, default_model, default_base = PROVIDERS[provider]
    updates: dict[str, str] = {"LES_LLM_PROVIDER": provider}

    if provider == "mlx":
        # MLX runs in-process; model is shared between host start and proxy.
        chosen = (model or default_model).strip()
        if chosen:
            updates["MLX_MODEL"] = chosen
            updates["LLM_MODEL"] = chosen
    else:
        prefix = _PREFIX[provider]
        chosen_base = (base_url or default_base).strip()
        if chosen_base:
            updates[f"{prefix}_BASE_URL"] = chosen_base
        chosen_model = (model or default_model).strip()
        if chosen_model:
            updates[f"{prefix}_MODEL"] = chosen_model
        if api_key.strip():
            updates[f"{prefix}_API_KEY"] = api_key.strip()

    updates["LES_CLOUD_CONSENT"] = "true" if is_cloud else "false"
    return updates


def already_configured(path: Path | None = None) -> bool:
    """True when .env already names a provider — first-run should not nag again."""
    return bool(read_env(path).get("LES_LLM_PROVIDER", "").strip())


# ── interactive ─────────────────────────────────────────────────────────────
def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{msg}{suffix}: ").strip()
    except EOFError:
        ans = ""
    return ans or default


def run_interactive() -> dict[str, str]:
    print("ЛЕС · первичная настройка движка чата\n")
    keys = list(PROVIDERS)
    for i, key in enumerate(keys, 1):
        print(f"  {i}. {key:<10} — {PROVIDERS[key][0]}")
    raw = _prompt("\nВыберите движок (номер или имя)", "1")
    if raw.isdigit() and 1 <= int(raw) <= len(keys):
        provider = keys[int(raw) - 1]
    elif raw in PROVIDERS:
        provider = raw
    else:
        print(f"[onboard] неизвестный выбор {raw!r} — беру mlx", file=sys.stderr)
        provider = "mlx"

    _label, is_cloud, default_model, default_base = PROVIDERS[provider]
    api_key = ""
    if is_cloud:
        print("\nОблачный провайдер требует API-ключ (хранится локально в .env).")
        api_key = _prompt("API-ключ")
    base_url = _prompt("Base URL", default_base) if default_base else ""
    model = _prompt("Модель (Enter — оставить по умолчанию/задать в GUI)", default_model)

    updates = build_updates(provider, api_key=api_key, model=model, base_url=base_url)
    if is_cloud and not api_key:
        print("[onboard] внимание: ключ не задан — впишите его позже в GUI «Настройки».",
              file=sys.stderr)
    return updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LES first-run provider onboarding.")
    parser.add_argument("--provider", choices=list(PROVIDERS), help="non-interactive: pick provider")
    parser.add_argument("--api-key", default="", help="API key for a cloud provider")
    parser.add_argument("--model", default="", help="override model id")
    parser.add_argument("--base-url", default="", help="override base url")
    parser.add_argument("--show", action="store_true", help="print current provider and exit")
    parser.add_argument("--skip-if-configured", action="store_true",
                        help="do nothing if .env already names a provider (first-run guard)")
    args = parser.parse_args(argv)

    if args.show:
        env = read_env()
        print(env.get("LES_LLM_PROVIDER", "(none)"))
        return 0

    if args.skip_if_configured and already_configured():
        print(f"[onboard] провайдер уже настроен ({read_env().get('LES_LLM_PROVIDER')}) — пропускаю")
        return 0

    if args.provider:
        updates = build_updates(args.provider, api_key=args.api_key, model=args.model,
                                base_url=args.base_url)
    elif sys.stdin.isatty():
        updates = run_interactive()
    else:
        # No TTY and no --provider: keep the safe local default rather than block boot.
        print("[onboard] нет TTY и не задан --provider — ставлю локальный mlx по умолчанию")
        updates = build_updates("mlx")

    persist_env(updates)
    print(f"[onboard] записано в {ENV_PATH}: LES_LLM_PROVIDER={updates['LES_LLM_PROVIDER']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
