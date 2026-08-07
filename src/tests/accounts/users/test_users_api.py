from __future__ import annotations

from uuid import uuid4

import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.users import UserRole
from app.accounts.users.adapters.persistence import UserRecord

pytestmark = pytest.mark.integration


def password_hash(password: str) -> str:
    return bytes(bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4))).decode()


async def persist_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: UserRole = UserRole.USER,
    active: bool = True,
) -> UserRecord:
    user = UserRecord(
        username=username,
        password=password_hash(password),
        role=role.value,
        is_active=active,
    )
    session.add(user)
    await session.commit()
    return user


async def login_headers(
    client: AsyncClient,
    *,
    username: str,
    password: str,
) -> dict[str, str]:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_admin_can_create_list_get_and_update_users(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    suffix = uuid4().hex
    admin_name = f"admin-{suffix}"
    admin_password = "admin-password"
    await persist_user(
        session,
        username=admin_name,
        password=admin_password,
        role=UserRole.ADMIN,
    )
    headers = await login_headers(
        client,
        username=admin_name,
        password=admin_password,
    )
    username = f"member-{suffix}"

    created = await client.post(
        "/users",
        json={"username": username, "password": "member-password"},
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body == {
        "id": body["id"],
        "username": username,
        "role": "user",
        "is_active": True,
    }

    duplicate = await client.post(
        "/users",
        json={"username": username, "password": "another-password"},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Username already taken"}

    listing = await client.get(
        "/users",
        params={"username__search": suffix, "page": 1, "page_size": 10},
        headers=headers,
    )
    assert listing.status_code == 200
    page = listing.json()
    assert page["total"] == 2
    assert {item["username"] for item in page["items"]} == {admin_name, username}
    assert page["page"] == 1
    assert page["page_size"] == 10
    assert page["total_pages"] == 1
    assert page["has_next"] is False
    assert page["has_prev"] is False

    fetched = await client.get(f"/users/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == body

    updated = await client.patch(
        f"/users/{body['id']}",
        json={"role": "admin", "is_active": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "admin"
    assert updated.json()["is_active"] is False


async def test_regular_user_permissions_and_self_update(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    suffix = uuid4().hex
    actor_name = f"actor-{suffix}"
    actor_password = "actor-password"
    actor = await persist_user(
        session,
        username=actor_name,
        password=actor_password,
    )
    target = await persist_user(
        session,
        username=f"target-{suffix}",
        password="target-password",
    )
    headers = await login_headers(
        client,
        username=actor_name,
        password=actor_password,
    )

    create = await client.post(
        "/users",
        json={"username": f"forbidden-{suffix}", "password": "password"},
        headers=headers,
    )
    assert create.status_code == 403
    assert create.json() == {"detail": "Admin privileges required"}

    edit_other = await client.patch(
        f"/users/{target.id}",
        json={"username": f"changed-target-{suffix}"},
        headers=headers,
    )
    assert edit_other.status_code == 403
    assert edit_other.json() == {"detail": "You can only edit your own account"}

    privileged = await client.patch(
        f"/users/{actor.id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert privileged.status_code == 403
    assert privileged.json() == {
        "detail": "Only an admin can change role or activation status"
    }

    new_name = f"renamed-{suffix}"
    self_update = await client.patch(
        f"/users/{actor.id}",
        json={"username": new_name, "password": "new-password"},
        headers=headers,
    )
    assert self_update.status_code == 200
    assert self_update.json()["username"] == new_name

    await login_headers(client, username=new_name, password="new-password")


async def test_me_and_missing_user_contracts(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    username = f"me-{uuid4().hex}"
    password = "me-password"
    user = await persist_user(session, username=username, password=password)
    headers = await login_headers(client, username=username, password=password)

    assert (await client.get("/users/me")).status_code == 401

    me = await client.get("/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json() == {
        "id": str(user.id),
        "username": username,
        "role": "user",
        "is_active": True,
    }
    assert "password" not in me.json()

    missing = await client.get(f"/users/{uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "User not found"}
