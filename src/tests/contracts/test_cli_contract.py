from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

PROJECT_ROOT = Path(__file__).parents[3]
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
APP_CLI = str(Path(sys.executable).with_name("cli"))
FACEBOOK_CLI = str(Path(sys.executable).with_name("facebook-spy"))

CLI_COMMANDS = {
    "app-cli": [APP_CLI, "--help"],
    "facebook-spy": [FACEBOOK_CLI, "--help"],
    "calibrator": [
        FACEBOOK_CLI,
        "calibrate",
        "--help",
    ],
    "db-importer": [
        FACEBOOK_CLI,
        "import-run",
        "--help",
    ],
    "enricher": [FACEBOOK_CLI, "enrich", "--help"],
    "classifier": [FACEBOOK_CLI, "classify", "--help"],
    "isolated-landing": [
        FACEBOOK_CLI,
        "resolve-landing",
        "--help",
    ],
    "orchestrator": [
        FACEBOOK_CLI,
        "orchestrate",
        "--help",
    ],
    "orchestrator-run": [
        FACEBOOK_CLI,
        "orchestrate",
        "run",
        "--help",
    ],
    "collector": [FACEBOOK_CLI, "collect", "--help"],
}

for command in (
    "migration",
    "migrations",
    "upgrade",
    "downgrade",
    "create_user",
    "filter-facebook-ads",
    "archive-facebook-landings",
    "sync-facebook-media",
    "backfill-facebook-ad-languages",
):
    CLI_COMMANDS[f"app-cli-{command}"] = [APP_CLI, command, "--help"]

for command in ("evaluate", "seed-baseline", "discover-active", "discover-octo"):
    CLI_COMMANDS[f"orchestrator-{command}"] = [
        FACEBOOK_CLI,
        "orchestrate",
        command,
        "--help",
    ]

EXPECTED_HELP_SHA256 = {
    "app-cli": "c3a65da463f79111eb38758a2f7b5ec2896a6b81777b40a32070b623d3863566",
    "app-cli-archive-facebook-landings": "5f79f748ad5fd2c1bf8935818e6dd28786131e67c6d3d2addbfb5a739f0d83ce",
    "app-cli-backfill-facebook-ad-languages": "cfc209dca24ef4b282804c0c4823565632d8505e79e57a2a70f86888edde8e11",
    "app-cli-create_user": "2a8758d4bb0b4f5dfea61c04c1cff1781e2041fde441c8568184f1b3147305cc",
    "app-cli-downgrade": "de102e3f894f66bb68628b444d8748cd9a5ca39daa3b111b9d7ad65d66077373",
    "app-cli-filter-facebook-ads": "b576a9dff0fcc862e897372409936eef643167288e5100228605a2ec7f7cb1ff",
    "app-cli-migration": "f050aaf3605d869580d1b8d27bfa3df81fd632803a467ab9a9c32e5e0cccde19",
    "app-cli-migrations": "df30a54b7d0bba38fa9e73ac6ca59b3ed868b71eb90641a97815103b5eb9d564",
    "app-cli-sync-facebook-media": "212253c239675682158b31c252992f3583e7650293588eedb9b7138e3dba06cb",
    "app-cli-upgrade": "f8c22eb67d684f89015f39e61d11772abab0977c76838a6b893123670260f9ab",
    "calibrator": "5a79c71e633fd0885188b1c6b0818212a6aec569c3c5025b3b313eacfaef5dd9",
    "classifier": "2d2ec608e0241dabddbfcde14297ee89aa9585ac511510cbb4d8b7b16b703bfd",
    "db-importer": "71395b0a5b0e680cac68828911b09957cf9e30564cbb61d5512740be9677f747",
    "enricher": "ffcb9d3376518e3ed9c12c08f6e17c0d1613647befffe1e88d1299c5983bdb41",
    "facebook-spy": "1f7bf50c4378e2a7beba8b3335b0050946841d8e2ce0eafdfaab6464cad8bf28",
    "isolated-landing": "72f0b8cefca79b2ca74b59a0065790489b72b168843c5a3d4737010ba1cb76a2",
    "orchestrator": "d90f06cae7590f837e0b3cb508a38ae1013acff32f1cf5b9e95096b64e8d51a1",
    "orchestrator-discover-active": "c0b4d411b51be1ef066d019a0127aa118a1f42a5ae5fa56d32074fd8690ffa2a",
    "orchestrator-discover-octo": "daeaf15af879b6a0783509eb2932eaa79818e057006ba99cfc4ebca238b986bf",
    "orchestrator-evaluate": "0be62bd831d451a764b80078fb6addb937642caab63a0966240ca186c0844940",
    "orchestrator-run": "4e09688cb47eef34a0aac2158ef3ed243f5f00aca2df5ec03f07d70159243606",
    "orchestrator-seed-baseline": "dc9e6331817f3fefe9be1393298396f05ff859bcacaf360bd8bb91bc5d0f5b87",
    "collector": "ab4b1c34f5553466e6c2dac8dd9cb5fa0dfb93bcba6063fcd48ac38fbbb46a68",
}


def _normalized_help(command: list[str]) -> str:
    env = {**os.environ, "COLUMNS": "120", "NO_COLOR": "1", "TERM": "dumb"}
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    plain = ANSI_ESCAPE.sub("", completed.stdout)
    return " ".join(plain.split())


@pytest.mark.parametrize("name", sorted(CLI_COMMANDS))
def test_cli_help_contract(name: str) -> None:
    payload = _normalized_help(CLI_COMMANDS[name]).encode()
    actual = hashlib.sha256(payload).hexdigest()
    assert actual == EXPECTED_HELP_SHA256[name], f"{name}: {actual}"
