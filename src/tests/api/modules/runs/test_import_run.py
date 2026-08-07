import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.modules.auth.services import JwtService
from app.api.modules.users.models import User, UserRole
from app.settings import get_config


async def test_import_run_and_list_ads(
    client: AsyncClient,
    session: AsyncSession,
    tmp_path,
) -> None:
    run_dir = tmp_path / "run_20260622_000000"
    screens_dir = run_dir / "screens"
    videos_dir = run_dir / "videos"
    screens_dir.mkdir(parents=True)
    videos_dir.mkdir(parents=True)
    (screens_dir / "0001_example.png").write_bytes(b"fake")
    (videos_dir / "0001_example.mp4").write_bytes(b"fake-video")
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "octo_profile_uuid": "profile-fr",
                "profile_country": "France",
                "octo_ip": "203.0.113.10",
            },
        ),
        encoding="utf-8",
    )
    ads_json = run_dir / "ads.json"
    ads_json.write_text(
        json.dumps(
            [
                {
                    "advertiser": "Example Brand",
                    "ad_type": "link",
                    "has_video": True,
                    "displayed_domain": "example.com",
                    "headline": "Example headline",
                    "ad_text": "Example ad text",
                    "cta": "Learn More",
                    "creative_img": "https://cdn.example/image.jpg",
                    "video": "videos/0001_example.mp4",
                    "screenshot": "screens/0001_example.png",
                    "screenshot_ok": True,
                    "screenshot_issue": None,
                    "landing_full": "https://example.com/?utm_source=facebook",
                    "landing_clean": "https://example.com/",
                    "fb_ad_id": "123456789012",
                    "relevance": {
                        "result": "relevant",
                        "language": "English",
                    },
                    "utm": {"utm_source": "facebook"},
                    "captured_at": "2026-06-22T16:00:00+00:00",
                }
            ],
        ),
        encoding="utf-8",
    )

    user = User(
        username="media-test-admin",
        password="unused-test-password-hash",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    tokens = JwtService(get_config()).create_token_pair(user)
    auth_headers = {"Authorization": f"Bearer {tokens.access_token}"}

    assert (
        await client.post(
            "/runs/import",
            json={"ads_json_path": str(ads_json), "title": "fixture run"},
        )
    ).status_code == 401
    import_resp = await client.post(
        "/runs/import",
        json={"ads_json_path": str(ads_json), "title": "fixture run"},
        headers=auth_headers,
    )
    assert import_resp.status_code == 201
    imported = import_resp.json()
    assert imported["total_ads"] == 1
    assert imported["resolved_ads"] == 1
    assert imported["octo_profile_uuid"] == "profile-fr"
    assert imported["profile_country"] == "France"
    assert imported["octo_ip"] == "203.0.113.10"

    assert (await client.get("/ads", params={"q": "example"})).status_code == 401
    ads_resp = await client.get(
        "/ads",
        params={"q": "example"},
        headers=auth_headers,
    )
    assert ads_resp.status_code == 200
    ads = ads_resp.json()
    assert ads["total"] == 1
    assert ads["items"][0]["advertiser"] == "Example Brand"
    assert ads["items"][0]["country"] == "France"
    assert ads["items"][0]["language"] == "en"
    assert ads["items"][0]["format"] == "video"
    item = ads["items"][0]
    assert "video_path" not in item
    assert "screenshot_path" not in item
    assert "landing_screenshot_path" not in item
    assert "landing_archive_path" not in item
    assert item["screenshot_url"].startswith(f"/media/ads/{item['id']}/screenshot?")
    assert item["video_url"].startswith(f"/media/ads/{item['id']}/video?")

    screenshot_resp = await client.get(item["screenshot_url"])
    assert screenshot_resp.status_code == 200
    assert screenshot_resp.content == b"fake"
    assert screenshot_resp.headers["x-content-type-options"] == "nosniff"

    video_resp = await client.get(item["video_url"], headers={"Range": "bytes=0-3"})
    assert video_resp.status_code == 206
    assert video_resp.content == b"fake"
    assert video_resp.headers["content-range"] == "bytes 0-3/10"
    video_head = await client.head(item["video_url"])
    assert video_head.status_code == 200
    assert video_head.headers["content-length"] == "10"
    assert video_head.content == b""

    prefix, token = item["screenshot_url"].rsplit("=", 1)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert (await client.get(f"{prefix}={tampered}")).status_code == 403

    old_direct_url = "/media/imports/run_20260622_000000/screens/0001_example.png"
    assert (await client.get(old_direct_url)).status_code == 404

    assert (await client.get("/stats/ads")).status_code == 401
    stats_resp = await client.get("/stats/ads", headers=auth_headers)
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total_ads"] == 1
    assert stats["link_ads"] == 1
    assert stats["resolved_ads"] == 1
    assert stats["by_language"] == [{"value": "en", "count": 1}]

    language_resp = await client.get(
        "/ads",
        params={"language": "en"},
        headers=auth_headers,
    )
    assert language_resp.status_code == 200
    assert language_resp.json()["total"] == 1

    other_language_resp = await client.get(
        "/ads",
        params={"language": "tr"},
        headers=auth_headers,
    )
    assert other_language_resp.status_code == 200
    assert other_language_resp.json()["total"] == 0
