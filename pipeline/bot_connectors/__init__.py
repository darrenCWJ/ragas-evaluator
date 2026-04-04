"""Bot connector package — unified interface for querying external chatbots."""

from pipeline.bot_connectors.base import BotConnector, BotResponse, Citation
from pipeline.bot_connectors.factory import SUPPORTED_TYPES, create_connector

__all__ = [
    "BotConnector",
    "BotResponse",
    "Citation",
    "SUPPORTED_TYPES",
    "create_connector",
]
