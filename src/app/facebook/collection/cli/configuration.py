from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus


def feed_url(args: argparse.Namespace) -> str:
    topic = args.topic.strip()
    if not topic:
        return "https://m.facebook.com/"
    return f"https://m.facebook.com/search/top/?q={quote_plus(topic)}"


def run_directory(args: argparse.Namespace) -> Path:
    if args.run_dir.strip():
        return Path(args.run_dir)
    return Path(args.out) / datetime.now().strftime("run_%Y%m%d_%H%M%S")
