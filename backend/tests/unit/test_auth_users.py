from tests.conftest import login, make_user


def test_login_me_logout(client):
    make_user()
    assert client.get("/api/auth/me").status_code == 401
    login(client)
    me = client.get("/api/auth/me").json()
    assert me["email"] == "admin@example.com" and me["role"] == "admin"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_bad_password_is_rejected_and_audited(client, db):
    from app.models import AuditLog

    make_user()
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 401
    assert db.query(AuditLog).filter_by(action="auth.login_failed").count() == 1


def test_analyst_cannot_use_admin_routes(analyst_client):
    assert analyst_client.get("/api/users").status_code == 403
    assert analyst_client.post("/api/api-keys", json={"name": "x"}).status_code == 403
    assert analyst_client.put("/api/settings", json={}).status_code == 403
    assert analyst_client.get("/api/calls").status_code == 200


def test_user_crud_and_session_invalidation(admin_client, client):
    r = admin_client.post("/api/users", json={"email": "Bob@Example.com", "name": "Bob", "role": "analyst",
                                              "password": "short"})
    assert r.status_code == 400  # weak password
    r = admin_client.post("/api/users", json={"email": "Bob@Example.com", "name": "Bob", "role": "analyst",
                                              "password": "long-enough-pw"})
    assert r.status_code == 201
    bob = r.json()
    assert bob["email"] == "bob@example.com"
    assert admin_client.post("/api/users", json={"email": "bob@example.com", "name": "B", "password": "long-enough-pw"}
                             ).status_code == 409

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as bob_client:
        login(bob_client, "bob@example.com", "long-enough-pw")
        assert bob_client.get("/api/auth/me").status_code == 200
        # Deactivation ends the existing session immediately.
        assert admin_client.patch(f"/api/users/{bob['id']}", json={"is_active": False}).status_code == 200
        assert bob_client.get("/api/auth/me").status_code == 401


def test_admin_cannot_demote_self(admin_client):
    me = admin_client.get("/api/auth/me").json()
    assert admin_client.patch(f"/api/users/{me['id']}", json={"role": "analyst"}).status_code == 400


def test_password_change(admin_client):
    r = admin_client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "new-password-1"})
    assert r.status_code == 400
    r = admin_client.post("/api/auth/password",
                          json={"current_password": "correct-horse-1", "new_password": "new-password-1"})
    assert r.status_code == 204
    assert admin_client.get("/api/auth/me").status_code == 200  # cookie refreshed


def test_api_keys(admin_client, client):
    r = admin_client.post("/api/api-keys", json={"name": "recorder"})
    assert r.status_code == 201
    key = r.json()
    assert key["key"].startswith("sqa_")
    listed = admin_client.get("/api/api-keys").json()
    assert "key" not in listed[0] and listed[0]["prefix"] == key["prefix"]
    assert admin_client.get("/api/v1/calls/nope", headers={"X-API-Key": key["key"]}).status_code == 404
    assert admin_client.get("/api/v1/calls/nope", headers={"X-API-Key": key["key"] + "x"}).status_code == 401
    admin_client.delete(f"/api/api-keys/{key['id']}")
    assert admin_client.get("/api/v1/calls/nope", headers={"X-API-Key": key["key"]}).status_code == 401
