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


def _provider_available(provider: str) -> bool:
    env_var = _PROVIDER_KEY_ENV.get(provider)
    if env_var is None:
        return True
    return bool(os.environ.get(env_var))


async def list_models() -> list[dict]:
    """Built-in (or gateway) models merged with custom/override rows."""
    base = await get_available_judge_models()
    merged: dict[str, dict] = {m["id"]: {**m, "custom": False, "enabled": True} for m in base}

    conn = db.init.get_db()
    rows = conn.execute(
        "SELECT model_id, name, provider, is_custom, enabled FROM judge_model_overrides"
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
            }
        elif model_id in merged:
            merged[model_id]["enabled"] = bool(entry["enabled"])
    return list(merged.values())


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


async def set_model_enabled(model_id: str, enabled: bool) -> bool:
    """Enable/disable a model (custom or built-in). Returns False if unknown."""
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id, is_custom FROM judge_model_overrides WHERE model_id = ?", (model_id,)
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE judge_model_overrides SET enabled = ? WHERE model_id = ?",
            (1 if enabled else 0, model_id),
        )
        conn.commit()
        return True

    base = await get_available_judge_models()
    match = next((m for m in base if m["id"] == model_id), None)
    if match is None:
        return False
    conn.execute(
        "INSERT INTO judge_model_overrides (model_id, name, provider, is_custom, enabled) "
        "VALUES (?, ?, ?, 0, ?)",
        (model_id, match["name"], match["provider"], 1 if enabled else 0),
    )
    conn.commit()
    return True


def remove_custom_model(model_id: str) -> bool:
    """Delete a custom model (or reset a built-in override). Returns False if unknown."""
    conn = db.init.get_db()
    cursor = conn.execute(
        "DELETE FROM judge_model_overrides WHERE model_id = ?", (model_id,)
    )
    conn.commit()
    return cursor.rowcount > 0
