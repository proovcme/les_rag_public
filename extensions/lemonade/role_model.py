"""Единственный источник имени модели для совместимого хоста — реестр ролей.

Адаптер исторически переписывал модель каждого запроса своим `LEMONADE_MODEL` из
окружения. Это делало его вторым источником истины рядом с реестром: служебные
вызовы LES шлют имя MLX-модели, которой на Windows нет, а окружение отставало от
смены роли — из-за чего вендор поднимал вторую 35B-модель на 11 ГБ рядом с
выбранной и память кончалась.

Здесь только решение «какое имя отправить вендору». Чтение реестра и HTTP живут
снаружи, чтобы правило проверялось без базы и сети.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable


def _identity(value: object) -> str:
    return str(value or "").strip().casefold().removesuffix(":latest")


def select_chat_model(
    requested: object,
    *,
    catalogue: Iterable[str],
    role_model: object,
    fallback: object = "",
) -> str:
    """Имя модели для вендора: запрошенная, затем роль, затем запасное значение.

    Запрошенная модель уважается, только если вендор её действительно знает —
    иначе запрос отправился бы с именем, которое вендор не сможет загрузить.
    """
    known = {_identity(item): str(item).strip() for item in catalogue if str(item or "").strip()}
    wanted = _identity(requested)
    if wanted and wanted in known:
        return known[wanted]
    for candidate in (role_model, fallback):
        name = str(candidate or "").strip()
        if name:
            return name
    return ""


class RoleModelCache:
    """Имя модели роли с коротким кэшем: реестр читается с диска, а не на каждый токен."""

    def __init__(
        self,
        loader: Callable[[], str],
        *,
        ttl_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._ttl = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._value = ""
        self._expires_at = 0.0

    def get(self) -> str:
        now = self._clock()
        if self._value and now < self._expires_at:
            return self._value
        try:
            value = str(self._loader() or "").strip()
        except Exception:  # noqa: BLE001 — реестр недоступен: остаётся прежнее имя
            value = ""
        if value:
            self._value = value
            self._expires_at = now + self._ttl
        return self._value


def answer_model_from_registry() -> str:
    """Идентификатор модели, привязанной к роли «Ответы», или пустая строка."""
    from proxy.services.model_connection_contracts import ConnectionRole
    from proxy.services.model_connection_registry_service import ModelConnectionRegistry

    registry = ModelConnectionRegistry()
    binding = registry.get_role_binding(ConnectionRole.ANSWER)
    if binding is None:
        return ""
    revision = registry.get_revision(binding.connection_revision_id)
    return str(getattr(revision, "model_id", "") or "").strip()
