"""Integration tests for FastAPI API endpoints.

Uses httpx AsyncClient with a real in-memory database.
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def test_db(tmp_path):
    """Initialize a fresh test database."""
    db_path = tmp_path / "test_api.db"
    import db.init as db_module

    with patch("db.init.DATABASE_PATH", db_path):
        db_module._connection = None
        conn = db_module.init_db()
        yield conn, db_path
        conn.close()
        db_module._connection = None


@pytest.fixture
async def client(test_db):
    """Create an async test client with patched database."""
    conn, db_path = test_db
    import db.init as db_module

    # Patch get_db to return our test connection
    with patch("db.init.get_db", return_value=conn):
        from app import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestHealthCheck:
    async def test_health_ok(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestProjectCRUD:
    async def test_create_project(self, client):
        resp = await client.post("/api/projects", json={"name": "Test Project", "description": "A test"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Project"
        assert data["description"] == "A test"
        assert "id" in data

    async def test_list_projects(self, client):
        await client.post("/api/projects", json={"name": "P1"})
        await client.post("/api/projects", json={"name": "P2"})
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    async def test_get_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "GetMe"})
        pid = create_resp.json()["id"]
        resp = await client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "GetMe"

    async def test_get_project_not_found(self, client):
        resp = await client.get("/api/projects/99999")
        assert resp.status_code == 404

    async def test_duplicate_name_409(self, client):
        await client.post("/api/projects", json={"name": "Unique"})
        resp = await client.post("/api/projects", json={"name": "Unique"})
        assert resp.status_code == 409

    async def test_blank_name_422(self, client):
        resp = await client.post("/api/projects", json={"name": "   "})
        assert resp.status_code == 422

    async def test_update_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Old Name"})
        pid = create_resp.json()["id"]
        resp = await client.put(f"/api/projects/{pid}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_delete_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "ToDelete"})
        pid = create_resp.json()["id"]
        resp = await client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 200
        # Verify it's gone
        get_resp = await client.get(f"/api/projects/{pid}")
        assert get_resp.status_code == 404


class TestChunkConfigs:
    async def _create_project(self, client) -> int:
        resp = await client.post("/api/projects", json={"name": f"ChunkProj"})
        return resp.json()["id"]

    async def test_create_chunk_config(self, client):
        pid = await self._create_project(client)
        resp = await client.post(
            f"/api/projects/{pid}/chunk-configs",
            json={"name": "recursive-500", "method": "recursive", "params": {"chunk_size": 500}},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "recursive-500"
        assert data["method"] == "recursive"

    async def test_list_chunk_configs(self, client):
        pid = await self._create_project(client)
        await client.post(
            f"/api/projects/{pid}/chunk-configs",
            json={"name": "c1", "method": "recursive", "params": {}},
        )
        resp = await client.get(f"/api/projects/{pid}/chunk-configs")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_get_chunk_config(self, client):
        pid = await self._create_project(client)
        create_resp = await client.post(
            f"/api/projects/{pid}/chunk-configs",
            json={"name": "c1", "method": "semantic", "params": {"max_chunk_size": 1000}},
        )
        cid = create_resp.json()["id"]
        resp = await client.get(f"/api/projects/{pid}/chunk-configs/{cid}")
        assert resp.status_code == 200
        assert resp.json()["method"] == "semantic"

    async def test_delete_chunk_config(self, client):
        pid = await self._create_project(client)
        create_resp = await client.post(
            f"/api/projects/{pid}/chunk-configs",
            json={"name": "del", "method": "recursive", "params": {}},
        )
        cid = create_resp.json()["id"]
        resp = await client.delete(f"/api/projects/{pid}/chunk-configs/{cid}")
        assert resp.status_code == 200


class TestDocuments:
    async def _create_project(self, client) -> int:
        resp = await client.post("/api/projects", json={"name": "DocProj"})
        return resp.json()["id"]

    async def test_upload_and_list(self, client):
        pid = await self._create_project(client)
        # Upload a text file
        resp = await client.post(
            f"/api/projects/{pid}/documents",
            files={"file": ("test.txt", b"Hello world content", "text/plain")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "test.txt"

        # List documents
        list_resp = await client.get(f"/api/projects/{pid}/documents")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

    async def test_get_document(self, client):
        pid = await self._create_project(client)
        upload = await client.post(
            f"/api/projects/{pid}/documents",
            files={"file": ("doc.txt", b"Content here", "text/plain")},
        )
        doc_id = upload.json()["id"]
        resp = await client.get(f"/api/projects/{pid}/documents/{doc_id}")
        assert resp.status_code == 200
        assert "content" in resp.json()

    async def test_delete_document(self, client):
        pid = await self._create_project(client)
        upload = await client.post(
            f"/api/projects/{pid}/documents",
            files={"file": ("del.txt", b"delete me", "text/plain")},
        )
        doc_id = upload.json()["id"]
        resp = await client.delete(f"/api/projects/{pid}/documents/{doc_id}")
        assert resp.status_code == 200


class TestEmbeddingConfigs:
    async def _create_project(self, client) -> int:
        resp = await client.post("/api/projects", json={"name": "EmbedProj"})
        return resp.json()["id"]

    async def test_create_embedding_config(self, client):
        pid = await self._create_project(client)
        resp = await client.post(
            f"/api/projects/{pid}/embedding-configs",
            json={
                "name": "openai-small",
                "type": "dense_openai",
                "model_name": "text-embedding-3-small",
                "params": {},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "dense_openai"

    async def test_list_embedding_configs(self, client):
        pid = await self._create_project(client)
        await client.post(
            f"/api/projects/{pid}/embedding-configs",
            json={"name": "e1", "type": "dense_openai", "model_name": "m", "params": {}},
        )
        resp = await client.get(f"/api/projects/{pid}/embedding-configs")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestRagConfigs:
    async def _setup(self, client):
        """Create project + chunk config + embedding config."""
        proj = await client.post("/api/projects", json={"name": "RagProj"})
        pid = proj.json()["id"]
        chunk = await client.post(
            f"/api/projects/{pid}/chunk-configs",
            json={"name": "c1", "method": "recursive", "params": {}},
        )
        embed = await client.post(
            f"/api/projects/{pid}/embedding-configs",
            json={"name": "e1", "type": "dense_openai", "model_name": "m", "params": {}},
        )
        return pid, chunk.json()["id"], embed.json()["id"]

    async def test_create_rag_config(self, client):
        pid, cid, eid = await self._setup(client)
        resp = await client.post(
            f"/api/projects/{pid}/rag-configs",
            json={
                "name": "rag1",
                "embedding_config_id": eid,
                "chunk_config_id": cid,
                "search_type": "dense",
                "llm_model": "gpt-4o-mini",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "rag1"

    async def test_list_rag_configs(self, client):
        pid, cid, eid = await self._setup(client)
        await client.post(
            f"/api/projects/{pid}/rag-configs",
            json={
                "name": "rag1",
                "embedding_config_id": eid,
                "chunk_config_id": cid,
                "search_type": "dense",
                "llm_model": "gpt-4o-mini",
            },
        )
        resp = await client.get(f"/api/projects/{pid}/rag-configs")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
