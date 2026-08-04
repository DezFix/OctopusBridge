from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download

from .registry import repo_for


def model_root() -> Path:
    for var in ("HONYAKU_MODEL_DIR", "LANBRIDGE_MODEL_DIR"):
        env = os.environ.get(var)
        if env:
            return Path(env)
    base = os.environ.get("LOCALAPPDATA") or (Path.home() / ".cache")
    return Path(base) / "honyaku" / "models"


def model_dir_for(tier: str, pair: str, base: Path | None = None) -> Path:
    repo = repo_for(tier, pair)
    return (base or model_root()) / tier / repo.replace("/", "--")


def is_downloaded(tier: str, pair: str, base: Path | None = None) -> bool:
    return (model_dir_for(tier, pair, base) / "model.bin").exists()


def ensure_model(tier: str, pair: str, base: Path | None = None) -> Path:
    target = model_dir_for(tier, pair, base)
    if (target / "model.bin").exists():
        return target
    snapshot_download(repo_id=repo_for(tier, pair), local_dir=target)
    return target
