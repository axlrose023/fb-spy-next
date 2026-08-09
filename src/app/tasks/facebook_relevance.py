from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.facebook.relevance import configured_relevance_service
from app.settings import get_config
from app.worker import broker

logger = logging.getLogger(__name__)


@broker.task(task_name="facebook_ad_relevance")
async def analyze_facebook_ad_relevance(
    raw: dict[str, Any],
    run_dir: str,
    index: int,
    result_path: str | None = None,
) -> dict[str, Any]:
    logger.info(
        "FB relevance task start idx=%s advertiser=%r domain=%r",
        index,
        raw.get("advertiser"),
        raw.get("displayed_domain"),
    )
    try:
        config = get_config()
        relevance_filter = configured_relevance_service(config)
        result = await relevance_filter.analyze_raw_ad(raw, Path(run_dir))
        payload = {
            "index": index,
            "relevant": result.relevant,
            "summary": result.summary,
            "source": result.source,
            "raw_response": result.raw_response,
        }
        logger.info(
            "FB relevance task finish idx=%s relevant=%s source=%s reason=%s",
            index,
            result.relevant,
            result.source,
            result.summary.get("reason"),
        )
    except Exception as exc:
        logger.exception(
            "FB relevance task failed idx=%s advertiser=%r domain=%r",
            index,
            raw.get("advertiser"),
            raw.get("displayed_domain"),
        )
        payload = {
            "index": index,
            "relevant": False,
            "summary": {
                "result": "not_relevant",
                "reason": f"Relevance task failed: {exc}",
            },
            "source": "taskiq_error",
            "raw_response": None,
        }

    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    return payload
