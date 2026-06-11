"""Chunking engine backed by langchain-text-splitters with 6 strategies and 2-step pipeline support."""

from langchain_text_splitters import (
    CharacterTextSplitter,
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)

VALID_METHODS = {"recursive", "parent_child", "semantic", "fixed_overlap", "markdown", "token"}

_PARAM_ALIASES = {
    "parent_chunk_size": "parent_size",
    "child_chunk_size": "child_size",
}


def _coerce_numeric(params: dict) -> dict:
    """Coerce string values that look numeric to int or float."""
    out = {}
    for k, v in params.items():
        if isinstance(v, str):
            try:
                out[k] = int(v)
                continue
            except ValueError:
                pass
            try:
                out[k] = float(v)
                continue
            except ValueError:
                pass
        out[k] = v
    return out


def chunk_text(text: str, method: str, params: dict) -> list[str]:
    """Split text into chunks using the specified strategy.

    Returns list[str] for all strategies.
    Raises ValueError for invalid method names.
    Returns [] for empty/whitespace-only text.
    """
    params = _coerce_numeric(params)
    params = {_PARAM_ALIASES.get(k, k): v for k, v in params.items()}
    if method == "recursive" and "overlap" in params and "chunk_overlap" not in params:
        params["chunk_overlap"] = params.pop("overlap")

    if method not in VALID_METHODS:
        raise ValueError(f"Invalid chunking method '{method}'. Must be one of: {', '.join(sorted(VALID_METHODS))}")

    if not text or not text.strip():
        return []

    if method == "recursive":
        return _recursive(text, **params)
    elif method == "parent_child":
        return _parent_child(text, **params)
    elif method == "semantic":
        return _semantic(text, **params)
    elif method == "fixed_overlap":
        return _fixed_overlap(text, **params)
    elif method == "markdown":
        return _markdown(text, **params)
    elif method == "token":
        return _token(text, **params)

    return [text]


def filter_chunks(
    chunks: list[str],
    min_char_length: int = 0,
    min_word_count: int = 0,
    max_whitespace_ratio: float = 1.0,
) -> list[str]:
    """Filter out low-quality chunks based on configurable thresholds.

    Args:
        chunks: List of chunk strings to filter.
        min_char_length: Drop chunks shorter than this (0 = disabled).
        min_word_count: Drop chunks with fewer words than this (0 = disabled).
        max_whitespace_ratio: Drop chunks where whitespace/special char ratio exceeds this (1.0 = disabled).
    """
    filtered = []
    for chunk in chunks:
        stripped = chunk.strip()
        if not stripped:
            continue
        if min_char_length > 0 and len(stripped) < min_char_length:
            continue
        if min_word_count > 0 and len(stripped.split()) < min_word_count:
            continue
        if max_whitespace_ratio < 1.0:
            non_alnum = sum(1 for c in stripped if not c.isalnum())
            ratio = non_alnum / len(stripped) if stripped else 1.0
            if ratio > max_whitespace_ratio:
                continue
        filtered.append(chunk)
    return filtered


def chunk_text_pipeline(
    text: str,
    method: str,
    params: dict,
    step2_method: str | None,
    step2_params: dict | None,
    filter_params: dict | None = None,
) -> list[str]:
    """Run a 1- or 2-step chunking pipeline with optional post-filtering.

    Step 1: chunk_text(text, method, params)
    Step 2 (if provided): chunk_text on each step 1 result with step2_method/step2_params
    Filter (if provided): remove low-quality chunks based on filter_params
    """
    step1_chunks = chunk_text(text, method, params)

    if step2_method is None or step2_params is None:
        chunks = step1_chunks
    else:
        step2_chunks = []
        for chunk in step1_chunks:
            sub_chunks = chunk_text(chunk, step2_method, step2_params)
            step2_chunks.extend(sub_chunks)
        chunks = step2_chunks

    if filter_params:
        chunks = filter_chunks(
            chunks,
            min_char_length=filter_params.get("min_char_length", 0),
            min_word_count=filter_params.get("min_word_count", 0),
            max_whitespace_ratio=filter_params.get("max_whitespace_ratio", 1.0),
        )

    return chunks


# --- Strategy implementations ---


def _recursive(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split by separators in priority order using RecursiveCharacterTextSplitter."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    return splitter.split_text(text)


def _parent_child(text: str, parent_size: int = 1000, child_size: int = 200) -> list[str]:
    """Split into parent chunks, then sub-split each into child chunks.

    Returns flat list of child chunk strings.
    """
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=parent_size,
        chunk_overlap=0,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=child_size,
        chunk_overlap=0,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    parents = parent_splitter.split_text(text)
    children = []
    for parent in parents:
        children.extend(child_splitter.split_text(parent))
    return children


def _semantic(text: str, max_chunk_size: int = 1000, breakpoint_threshold: float = 0.5) -> list[str]:
    """Split on structural boundaries: headings, double newlines, single newlines.

    Uses RecursiveCharacterTextSplitter with heading-aware separators.
    Falls back to smaller separators for oversized sections.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chunk_size,
        chunk_overlap=0,
        separators=[
            "\n#{1,6} ",   # Markdown headings
            "\n\n",        # Double newlines (paragraphs)
            "\n",          # Single newlines
            ". ",          # Sentences
            " ",           # Words
            "",            # Characters
        ],
        is_separator_regex=True,
        length_function=len,
    )
    return splitter.split_text(text)


def _fixed_overlap(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """Fixed-size character window with overlap."""
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    splitter = CharacterTextSplitter(
        separator="",
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
    )
    return splitter.split_text(text)


def _markdown(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
    """Markdown-aware splitting that respects document structure.

    Splits on headings, code blocks, and list items before falling back
    to paragraph and sentence boundaries.
    """
    splitter = MarkdownTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_text(text)


def _token(text: str, chunk_size: int = 256, chunk_overlap: int = 30, encoding_name: str = "cl100k_base") -> list[str]:
    """Token-based splitting aligned to embedding model token limits.

    Uses tiktoken to count tokens, ensuring chunks are within model limits.
    Default encoding (cl100k_base) matches OpenAI ada-002 / text-embedding-3-*.
    """
    splitter = TokenTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        encoding_name=encoding_name,
    )
    return splitter.split_text(text)
