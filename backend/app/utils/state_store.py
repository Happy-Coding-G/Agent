from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


PROJECT_BACKEND_DIR = Path(__file__).resolve().parents[2]
STATE_ROOT = PROJECT_BACKEND_DIR / "state"


def _scope_dir(scope: str) -> Path:
    path = STATE_ROOT / scope
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(scope: str, key: str, default: Any) -> Any:
    path = _scope_dir(scope) / f"{key}.json"
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_state(scope: str, key: str, data: Any) -> None:
    target = _scope_dir(scope) / f"{key}.json"
    fd, tmp_name = tempfile.mkstemp(prefix=target.stem, suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        tmp_path.replace(target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
