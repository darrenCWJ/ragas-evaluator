"""Document upload and management routes."""

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

import db.init
from app.models import DocumentContextUpdate
from config import (
    ALLOWED_FILE_TYPES,
    DATA_DIR,
    IMAGE_FILE_TYPES,
    MAX_IMAGE_UPLOAD_SIZE,
    MAX_UPLOAD_SIZE,
)

router = APIRouter(prefix="/api", tags=["documents"])
logger = logging.getLogger(__name__)

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _save_original_image(project_id: int, filename: str, data: bytes) -> str:
    """Persist the original image under data/uploads; return the relative path."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name).strip(".")
    if not safe_name:
        safe_name = "image"
    upload_dir = (Path(DATA_DIR) / "uploads" / str(int(project_id))).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = (upload_dir / safe_name).resolve()
    # Containment check — the sanitized name must stay inside the upload dir
    if upload_dir not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid image filename")
    counter = 1
    while target.exists():
        target = upload_dir / f"{target.stem}_{counter}{target.suffix}"
        counter += 1
    target.write_bytes(data)
    return str(target.relative_to(Path(DATA_DIR).resolve()))


@router.post("/projects/{project_id}/documents", status_code=201)
async def upload_project_document(project_id: int, file: UploadFile = File(...)):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_FILE_TYPES))}",
        )

    content_bytes = await file.read()
    if len(content_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 50MB size limit")

    metadata: dict | None = None
    if ext in IMAGE_FILE_TYPES:
        if len(content_bytes) > MAX_IMAGE_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Image exceeds {MAX_IMAGE_UPLOAD_SIZE // (1024 * 1024)}MB size limit",
            )
        from pipeline.vision import extract_image_text

        text = await extract_image_text(content_bytes, _IMAGE_MIME[ext])
        try:
            stored_path = _save_original_image(project_id, filename, content_bytes)
        except OSError:
            logger.exception("Failed to persist original image %s", filename)
            stored_path = None
        metadata = {"source_kind": "image", "original_path": stored_path}
    else:
        from pipeline.document_parsers import DocumentParseError, parse_document

        try:
            text = parse_document(filename, ext, content_bytes)
        except DocumentParseError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    cursor = conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content, metadata_json) VALUES (?, ?, ?, ?, ?)",
        (project_id, filename, ext, text, json.dumps(metadata) if metadata else None),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, filename, file_type, created_at FROM documents WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    result = dict(row)
    result["source_kind"] = metadata["source_kind"] if metadata else "text"
    return result


@router.get("/projects/{project_id}/documents")
async def list_project_documents(project_id: int):
    conn = db.init.get_db()

    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = conn.execute(
        "SELECT id, filename, file_type, context_label, created_at FROM documents WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/projects/{project_id}/documents/{document_id}")
async def get_project_document(project_id: int, document_id: int):
    conn = db.init.get_db()

    row = conn.execute(
        "SELECT id, project_id, filename, file_type, content, context_label, created_at FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@router.patch("/projects/{project_id}/documents/{document_id}/context-label")
async def update_document_context_label(project_id: int, document_id: int, req: DocumentContextUpdate):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Document not found")
    conn.execute(
        "UPDATE documents SET context_label = ? WHERE id = ?",
        (req.context_label.strip(), document_id),
    )
    conn.commit()
    return {"detail": "Context label updated", "context_label": req.context_label.strip()}


@router.delete("/projects/{project_id}/documents")
async def delete_all_project_documents(project_id: int):
    conn = db.init.get_db()
    project = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conn.execute("DELETE FROM documents WHERE project_id = ?", (project_id,))
    conn.commit()
    return {"detail": "All documents deleted"}


@router.delete("/projects/{project_id}/documents/{document_id}")
async def delete_project_document(project_id: int, document_id: int):
    conn = db.init.get_db()
    existing = conn.execute(
        "SELECT id FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Document not found")
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    conn.commit()
    return {"detail": "Document deleted"}
