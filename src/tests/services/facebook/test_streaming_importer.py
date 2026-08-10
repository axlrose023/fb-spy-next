import json
from pathlib import Path

from sqlalchemy import select

from app.ad_library.ads.adapters.persistence import FacebookAd
from app.facebook.runs.adapters import FacebookAdsImporter
from app.facebook.runs.adapters.persistence import FacebookRun
from app.settings import Config, FacebookConfig, GeminiConfig, MediaStorageConfig


async def test_streaming_import_queues_relevance_and_inserts_only_accepted(
    monkeypatch,
    tmp_path,
    uow,
) -> None:
    run_dir = tmp_path / "run_20260626_000000"
    screens_dir = run_dir / "screens"
    videos_dir = run_dir / "videos"
    screens_dir.mkdir(parents=True)
    videos_dir.mkdir(parents=True)
    (screens_dir / "0001_relevant.png").write_bytes(b"fake")
    (screens_dir / "0002_noise.png").write_bytes(b"fake")
    (videos_dir / "0001_relevant.mp4").write_bytes(b"fake-video")

    raw_ads = [
        {
            "advertiser": "Relevant Signal",
            "ad_type": "link",
            "has_video": True,
            "displayed_domain": "signals.example",
            "headline": "90% win rate trading signal",
            "ad_text": "Join our signal group",
            "cta": "Join Now",
            "creative_img": "https://cdn.example/relevant.jpg",
            "video": "videos/0001_relevant.mp4",
            "screenshot": "screens/0001_relevant.png",
            "screenshot_ok": True,
            "landing_full": "https://signals.example/?utm_source=facebook",
            "landing_clean": "https://signals.example/",
            "utm": {"utm_source": "facebook"},
            "captured_at": "2026-06-26T10:00:00+00:00",
        },
        {
            "advertiser": "Regular SaaS",
            "ad_type": "link",
            "has_video": False,
            "displayed_domain": "saas.example",
            "headline": "Team inbox for support",
            "ad_text": "Answer customers faster",
            "cta": "Learn More",
            "creative_img": "https://cdn.example/noise.jpg",
            "screenshot": "screens/0002_noise.png",
            "screenshot_ok": True,
            "captured_at": "2026-06-26T10:01:00+00:00",
        },
    ]
    (run_dir / "ads.partial.json").write_text(
        json.dumps(raw_ads, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeRelevanceTask:
        async def kiq(self, raw, run_dir, index, result_path):
            relevant = raw["advertiser"] == "Relevant Signal"
            payload = {
                "index": index,
                "relevant": relevant,
                "summary": {
                    "result": "relevant" if relevant else "not_relevant",
                    "reason": "fake result",
                },
                "source": "fake-taskiq",
                "raw_response": None,
            }
            path = Path(result_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

    from app.tasks import facebook_relevance

    monkeypatch.setattr(
        facebook_relevance,
        "analyze_facebook_ad_relevance",
        FakeRelevanceTask(),
    )

    config = Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(
            data_dir=tmp_path,
            runner_out_dir=tmp_path,
            relevance_filter_enabled=True,
            relevance_filter_taskiq_enabled=True,
        ),
        gemini=GeminiConfig(api_key="test-key"),
    )

    class RecordingS3MediaStorage:
        backend = "s3"

        def __init__(self) -> None:
            self.uploaded_advertisers: list[str] = []

        async def upload_ads(self, ads, *, relevance_verified: bool) -> int:
            assert relevance_verified is True
            self.uploaded_advertisers.extend(ad.advertiser for ad in ads)
            return len(ads)

    media_storage = RecordingS3MediaStorage()
    importer = FacebookAdsImporter(config, media_storage=media_storage)
    run = FacebookRun(status="running", title="streaming test")
    await uow.facebook_runs.create(run)

    stream = importer.create_streaming_session(run.id, run_dir)
    await stream.poll(uow, run)
    await stream.finalize(uow, run)
    await uow.commit()

    rows = (
        (
            await uow.session.execute(
                select(FacebookAd).where(FacebookAd.run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].advertiser == "Relevant Signal"
    assert rows[0].video_path == "run_20260626_000000/videos/0001_relevant.mp4"
    assert run.total_ads == 1
    assert run.video_ads == 1
    assert stream.pending_count == 0
    assert media_storage.uploaded_advertisers == ["Relevant Signal"]

    accepted = json.loads((run_dir / "ads.json").read_text(encoding="utf-8"))
    rejected = json.loads((run_dir / "ads.rejected.json").read_text(encoding="utf-8"))
    unfiltered = json.loads(
        (run_dir / "ads.unfiltered.json").read_text(encoding="utf-8")
    )
    assert [ad["advertiser"] for ad in accepted] == ["Relevant Signal"]
    assert [ad["advertiser"] for ad in rejected] == ["Regular SaaS"]
    assert len(unfiltered) == 2
