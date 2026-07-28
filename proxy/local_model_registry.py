"""Единый реестр локальных MLX-моделей чата.

Идентификатор модели не должен расходиться между host, chat, smeta, router и warmup.
Выбор оператора через env имеет приоритет над DEFAULT_LOCAL_MLX_MODEL.
"""

from __future__ import annotations


DEFAULT_LOCAL_MLX_MODEL = "mlx-community/Qwen3.5-9B-OptiQ-4bit"

LOCAL_MLX_MODEL_CHOICES = {
    "mlx-community/Qwen3.5-4B-MLX-4bit": "4B — быстрый и малопамятный · диагностический",
    "mlx-community/Qwen3.5-9B-MLX-4bit": "9B uniform 4-bit · резерв совместимости",
    DEFAULT_LOCAL_MLX_MODEL: "9B OptiQ · основной для Mac с 24 ГБ",
}
