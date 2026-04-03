"""Chunking engine with 4 configurable strategies and 2-step pipeline support."""

import re

VALID_METHODS = {"recursive", "parent_child", "semantic", "fixed_overlap"}


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
    # Normalize frontend param names to engine param names
    _ALIASES = {
        "parent_chunk_size": "parent_size",
        "child_chunk_size": "child_size",
    }
    params = {_ALIASES.get(k, k): v for k, v in params.items()}
    # "overlap" means "chunk_overlap" for recursive (fixed_overlap already uses "overlap")
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


def chunk_text_pipeline(
    text: str,
    method: str,
    params: dict,
    step2_method: str | None,
    step2_params: dict | None,
) -> list[str]:
    """Run a 1- or 2-step chunking pipeline.

    Step 1: chunk_text(text, method, params)
    Step 2 (if provided): chunk_text on each step 1 result with step2_method/step2_params
    """
    step1_chunks = chunk_text(text, method, params)

    if step2_method is None or step2_params is None:
        return step1_chunks

    step2_chunks = []
    for chunk in step1_chunks:
        sub_chunks = chunk_text(chunk, step2_method, step2_params)
        step2_chunks.extend(sub_chunks)

    return step2_chunks


# --- Strategy implementations ---


def _recursive(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split by separators in priority order, merging pieces to target chunk_size."""
    separators = ["\n\n", "\n", ". ", " ", ""]

    def _split_with_separator(t: str, sep: str) -> list[str]:
        if sep == "":
            return list(t)
        parts = t.split(sep)
        # Re-attach separator to end of each part (except last)
        result = []
        for i, part in enumerate(parts):
            if i < len(parts) - 1:
                result.append(part + sep)
            else:
                result.append(part)
        return [p for p in result if p]

    def _merge_pieces(pieces: list[str], size: int, overlap: int) -> list[str]:
        chunks = []
        current = ""
        for piece in pieces:
            if len(current) + len(piece) <= size:
                current += piece
            else:
                if current:
                    chunks.append(current)
                # Add overlap from end of previous chunk
                if overlap > 0 and chunks:
                    prev = chunks[-1]
                    overlap_text = prev[-overlap:] if len(prev) >= overlap else prev
                    current = overlap_text + piece
                else:
                    current = piece
        if current:
            chunks.append(current)
        return chunks

    # Try each separator level
    for sep in separators:
        pieces = _split_with_separator(text, sep)
        if all(len(p) <= chunk_size for p in pieces) or sep == "":
            return _merge_pieces(pieces, chunk_size, chunk_overlap)

    return [text]


def _parent_child(text: str, parent_size: int = 1000, child_size: int = 200) -> list[str]:
    """Split into parent chunks, then sub-split each into child chunks.

    Returns flat list of child chunk strings (consistent return type).
    """
    parents = _recursive(text, chunk_size=parent_size, chunk_overlap=0)
    children = []
    for parent in parents:
        child_chunks = _recursive(parent, chunk_size=child_size, chunk_overlap=0)
        children.extend(child_chunks)
    return children


def _semantic(text: str, max_chunk_size: int = 1000, breakpoint_threshold: float = 0.5) -> list[str]:
    """Split on semantic boundaries: headings, double newlines, single newlines.

    Falls back to recursive split for oversized sections.
    """
    # Split on headings (lines starting with #)
    sections = re.split(r'(?=^#{1,6}\s)', text, flags=re.MULTILINE)
    sections = [s for s in sections if s.strip()]

    # If no heading splits, try double newlines
    if len(sections) <= 1:
        sections = [s.strip() for s in text.split("\n\n") if s.strip()]

    # If still no splits, try single newlines
    if len(sections) <= 1:
        sections = [s.strip() for s in text.split("\n") if s.strip()]

    chunks = []
    current = ""

    for section in sections:
        if len(section) > max_chunk_size:
            # Flush current buffer
            if current:
                chunks.append(current)
                current = ""
            # Fall back to recursive for oversized section
            sub_chunks = _recursive(section, chunk_size=max_chunk_size, chunk_overlap=0)
            chunks.extend(sub_chunks)
        elif len(current) + len(section) + 1 <= max_chunk_size:
            current = current + "\n" + section if current else section
        else:
            if current:
                chunks.append(current)
            current = section

    if current:
        chunks.append(current)

    return chunks


def _fixed_overlap(text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """Fixed-size character window with overlap."""
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(text), step):
        chunk = text[i:i + chunk_size]
        if chunk:
            chunks.append(chunk)
        # Stop if we've captured the end
        if i + chunk_size >= len(text):
            break

    return chunks
