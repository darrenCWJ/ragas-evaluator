"""Pydantic models and shared constants for the API."""

import os

from pydantic import BaseModel, Field, field_validator


# --- Validation sets ---

VALID_QUESTION_STATUSES = {"pending", "approved", "rejected", "edited"}
VALID_ANNOTATION_STATUSES = {"approved", "rejected", "edited"}
VALID_BULK_ACTIONS = {"approve", "reject", "approve_all", "reject_all"}
BULK_ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "approve_all": "approved",
    "reject_all": "rejected",
}

VALID_CHUNK_METHODS = {"recursive", "parent_child", "semantic", "fixed_overlap", "markdown", "token"}
VALID_EMBEDDING_TYPES = {"dense_openai", "dense_sentence_transformers", "bm25_sparse"}
VALID_SEARCH_TYPES = {"dense", "sparse", "hybrid"}
VALID_RESPONSE_MODES = {"single_shot", "multi_step"}
VALID_EXPERIMENT_STATUSES = {"pending", "running", "completed", "failed"}
VALID_QUERY_TYPES = {"single_hop_specific", "multi_hop_abstract", "multi_hop_specific"}

ALLOWED_LLM_PARAMS = {
    "temperature",
    "max_tokens",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
}

MAX_CHUNKS_FOR_GENERATION = int(os.environ.get("MAX_CHUNKS_FOR_GENERATION", 0))
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB
MAX_BASELINE_CSV_SIZE = 10 * 1024 * 1024  # 10MB
MAX_BASELINE_ROWS = 1000
ALLOWED_FILE_TYPES = {".txt", ".pdf"}

DEFAULT_EXPERIMENT_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "factual_correctness",
    "semantic_similarity",
]


# --- Request / response models ---


class TestGenRequest(BaseModel):
    chunks: list[str]
    testset_size: int = 10
    num_personas: int = 3
    custom_personas: list[dict] | None = None
    use_personas: bool = True


class PersonaGenRequest(BaseModel):
    chunks: list[str]
    num_personas: int = 3
    custom_personas: list[dict] | None = None


class TestSetCreate(BaseModel):
    chunk_config_id: int
    name: str | None = None
    testset_size: int = 10
    num_personas: int = 3
    custom_personas: list[dict] | None = None
    use_personas: bool = True
    query_distribution: dict[str, float] | None = None
    chunk_sample_size: int = 0
    num_workers: int = 4

    @field_validator("testset_size")
    @classmethod
    def validate_testset_size(cls, v: int) -> int:
        if v < 1 or v > 400:
            raise ValueError("testset_size must be between 1 and 400")
        return v

    @field_validator("num_personas")
    @classmethod
    def validate_num_personas(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("num_personas must be between 1 and 10")
        return v

    @field_validator("num_workers")
    @classmethod
    def validate_num_workers(cls, v: int) -> int:
        if v < 1 or v > 8:
            raise ValueError("num_workers must be between 1 and 8")
        return v


class QuestionAnnotation(BaseModel):
    status: str
    user_edited_answer: str | None = None
    user_notes: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_ANNOTATION_STATUSES:
            raise ValueError(
                f"Invalid status '{v}'. Must be one of: {', '.join(sorted(VALID_ANNOTATION_STATUSES))}"
            )
        return v


class BulkAnnotation(BaseModel):
    action: str
    question_ids: list[int] | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in VALID_BULK_ACTIONS:
            raise ValueError(
                f"Invalid action '{v}'. Must be one of: {', '.join(sorted(VALID_BULK_ACTIONS))}"
            )
        return v


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Project name must not be blank")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Project name must not be blank")
        return v


class ApiConfigCreate(BaseModel):
    endpoint_url: str
    api_key: str | None = None
    headers_json: str | None = None

    @field_validator("endpoint_url")
    @classmethod
    def url_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Endpoint URL must not be blank")
        return v


class ChunkConfigCreate(BaseModel):
    name: str
    method: str
    params: dict
    step2_method: str | None = None
    step2_params: dict | None = None
    filter_params: dict | None = None

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in VALID_CHUNK_METHODS:
            raise ValueError(
                f"method must be one of: {', '.join(sorted(VALID_CHUNK_METHODS))}"
            )
        return v

    @field_validator("step2_method")
    @classmethod
    def validate_step2_method(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CHUNK_METHODS:
            raise ValueError(
                f"step2_method must be one of: {', '.join(sorted(VALID_CHUNK_METHODS))}"
            )
        return v

    def model_post_init(self, __context) -> None:
        if (self.step2_method is None) != (self.step2_params is None):
            raise ValueError(
                "step2_method and step2_params must both be set or both be None"
            )


class EmbeddingConfigCreate(BaseModel):
    name: str
    type: str
    model_name: str
    params: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_EMBEDDING_TYPES:
            raise ValueError(
                f"type must be one of: {', '.join(sorted(VALID_EMBEDDING_TYPES))}"
            )
        return v


class EmbedRequest(BaseModel):
    chunk_config_id: int
    use_contextual_prefix: bool = False


class DocumentContextUpdate(BaseModel):
    context_label: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class HybridSearchRequest(BaseModel):
    query: str
    dense_config_id: int
    sparse_config_id: int
    top_k: int = 5
    alpha: float = 0.5

    @field_validator("alpha")
    @classmethod
    def validate_alpha(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("alpha must be between 0.0 and 1.0")
        return v


class RagConfigCreate(BaseModel):
    name: str
    embedding_config_id: int
    chunk_config_id: int
    search_type: str
    llm_model: str
    top_k: int = 5
    system_prompt: str | None = None
    llm_params: dict | None = None
    sparse_config_id: int | None = None
    alpha: float | None = None
    response_mode: str = "single_shot"
    max_steps: int = 3
    reranker_model: str | None = None
    reranker_top_k: int | None = None

    @field_validator("search_type")
    @classmethod
    def validate_search_type(cls, v: str) -> str:
        if v not in VALID_SEARCH_TYPES:
            raise ValueError(
                f"search_type must be one of: {', '.join(sorted(VALID_SEARCH_TYPES))}"
            )
        return v

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, v: str) -> str:
        if v not in VALID_RESPONSE_MODES:
            raise ValueError(
                f"response_mode must be one of: {', '.join(sorted(VALID_RESPONSE_MODES))}"
            )
        return v

    @field_validator("max_steps")
    @classmethod
    def validate_max_steps(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("max_steps must be between 1 and 10")
        return v

    @field_validator("llm_params")
    @classmethod
    def validate_llm_params(cls, v: dict | None) -> dict | None:
        if v is not None:
            unknown = set(v.keys()) - ALLOWED_LLM_PARAMS
            if unknown:
                raise ValueError(
                    f"Unknown llm_params keys: {', '.join(sorted(unknown))}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_LLM_PARAMS))}"
                )
        return v

    def model_post_init(self, __context) -> None:
        if self.search_type == "hybrid":
            if self.sparse_config_id is None:
                raise ValueError(
                    "sparse_config_id is required when search_type is 'hybrid'"
                )
            if self.alpha is None:
                raise ValueError("alpha is required when search_type is 'hybrid'")
            if self.alpha < 0.0 or self.alpha > 1.0:
                raise ValueError("alpha must be between 0.0 and 1.0")


class RagConfigUpdate(BaseModel):
    name: str | None = None
    embedding_config_id: int | None = None
    chunk_config_id: int | None = None
    search_type: str | None = None
    llm_model: str | None = None
    top_k: int | None = None
    system_prompt: str | None = None
    llm_params: dict | None = None
    sparse_config_id: int | None = None
    alpha: float | None = None
    response_mode: str | None = None
    max_steps: int | None = None
    reranker_model: str | None = None
    reranker_top_k: int | None = None

    @field_validator("search_type")
    @classmethod
    def validate_search_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_SEARCH_TYPES:
            raise ValueError(
                f"search_type must be one of: {', '.join(sorted(VALID_SEARCH_TYPES))}"
            )
        return v

    @field_validator("response_mode")
    @classmethod
    def validate_response_mode(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_RESPONSE_MODES:
            raise ValueError(
                f"response_mode must be one of: {', '.join(sorted(VALID_RESPONSE_MODES))}"
            )
        return v

    @field_validator("max_steps")
    @classmethod
    def validate_max_steps(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 10):
            raise ValueError("max_steps must be between 1 and 10")
        return v

    @field_validator("llm_params")
    @classmethod
    def validate_llm_params(cls, v: dict | None) -> dict | None:
        if v is not None:
            unknown = set(v.keys()) - ALLOWED_LLM_PARAMS
            if unknown:
                raise ValueError(
                    f"Unknown llm_params keys: {', '.join(sorted(unknown))}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_LLM_PARAMS))}"
                )
        return v


class RagQueryRequest(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        if len(v) > 10000:
            raise ValueError("query must not exceed 10000 characters")
        return v


class ExperimentCreate(BaseModel):
    test_set_id: int
    rag_config_id: int | None = None
    bot_config_id: int | None = None
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 200:
            raise ValueError("name must not exceed 200 characters")
        return v

    def model_post_init(self, __context) -> None:
        if self.rag_config_id is None and self.bot_config_id is None:
            raise ValueError("Either rag_config_id or bot_config_id must be provided")
        if self.rag_config_id is not None and self.bot_config_id is not None:
            raise ValueError("Provide rag_config_id or bot_config_id, not both")


class ExperimentRunRequest(BaseModel):
    metrics: list[str] | None = None


class SuggestionUpdate(BaseModel):
    implemented: bool


class ApplySuggestionRequest(BaseModel):
    override_value: str | None = None
    experiment_name: str | None = None

    @field_validator("experiment_name")
    @classmethod
    def validate_experiment_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("experiment_name must not be empty")
            if len(v) > 200:
                raise ValueError("experiment_name must not exceed 200 characters")
        return v


class BatchApplyItem(BaseModel):
    suggestion_id: int
    override_value: str | None = None


class BatchApplyRequest(BaseModel):
    items: list[BatchApplyItem]
    experiment_name: str | None = None

    @field_validator("experiment_name")
    @classmethod
    def validate_experiment_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("experiment_name must not be empty")
            if len(v) > 200:
                raise ValueError("experiment_name must not exceed 200 characters")
        return v


VALID_CUSTOM_METRIC_TYPES = {"integer_range", "similarity", "rubrics", "instance_rubrics"}


class CustomMetricCreate(BaseModel):
    name: str
    metric_type: str
    prompt: str | None = None
    rubrics: dict[str, str] | None = None
    min_score: int = 1
    max_score: int = 5

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 100:
            raise ValueError("name must not exceed 100 characters")
        # Ensure name is a valid metric key (lowercase, underscores)
        import re
        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            raise ValueError("name must be lowercase with underscores only (e.g. 'my_metric')")
        return v

    @field_validator("metric_type")
    @classmethod
    def validate_metric_type(cls, v: str) -> str:
        if v not in VALID_CUSTOM_METRIC_TYPES:
            raise ValueError(
                f"metric_type must be one of: {', '.join(sorted(VALID_CUSTOM_METRIC_TYPES))}"
            )
        return v

    def model_post_init(self, __context) -> None:
        if self.metric_type in ("integer_range", "similarity") and not self.prompt:
            raise ValueError("prompt is required for integer_range and similarity metric types")
        if self.metric_type == "rubrics" and not self.rubrics:
            raise ValueError("rubrics are required for rubrics metric type")
        if self.min_score >= self.max_score:
            raise ValueError("min_score must be less than max_score")
        if self.min_score < 0 or self.max_score > 10:
            raise ValueError("score range must be between 0 and 10")


VALID_CONNECTOR_TYPES = {"glean", "openai", "claude", "deepseek", "gemini", "custom"}


class BotConfigCreate(BaseModel):
    name: str
    connector_type: str
    config_json: dict
    prompt_for_sources: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 200:
            raise ValueError("name must not exceed 200 characters")
        return v

    @field_validator("connector_type")
    @classmethod
    def validate_connector_type(cls, v: str) -> str:
        if v not in VALID_CONNECTOR_TYPES:
            raise ValueError(
                f"connector_type must be one of: {', '.join(sorted(VALID_CONNECTOR_TYPES))}"
            )
        return v


VALID_HUMAN_RATINGS = {"accurate", "partially_accurate", "inaccurate"}


class HumanAnnotationCreate(BaseModel):
    experiment_result_id: int
    rating: str
    notes: str | None = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: str) -> str:
        if v not in VALID_HUMAN_RATINGS:
            raise ValueError(
                f"rating must be one of: {', '.join(sorted(VALID_HUMAN_RATINGS))}"
            )
        return v


class HumanAnnotationBatch(BaseModel):
    annotations: list[HumanAnnotationCreate]

    @field_validator("annotations")
    @classmethod
    def validate_non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("annotations list must not be empty")
        return v


class BotConfigUpdate(BaseModel):
    name: str | None = None
    connector_type: str | None = None
    config_json: dict | None = None
    prompt_for_sources: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("name must not be empty")
        return v

    @field_validator("connector_type")
    @classmethod
    def validate_connector_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_CONNECTOR_TYPES:
            raise ValueError(
                f"connector_type must be one of: {', '.join(sorted(VALID_CONNECTOR_TYPES))}"
            )
        return v
