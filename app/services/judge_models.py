"""Editable judge-model registry.

Merges the built-in JUDGE_MODELS defaults (or gateway-discovered models) with
user-managed rows in the judge_model_overrides table:

- is_custom=1 rows are user-added models (any provider).
- is_custom=0 rows toggle visibility of a built-in default (enabled flag).

The merged list powers every model picker in the UI (skill trials,
multi-LLM judge, experiments).
"""

import os

import db.init
from pipeline.llm import get_available_judge_models

_PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "gateway": "OPENAI_API_KEY",
}

ALLOWED_PROVIDERS = set(_PROVIDER_KEY_ENV)

# Default USD prices per 1M tokens (input, output) for cost ESTIMATES.
# Editable per model via the registry — vendor pricing changes; these are
# starting points, not billing truth.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-5.1": (1.25, 10.0),
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gemini-3-pro-preview": (2.0, 12.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.5),
}


def _provider_available(provider: str) -> bool:
    env_var = _PROVIDER_KEY_ENV.get(provider)
    if env_var is None:
        return True
    return bool(os.environ.get(env_var))


async def list_models() -> list[dict]:
    """Built-in (or gateway) models merged with custom/override rows."""
    base = await get_available_judge_models()
    merged: dict[str, dict] = {m["id"]: {**m, "custom": False, "enabled": True} for m in base}
    for model_id, entry in merged.items():
        default = DEFAULT_PRICES.get(model_id)
        entry["price_in_per_mtok"] = default[0] if default else None
        entry["price_out_per_mtok"] = default[1] if default else None

    conn = db.init.get_db()
    rows = conn.execute(
        "SELECT model_id, name, provider, is_custom, enabled, "
        "price_in_per_mtok, price_out_per_mtok FROM judge_model_overrides"
    ).fetchall()
    for row in rows:
        entry = dict(row)
        model_id = entry["model_id"]
        if entry["is_custom"]:
            merged[model_id] = {
                "id": model_id,
                "name": entry["name"],
                "provider": entry["provider"],
                "available": _provider_available(entry["provider"]),
                "custom": True,
                "enabled": bool(entry["enabled"]),
                "price_in_per_mtok": entry["price_in_per_mtok"],
                "price_out_per_mtok": entry["price_out_per_mtok"],
            }
        elif model_id in merged:
            merged[model_id]["enabled"] = bool(entry["enabled"])
            if entry["price_in_per_mtok"] is not None:
                merged[model_id]["price_in_per_mtok"] = entry["price_in_per_mtok"]
            if entry["price_out_per_mtok"] is not None:
                merged[model_id]["price_out_per_mtok"] = entry["price_out_per_mtok"]
    return list(merged.values())


async def price_map() -> dict[str, tuple[float, float]]:
    """model id → (price_in, price_out) per 1M tokens, for cost estimates."""
    prices: dict[str, tuple[float, float]] = {}
    for model in await list_models():
        p_in = model.get("price_in_per_mtok")
        p_out = model.get("price_out_per_mtok")
        if p_in is not None and p_out is not None:
            prices[model["id"]] = (float(p_in), float(p_out))
    return prices


def estimate_cost_usd(
    tokens_in: int, tokens_out: int, prices: tuple[float, float] | None
) -> float | None:
    if prices is None:
        return None
    return round(
        (tokens_in or 0) * prices[0] / 1_000_000 + (tokens_out or 0) * prices[1] / 1_000_000,
        6,
    )


async def add_custom_model(model_id: str, name: str, provider: str) -> dict:
    """Register a custom judge model. Raises ValueError on bad input/duplicate."""
    model_id = model_id.strip()
    name = name.strip() or model_id
    provider = provider.strip().lower()
    if not model_id:
        raise ValueError("Model id is required")
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"Provider must be one of: {', '.join(sorted(ALLOWED_PROVIDERS))}")

    base_ids = {m["id"] for m in await get_available_judge_models()}
    if model_id in base_ids:
        raise ValueError("Model id already exists as a built-in model")

    conn = db.init.get_db()
    try:
        conn.execute(
            "INSERT INTO judge_model_overrides (model_id, name, provider, is_custom, enabled) "
            "VALUES (?, ?, ?, 1, 1)",
            (model_id, name, provider),
        )
        conn.commit()
    except Exception as e:
        if db.init.is_integrity_error(e):
            raise ValueError("Model id already exists") from e
        raise
    return {
        "id": model_id,
        "name": name,
        "provider": provider,
        "available": _provider_available(provider),
        "custom": True,
        "enabled": True,
    }


async def update_model(
    model_id: str,
    enabled: bool | None = None,
    price_in_per_mtok: float | None = None,
    price_out_per_mtok: float | None = None,
) -> bool:
    """Update a model's enabled flag and/or price overrides.

    Works for custom AND built-in models (built-ins get an is_custom=0
    override row on first change). Returns False if the model is unknown.
    """
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM judge_model_overrides WHERE model_id = ?", (model_id,)
    ).fetchone()
    if existing is None:
        base = await get_available_judge_models()
        match = next((m for m in base if m["id"] == model_id), None)
        if match is None:
            return False
        conn.execute(
            "INSERT INTO judge_model_overrides (model_id, name, provider, is_custom, enabled) "
            "VALUES (?, ?, ?, 0, 1)",
            (model_id, match["name"], match["provider"]),
        )

    updates: list[str] = []
    params: list = []
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(1 if enabled else 0)
    if price_in_per_mtok is not None:
        updates.append("price_in_per_mtok = ?")
        params.append(price_in_per_mtok)
    if price_out_per_mtok is not None:
        updates.append("price_out_per_mtok = ?")
        params.append(price_out_per_mtok)
    if updates:
        params.append(model_id)
        conn.execute(
            f"UPDATE judge_model_overrides SET {', '.join(updates)} WHERE model_id = ?",
            params,
        )
    conn.commit()
    return True


async def set_model_enabled(model_id: str, enabled: bool) -> bool:
    """Enable/disable a model (custom or built-in). Returns False if unknown."""
    return await update_model(model_id, enabled=enabled)


def remove_custom_model(model_id: str) -> bool:
    """Delete a custom model (or reset a built-in override). Returns False if unknown."""
    conn = db.init.get_db()
    cursor = conn.execute(
        "DELETE FROM judge_model_overrides WHERE model_id = ?", (model_id,)
    )
    conn.commit()
    return cursor.rowcount > 0
