"""Factory that creates a BotConnector from a config dict.

The config dict matches what is stored in ``bot_configs.config_json``
in the database (Phase 2).  The ``connector_type`` field selects
which connector class to instantiate.
"""

from __future__ import annotations

from typing import Any

from pipeline.bot_connectors.base import BotConnector
from pipeline.bot_connectors.claude_bot import ClaudeBotConnector
from pipeline.bot_connectors.custom import CustomBotConnector
from pipeline.bot_connectors.deepseek_bot import DeepSeekBotConnector
from pipeline.bot_connectors.gemini_bot import GeminiBotConnector
from pipeline.bot_connectors.glean import GleanBotConnector
from pipeline.bot_connectors.openai_bot import OpenAIBotConnector

# Maps connector_type values to their constructor + config mapping.
_REGISTRY: dict[str, type] = {
    "glean": GleanBotConnector,
    "openai": OpenAIBotConnector,
    "claude": ClaudeBotConnector,
    "deepseek": DeepSeekBotConnector,
    "gemini": GeminiBotConnector,
    "custom": CustomBotConnector,
}

SUPPORTED_TYPES = tuple(_REGISTRY.keys())


def create_connector(
    connector_type: str,
    config: dict[str, Any],
    *,
    prompt_for_sources: bool = False,
) -> BotConnector:
    """Instantiate a connector from a type string and config dict.

    Args:
        connector_type: One of ``SUPPORTED_TYPES``.
        config: Connector-specific config (api_key, model, endpoint, etc.).
        prompt_for_sources: Whether to inject source-citing instructions.

    Returns:
        An object satisfying the ``BotConnector`` protocol.

    Raises:
        ValueError: If ``connector_type`` is unknown.
    """
    cls = _REGISTRY.get(connector_type)
    if cls is None:
        raise ValueError(
            f"Unknown connector type {connector_type!r}. "
            f"Supported: {', '.join(SUPPORTED_TYPES)}"
        )

    # Glean and custom connectors don't use prompt_for_sources
    if connector_type in ("glean", "custom"):
        return cls(**config)  # type: ignore[no-any-return]

    # LLM connectors accept prompt_for_sources
    return cls(**config, prompt_for_sources=prompt_for_sources)  # type: ignore[no-any-return]
