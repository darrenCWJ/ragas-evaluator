"""Editable judge-model registry: defaults merge, custom models, enable/disable."""

import pytest

from app.services import judge_models
from pipeline.llm import JUDGE_MODELS


class TestListModels:
    async def test_defaults_returned_enabled(self, tmp_db):
        models = await judge_models.list_models()
        ids = {m["id"] for m in models}
        for default in JUDGE_MODELS:
            assert default["id"] in ids
        assert all(m["enabled"] for m in models)
        assert all(m["custom"] is False for m in models)

    async def test_defaults_include_current_generation_models(self, tmp_db):
        ids = {m["id"] for m in await judge_models.list_models()}
        assert "claude-opus-4-8" in ids
        assert "claude-sonnet-4-6" in ids
        assert "gpt-5.1" in ids


class TestCustomModels:
    async def test_add_and_list_custom_model(self, tmp_db):
        added = await judge_models.add_custom_model("my-gateway-model", "My Model", "gateway")
        assert added["custom"] is True

        models = await judge_models.list_models()
        match = next(m for m in models if m["id"] == "my-gateway-model")
        assert match["name"] == "My Model"
        assert match["provider"] == "gateway"
        assert match["enabled"] is True

    async def test_duplicate_custom_model_rejected(self, tmp_db):
        await judge_models.add_custom_model("dup-model", "Dup", "openai")
        with pytest.raises(ValueError, match="already exists"):
            await judge_models.add_custom_model("dup-model", "Dup again", "openai")

    async def test_builtin_id_rejected_as_custom(self, tmp_db):
        with pytest.raises(ValueError, match="built-in"):
            await judge_models.add_custom_model(JUDGE_MODELS[0]["id"], "Clone", "openai")

    async def test_unknown_provider_rejected(self, tmp_db):
        with pytest.raises(ValueError, match="Provider"):
            await judge_models.add_custom_model("x-model", "X", "nonsense")

    async def test_remove_custom_model(self, tmp_db):
        await judge_models.add_custom_model("temp-model", "Temp", "openai")
        assert judge_models.remove_custom_model("temp-model") is True
        ids = {m["id"] for m in await judge_models.list_models()}
        assert "temp-model" not in ids

    async def test_remove_unknown_model_returns_false(self, tmp_db):
        assert judge_models.remove_custom_model("never-existed") is False


class TestEnableDisable:
    async def test_disable_builtin_model(self, tmp_db):
        target = JUDGE_MODELS[0]["id"]
        assert await judge_models.set_model_enabled(target, False) is True
        models = await judge_models.list_models()
        match = next(m for m in models if m["id"] == target)
        assert match["enabled"] is False

    async def test_reenable_builtin_model(self, tmp_db):
        target = JUDGE_MODELS[0]["id"]
        await judge_models.set_model_enabled(target, False)
        await judge_models.set_model_enabled(target, True)
        match = next(m for m in await judge_models.list_models() if m["id"] == target)
        assert match["enabled"] is True

    async def test_disable_custom_model(self, tmp_db):
        await judge_models.add_custom_model("toggle-model", "Toggle", "gemini")
        await judge_models.set_model_enabled("toggle-model", False)
        match = next(
            m for m in await judge_models.list_models() if m["id"] == "toggle-model"
        )
        assert match["enabled"] is False

    async def test_enable_unknown_model_returns_false(self, tmp_db):
        assert await judge_models.set_model_enabled("ghost-model", True) is False
