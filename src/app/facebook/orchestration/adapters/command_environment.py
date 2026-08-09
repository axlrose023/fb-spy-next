from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PythonProcessEnvironment:
    executable: str


@dataclass(frozen=True, slots=True)
class OctoProcessEnvironment(PythonProcessEnvironment):
    collector_module: str
    host: str
    port: int
    headless: bool
