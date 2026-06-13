"""W7.2 — `lesctl doctor`: одношаговый отчёт о здоровье рантайма ЛЕС.

Проверяет порты сервисов, RAM/диск, доступность GPU/Metal, инференс/эмбеддер,
наличие конфигурации облачных провайдеров и коллекции Qdrant. Офлайн-безопасен:
упавший сервис даёт одну понятную строку с причиной, а не трейсбэк.

Переиспользует хелперы из ``tools.les_runtime_control`` (порты/health/память) и
стандартную библиотеку (socket/shutil/platform/urllib) — без новых зависимостей.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools import les_runtime_control as rc


ROOT = Path(__file__).resolve().parents[1]

# Облачные провайдеры по политике проекта — только OpenRouter и OpenAI.
CLOUD_PROVIDERS = (
    ("OpenRouter", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"),
    ("OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL"),
)


@dataclass
class Check:
    """Одна строка отчёта."""

    name: str
    status: str  # ok | warn | fail
    detail: str
    value: str = ""


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)
    ok_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    overall: str = "ok"

    def add(self, check: Check) -> None:
        self.checks.append(check)


# ---------------------------------------------------------------------------
# Отдельные проверки (каждая ловит свои исключения и возвращает причину)
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _http_json(url: str, timeout: float = 5.0) -> tuple[int, dict | None, str]:
    """Возвращает (http_code, json_or_None, error_message)."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "lesctl-doctor"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = getattr(response, "status", 0) or 0
            raw = response.read()
        try:
            return code, json.loads(raw.decode("utf-8")), ""
        except Exception:
            return code, None, ""
    except urllib.error.HTTPError as error:
        return error.code, None, f"HTTP {error.code}"
    except ConnectionRefusedError:
        return 0, None, "connection refused"
    except Exception as error:  # socket timeout, DNS, и т.п.
        return 0, None, str(error)[:120]


def check_ports(report: DoctorReport) -> None:
    """Порты сервисов: proxy :8050, sovushka :8051, mlx :8080, qdrant :6333."""
    targets = [
        ("proxy", 8050),
        ("sovushka", 8051),
        ("mlx", 8080),
        ("qdrant", 6333),
    ]
    for label, port in targets:
        service = rc.SERVICES.get(label) or rc.SERVICES.get("ui" if label == "sovushka" else label)
        title = service.title if service else label
        if _port_open("127.0.0.1", port):
            report.add(Check(f"порт {label} :{port}", "ok", f"{title} слушает", value="LISTEN"))
        else:
            report.add(
                Check(
                    f"порт {label} :{port}",
                    "fail",
                    f"{title} — UNREACHABLE (connection refused)",
                    value="DOWN",
                )
            )


def check_ram(report: DoctorReport) -> None:
    free_gb, total_gb, swap_pct = rc._host_memory()
    if free_gb is None or total_gb is None:
        report.add(Check("RAM", "warn", "не удалось определить (psutil недоступен)"))
        return
    used_pct = 100.0 * (1 - free_gb / total_gb) if total_gb else 0.0
    swap = f", swap {swap_pct:.0f}%" if swap_pct is not None else ""
    detail = f"свободно {free_gb:.1f} / {total_gb:.1f} GB ({used_pct:.0f}% занято){swap}"
    if free_gb < 4:
        status = "fail"
    elif free_gb < 12:
        status = "warn"
    else:
        status = "ok"
    report.add(Check("RAM", status, detail, value=f"{free_gb:.1f}GB free"))


def check_disk(report: DoctorReport) -> None:
    try:
        usage = shutil.disk_usage(str(ROOT))
    except Exception as error:
        report.add(Check("Диск", "warn", f"не удалось определить: {error}"))
        return
    free_gb = usage.free / 1e9
    total_gb = usage.total / 1e9
    used_pct = 100.0 * usage.used / usage.total if usage.total else 0.0
    detail = f"свободно {free_gb:.0f} / {total_gb:.0f} GB ({used_pct:.0f}% занято)"
    if free_gb < 10:
        status = "fail"
    elif free_gb < 30:
        status = "warn"
    else:
        status = "ok"
    report.add(Check("Диск", status, detail, value=f"{free_gb:.0f}GB free"))


def check_gpu(report: DoctorReport) -> None:
    """GPU/Metal: на Apple Silicon инференс идёт через Metal (MLX/Core ML)."""
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin" and machine == "arm64":
        # На Apple Silicon Metal присутствует всегда; system_profiler медленный — не дёргаем.
        report.add(
            Check(
                "GPU / Metal",
                "ok",
                f"Apple Silicon ({machine}) — Metal доступен (MLX/Core ML)",
                value="metal",
            )
        )
        return
    if system == "Linux":
        if shutil.which("nvidia-smi"):
            report.add(Check("GPU / Metal", "ok", "NVIDIA GPU (nvidia-smi доступен)", value="cuda"))
        else:
            report.add(
                Check(
                    "GPU / Metal",
                    "warn",
                    "GPU не обнаружен (nvidia-smi отсутствует) — инференс на CPU",
                    value="cpu",
                )
            )
        return
    report.add(Check("GPU / Metal", "warn", f"платформа {system}/{machine} — ускорителя нет", value="cpu"))


def check_inference(report: DoctorReport) -> None:
    """MLX-инференс :8080 — main-модель и эмбеддер."""
    mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080").rstrip("/")
    code, data, err = _http_json(f"{mlx_url}/api/health")
    if data is None:
        cause = err or f"HTTP {code}" if code else "нет ответа"
        report.add(
            Check(
                "MLX инференс :8080",
                "fail",
                f"UNREACHABLE ({cause})",
                value="DOWN",
            )
        )
        report.add(Check("Эмбеддер", "fail", "недоступен (MLX-host не отвечает)", value="DOWN"))
        return

    main = data.get("main_model")
    if isinstance(main, dict):
        path = str(main.get("path", "?")).split("/")[-1]
        loaded = bool(main.get("loaded"))
    else:
        path, loaded = "?", bool(main)
    report.add(
        Check(
            "MLX инференс :8080",
            "ok" if loaded else "warn",
            f"main-модель {path} ({'загружена' if loaded else 'ленивая, не в памяти'})",
            value="loaded" if loaded else "lazy",
        )
    )

    embed = data.get("embed_model")
    if isinstance(embed, dict):
        embed_loaded = bool(embed.get("loaded"))
        embed_path = str(embed.get("path", "")).split("/")[-1]
    else:
        embed_loaded = bool(embed)
        embed_path = ""
    suffix = f" {embed_path}" if embed_path else ""
    report.add(
        Check(
            "Эмбеддер",
            "ok",
            f"доступен{suffix} ({'в памяти' if embed_loaded else 'ленивый'})",
            value="loaded" if embed_loaded else "lazy",
        )
    )


def check_proxy(report: DoctorReport) -> None:
    """Proxy :8050 — API-шлюз."""
    proxy_url = "http://127.0.0.1:8050"
    code, data, err = _http_json(f"{proxy_url}/api/health")
    if code and code < 500:
        status = "ok"
        detail = "API-шлюз отвечает (/api/health)"
        if isinstance(data, dict) and data.get("status"):
            detail += f" — status={data['status']}"
        report.add(Check("Proxy :8050 health", status, detail, value=f"HTTP {code}"))
    else:
        cause = err or (f"HTTP {code}" if code else "connection refused")
        report.add(Check("Proxy :8050 health", "fail", f"UNREACHABLE ({cause})", value="DOWN"))


def check_providers(report: DoctorReport) -> None:
    """Конфигурация провайдеров: активный LLM-провайдер + наличие облачных ключей."""
    active = os.getenv("LES_LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "mlx"
    report.add(Check("LLM-провайдер (активный)", "ok", f"{active}", value=active))
    for name, key_env, model_env in CLOUD_PROVIDERS:
        has_key = bool(os.getenv(key_env, "").strip())
        model = os.getenv(model_env, "").strip()
        if has_key:
            model_note = f", модель {model}" if model else " (модель не указана)"
            report.add(
                Check(
                    f"Провайдер {name}",
                    "ok",
                    f"ключ задан{model_note}",
                    value="key set",
                )
            )
        else:
            report.add(
                Check(
                    f"Провайдер {name}",
                    "warn",
                    f"ключ {key_env} не задан (облачный фолбэк недоступен)",
                    value="no key",
                )
            )


def check_collections(report: DoctorReport) -> None:
    """Коллекции Qdrant :6333 и активная коллекция профиля."""
    qdrant_url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
    code, data, err = _http_json(f"{qdrant_url}/collections")
    if data is None:
        cause = err or (f"HTTP {code}" if code else "connection refused")
        report.add(Check("Qdrant :6333 коллекции", "fail", f"UNREACHABLE ({cause})", value="DOWN"))
        return

    collections = []
    try:
        collections = data.get("result", {}).get("collections", []) or []
    except Exception:
        pass
    names = [c.get("name", "?") for c in collections]

    active = None
    try:
        from backend.rag_config import rag_collection_name

        active = rag_collection_name()
    except Exception:
        active = None

    if not names:
        report.add(Check("Qdrant :6333 коллекции", "warn", "коллекций нет", value="0 cols"))
        return

    if active and active not in names:
        report.add(
            Check(
                "Qdrant :6333 коллекции",
                "warn",
                f"{len(names)} коллекций; активная '{active}' ОТСУТСТВУЕТ ({', '.join(names[:6])})",
                value=f"{len(names)} cols",
            )
        )
        return

    suffix = f"; активная '{active}'" if active else ""
    report.add(
        Check(
            "Qdrant :6333 коллекции",
            "ok",
            f"{len(names)} коллекций{suffix}",
            value=f"{len(names)} cols",
        )
    )


# ---------------------------------------------------------------------------
# Сборка отчёта и вывод
# ---------------------------------------------------------------------------


def build_report() -> DoctorReport:
    report = DoctorReport()
    # Порядок: порты → ресурсы → GPU → инференс/эмбеддер → proxy → провайдеры → коллекции.
    for fn in (
        check_ports,
        check_ram,
        check_disk,
        check_gpu,
        check_inference,
        check_proxy,
        check_providers,
        check_collections,
    ):
        try:
            fn(report)
        except Exception as error:  # никакая проверка не должна ронять doctor
            report.add(Check(fn.__name__, "warn", f"проверка не выполнена: {error}"))

    report.ok_count = sum(1 for c in report.checks if c.status == "ok")
    report.warn_count = sum(1 for c in report.checks if c.status == "warn")
    report.fail_count = sum(1 for c in report.checks if c.status == "fail")
    report.overall = "fail" if report.fail_count else ("warn" if report.warn_count else "ok")
    return report


_MARK = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}


def _line(check: Check) -> str:
    mark = _MARK.get(check.status, "?")
    value = f" {check.value}" if check.value else ""
    return f"[{mark:4}] {check.name:26}{value:>14}  {check.detail}"


def print_report(report: DoctorReport, *, stream=None) -> None:
    stream = stream or sys.stdout
    print("LES doctor — отчёт о здоровье рантайма (W7.2)", file=stream)
    print("=" * 72, file=stream)
    for check in report.checks:
        print(_line(check), file=stream)
    print("=" * 72, file=stream)
    print(
        f"итог: {_MARK[report.overall]} "
        f"({report.ok_count} ok / {report.warn_count} warn / {report.fail_count} fail)",
        file=stream,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LES runtime health doctor (W7.2).")
    parser.add_argument("--json", action="store_true", help="вывести машинно-читаемый JSON")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print_report(report)
    # exit-код: 0 — всё ок/предупреждения, 1 — есть FAIL (сломанный сервис).
    return 1 if report.fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
