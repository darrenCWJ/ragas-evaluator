"""Document upload and management routes."""

import io
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.models import ALLOWED_FILE_TYPES, MAX_UPLOAD_SIZE, DocumentContextUpdate
import db.init

router = APIRouter(prefix="/api", tags=["documents"])


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

    if ext == ".txt":
        text = content_bytes.decode("utf-8", errors="ignore")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    cursor = conn.execute(
        "INSERT INTO documents (project_id, filename, file_type, content) VALUES (?, ?, ?, ?)",
        (project_id, filename, ext, text),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, filename, file_type, created_at FROM documents WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return dict(row)


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
