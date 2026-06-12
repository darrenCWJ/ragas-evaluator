"""Document upload and management routes."""

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import db.init
from app.models import DocumentContextUpdate, DocumentReprocessRequest
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


def _save_original_file(project_id: int, filename: str, data: bytes) -> str:
    """Persist an original upload under data/uploads; return the relative path."""
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


async def _extract_document_text(
    filename: str,
    ext: str,
    content_bytes: bytes,
    extract_tables: bool,
    describe_images: bool,
) -> tuple[str, int]:
    """Parse a text document with processing options applied.

    Returns (text, images_described). Shared by upload and re-process.
    """
    from pipeline.document_parsers import (
        DocumentParseError,
        extract_embedded_images,
        parse_document,
    )

    try:
        text = parse_document(filename, ext, content_bytes, extract_tables=extract_tables)
    except DocumentParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    images_described = 0
    if describe_images:
        from pipeline.vision import extract_image_text, pick_vision_model

        pick_vision_model()  # fail fast (422) when no vision provider is configured
        sections: list[str] = []
        for img in extract_embedded_images(ext, content_bytes):
            try:
                described = await extract_image_text(img["data"], img["mime"])
            except HTTPException as e:
                logger.warning(
                    "Vision description failed for an image in %s: %s", filename, e.detail
                )
                continue
            sections.append(f"[Embedded image — {img['label']}]\n{described}")
            images_described += 1
        if sections:
            text = text + "\n\n" + "\n\n".join(sections)
    return text, images_described


@router.post("/projects/{project_id}/documents", status_code=201)
async def upload_project_document(
    project_id: int,
    file: UploadFile = File(...),
    # Processing options — how the document becomes retrievable text:
    # extract_tables: DOCX/PPTX tables rendered as markdown rows (default on).
    # describe_images: embedded images (PPTX/DOCX/PDF) described by the vision
    # LLM and appended to the text (default off — costs LLM calls).
    extract_tables: bool = Form(True),
    describe_images: bool = Form(False),
):
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
            stored_path = _save_original_file(project_id, filename, content_bytes)
        except OSError:
            logger.exception("Failed to persist original image %s", filename)
            stored_path = None
        metadata = {"source_kind": "image", "original_path": stored_path}
    else:
        text, images_described = await _extract_document_text(
            filename, ext, content_bytes, extract_tables, describe_images
        )
        try:
            stored_path = _save_original_file(project_id, filename, content_bytes)
        except OSError:
            logger.exception("Failed to persist original file %s", filename)
            stored_path = None
        metadata = {
            "original_path": stored_path,
            "processing": {
                "extract_tables": extract_tables,
                "describe_images": describe_images,
                "images_described": images_described,
            },
        }

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
    result["source_kind"] = (metadata or {}).get("source_kind", "text")
    return result


@router.post("/projects/{project_id}/documents/{document_id}/reprocess")
async def reprocess_document(project_id: int, document_id: int, req: DocumentReprocessRequest):
    """Re-extract a document's text from its stored original file.

    Lets users apply new processing options (tables, vision image
    descriptions) without re-uploading. Chunks generated from the old text
    are NOT touched — re-generate chunk configs afterwards to pick up the
    new content.
    """
    conn = db.init.get_db()
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ? AND project_id = ?",
        (document_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except (TypeError, ValueError):
        meta = {}
    original_rel = meta.get("original_path")
    if not original_rel:
        raise HTTPException(
            status_code=409,
            detail="Original file was not stored (uploaded before re-processing existed) — re-upload it instead",
        )
    data_root = Path(DATA_DIR).resolve()
    original = (data_root / original_rel).resolve()
    if data_root not in original.parents or not original.exists():
        raise HTTPException(status_code=409, detail="Original file is missing on disk — re-upload it instead")

    content_bytes = original.read_bytes()
    ext = row["file_type"]
    if ext in IMAGE_FILE_TYPES:
        from pipeline.vision import extract_image_text

        text = await extract_image_text(content_bytes, _IMAGE_MIME[ext])
        images_described = 1
    else:
        text, images_described = await _extract_document_text(
            row["filename"], ext, content_bytes, req.extract_tables, req.describe_images
        )

    meta["processing"] = {
        "extract_tables": req.extract_tables,
        "describe_images": req.describe_images,
        "images_described": images_described,
    }
    conn.execute(
        "UPDATE documents SET content = ?, metadata_json = ? WHERE id = ?",
        (text, json.dumps(meta), document_id),
    )
    conn.commit()
    return {
        "id": document_id,
        "filename": row["filename"],
        "images_described": images_described,
        "content_chars": len(text),
        "note": "Re-generate chunk configs to apply the new text to retrieval",
    }


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
