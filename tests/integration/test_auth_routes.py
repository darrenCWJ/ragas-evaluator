"""Integration tests for user auth, project isolation, and the admin role."""

import uuid

import pytest
from fastapi.testclient import TestClient

import app as app_module
import db.init
import main
from app.services import auth as auth_service

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clean_auth_state():
    """Keep auth tests hermetic: no users before/after, cache + limiter reset.

    Without this, users created here would flip the whole app into enforced
    mode for every other test file sharing the database.
    """
    def _reset():
        conn = db.init.get_db()
        conn.execute("DELETE FROM project_members")
        # Projects created during tests reference users — orphan them before
        # deleting accounts (owner_id is nullable by design for legacy rows).
        conn.execute("UPDATE projects SET owner_id = NULL WHERE owner_id IS NOT NULL")
        conn.execute("DELETE FROM users")
        conn.commit()
        app_module._auth_active_cache = False
        with auth_service._attempts_lock:
            auth_service._attempts.clear()

    # init_db may not have run yet on first test — reset only if tables exist
    try:
        _reset()
    except Exception:
        pass
    yield
    _reset()


def _client() -> TestClient:
    return TestClient(main.app)


def _register(client: TestClient, email: str, name: str = "User", password: str = "hunter2hunter2"):
    return client.post(
        "/api/auth/register", json={"email": email, "name": name, "password": password}
    )


def _make_project(client: TestClient, name: str | None = None) -> int:
    resp = client.post(
        "/api/projects",
        json={"name": name or f"auth-it-{uuid.uuid4().hex[:8]}", "description": ""},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestBootstrapAndSessions:
    def test_open_mode_before_any_user(self):
        with _client() as c:
            assert c.get("/api/auth/status").json()["auth_enabled"] is False
            # Everything works anonymously, exactly as before
            pid = _make_project(c)
            assert c.get(f"/api/projects/{pid}").status_code == 200
            c.delete(f"/api/projects/{pid}")

    def test_first_user_is_admin_and_activates_auth(self):
        with _client() as c:
            r = _register(c, "admin@example.com", "Admin")
            assert r.status_code == 201, r.text
            assert r.json()["role"] == "admin"
            assert c.get("/api/auth/status").json()["auth_enabled"] is True

            # Same client carries the session cookie → still works
            me = c.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["email"] == "admin@example.com"

        # Fresh client without a session → locked out
        with _client() as anon:
            assert anon.get("/api/projects").status_code == 401

    def test_second_user_is_regular(self):
        with _client() as c:
            _register(c, "admin@example.com")
            r = _register(c, "user@example.com")
            assert r.json()["role"] == "user"

    def test_login_logout_cycle(self):
        with _client() as c:
            _register(c, "a@example.com", password="hunter2hunter2")
        with _client() as c:
            bad = c.post(
                "/api/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
            )
            assert bad.status_code == 401
            ok = c.post(
                "/api/auth/login",
                json={"email": "a@example.com", "password": "hunter2hunter2"},
            )
            assert ok.status_code == 200
            assert c.get("/api/auth/me").status_code == 200
            c.post("/api/auth/logout")
            assert c.get("/api/auth/me").status_code == 401

    def test_duplicate_email_409(self):
        with _client() as c:
            _register(c, "dup@example.com")
            assert _register(c, "dup@example.com").status_code == 409

    def test_machine_token_acts_as_admin(self, monkeypatch):
        monkeypatch.setenv("RAGAS_API_KEY", "machine-secret")
        with _client() as c:
            _register(c, "admin@example.com")
            pid = _make_project(c)
        with _client() as machine:
            r = machine.get(
                f"/api/projects/{pid}",
                headers={"Authorization": "Bearer machine-secret"},
            )
            assert r.status_code == 200


class TestProjectIsolation:
    def test_users_only_see_their_projects(self):
        with _client() as alice:
            _register(alice, "alice@example.com", "Alice")
            alice_pid = _make_project(alice, f"alice-{uuid.uuid4().hex[:6]}")

            with _client() as bob:
                _register(bob, "bob@example.com", "Bob")
                bob_pid = _make_project(bob, f"bob-{uuid.uuid4().hex[:6]}")

                bob_list = {p["id"] for p in bob.get("/api/projects").json()}
                assert bob_pid in bob_list
                assert alice_pid not in bob_list

                # Direct access to Alice's project is forbidden
                assert bob.get(f"/api/projects/{alice_pid}").status_code == 403
                assert (
                    bob.get(f"/api/projects/{alice_pid}/documents").status_code == 403
                )

            # Alice (the first user → admin) sees both
            alice_list = {p["id"] for p in alice.get("/api/projects").json()}
            assert {alice_pid, bob_pid} <= alice_list

    def test_membership_grants_access(self):
        with _client() as admin:
            _register(admin, "admin@example.com")
        with _client() as owner:
            _register(owner, "owner@example.com", "Owner")
            pid = _make_project(owner)
            with _client() as guest:
                _register(guest, "guest@example.com", "Guest")
                assert guest.get(f"/api/projects/{pid}").status_code == 403

                add = owner.post(
                    f"/api/projects/{pid}/members", json={"email": "guest@example.com"}
                )
                assert add.status_code == 201, add.text
                assert guest.get(f"/api/projects/{pid}").status_code == 200

                guest_id = guest.get("/api/auth/me").json()["id"]
                owner.delete(f"/api/projects/{pid}/members/{guest_id}")
                assert guest.get(f"/api/projects/{pid}").status_code == 403

    def test_only_owner_or_admin_manages_members(self):
        with _client() as admin:
            _register(admin, "admin@example.com")
        with _client() as owner:
            _register(owner, "owner@example.com")
            pid = _make_project(owner)
            owner.post(f"/api/projects/{pid}/members", json={"email": "admin@example.com"})
        with _client() as member:
            _register(member, "third@example.com")
            with _client() as owner2:
                owner2.post(
                    "/api/auth/login",
                    json={"email": "owner@example.com", "password": "hunter2hunter2"},
                )
                owner2.post(f"/api/projects/{pid}/members", json={"email": "third@example.com"})
            # A plain member may view but not add others
            r = member.post(f"/api/projects/{pid}/members", json={"email": "admin@example.com"})
            assert r.status_code == 403


class TestAdmin:
    def test_admin_user_list_and_promotion(self):
        with _client() as admin:
            _register(admin, "admin@example.com")
            with _client() as user:
                _register(user, "user@example.com")
                assert user.get("/api/auth/users").status_code == 403

            users = admin.get("/api/auth/users")
            assert users.status_code == 200
            by_email = {u["email"]: u for u in users.json()}
            assert by_email["admin@example.com"]["role"] == "admin"

            target_id = by_email["user@example.com"]["id"]
            promoted = admin.patch(f"/api/auth/users/{target_id}/role", json={"role": "admin"})
            assert promoted.json()["role"] == "admin"

    def test_last_admin_cannot_be_demoted(self):
        with _client() as admin:
            _register(admin, "admin@example.com")
            my_id = admin.get("/api/auth/me").json()["id"]
            r = admin.patch(f"/api/auth/users/{my_id}/role", json={"role": "user"})
            assert r.status_code == 409
