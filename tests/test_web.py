import secrets

import pytest
from fastapi.testclient import TestClient

from database.models import PostQueue, User
from web.auth import hash_password

# Generated per run, so no password literal sits in the repo.
TEST_PASSWORD = secrets.token_urlsafe(12)


@pytest.fixture
def web(db, monkeypatch):
    import web.app as app_module

    monkeypatch.setattr(app_module, "_db", db)
    monkeypatch.setattr(app_module, "_login_attempts", {})
    return app_module


@pytest.fixture
def client(web):
    return TestClient(web.app)


def add_user(db, email, role, password=TEST_PASSWORD):
    with db.Session() as session:
        user = User(
            email=email,
            role=role,
            password_hash=hash_password(password),
            is_active=True,
        )
        session.add(user)
        session.commit()
        return user.id


def login(client, email, password=TEST_PASSWORD):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def test_bad_page_number_does_not_500(client):
    assert client.get("/?page=abc").status_code == 200
    assert client.get("/?page=-3").status_code == 200


def test_security_headers_are_set(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"


def test_spoofed_forwarded_for_does_not_reset_the_login_limit(db, client):
    add_user(db, "admin@example.com", "superadmin")
    for i in range(8):
        headers = {"X-Forwarded-For": f"10.0.0.{i}"}
        client.post(
            "/login",
            data={"email": "admin@example.com", "password": "wrong-" + TEST_PASSWORD},
            headers=headers,
        )
    response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "wrong-" + TEST_PASSWORD},
        headers={"X-Forwarded-For": "10.9.9.9"},
    )
    assert response.status_code == 429


def test_login_works(db, client):
    add_user(db, "admin@example.com", "superadmin")
    assert login(client, "admin@example.com").status_code == 303
    assert login(client, "nobody@example.com").status_code == 200  # back to the form


def test_admin_cannot_deactivate_superadmin(db, client):
    owner = add_user(db, "owner@example.com", "superadmin")
    add_user(db, "admin@example.com", "admin")
    login(client, "admin@example.com")
    client.post(f"/admin/users/{owner}/toggle", follow_redirects=False)
    with db.Session() as session:
        assert session.get(User, owner).is_active


def test_error_flash_keeps_its_category(db, client):
    add_user(db, "admin@example.com", "admin")
    login(client, "admin@example.com")
    response = client.post(
        "/admin/users/invite",
        data={"email": "admin@example.com"},
        follow_redirects=False,
    )
    assert response.cookies.get("flash_cat") == "error"


def test_post_now_hands_item_to_the_bot(db, client):
    add_user(db, "admin@example.com", "admin")
    with db.Session() as session:
        item = PostQueue(
            content_type="news",
            priority="drip",
            status="failed",
            content_text="x",
            retry_count=3,
        )
        session.add(item)
        session.commit()
        item_id = item.id
    login(client, "admin@example.com")
    client.post(f"/admin/queue/{item_id}/post-now", follow_redirects=False)
    with db.Session() as session:
        item = session.get(PostQueue, item_id)
        assert (item.status, item.priority, item.retry_count) == (
            "pending",
            "immediate",
            0,
        )
