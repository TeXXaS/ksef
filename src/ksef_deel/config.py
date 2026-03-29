import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class KsefEnvironment(Enum):
    TEST = "test"
    DEMO = "demo"
    PROD = "prod"


@dataclass(frozen=True)
class KsefConfig:
    environment: KsefEnvironment
    nip: str
    token: str = ""


def load_config(path: Path) -> KsefConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    ksef = raw["ksef"]
    return KsefConfig(
        environment=KsefEnvironment(ksef["environment"]),
        nip=ksef["nip"],
        token=ksef.get("token", ""),
    )
