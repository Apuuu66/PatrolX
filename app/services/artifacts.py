"""中间产物仓库：显式传递 + rule_version 版本校验。"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.inspectors.base import Inspector


@dataclass(slots=True)
class Artifact:
    key: str
    rule_code: str
    rule_version: str
    path: str


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root  # output/<task_id>/<system_id>/artifacts/

    def _manifest_path(self) -> Path:
        return self.root / ".artifacts.json"

    def save(self, key: str, inspector: Inspector, path: Path) -> None:
        manifest = self.load()
        manifest[key] = {
            "key": key,
            "rule_code": inspector.code,
            "rule_version": inspector.rule_version,
            "path": str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> dict[str, dict]:
        if not self._manifest_path().exists():
            return {}
        return json.loads(self._manifest_path().read_text(encoding="utf-8"))

    def get(self, key: str) -> Artifact | None:
        raw = self.load().get(key)
        if not raw:
            return None
        path = (self.root / raw["path"]) if not Path(raw["path"]).is_absolute() else Path(raw["path"])
        if not path.exists():
            return None
        return Artifact(key=raw["key"], rule_code=raw["rule_code"], rule_version=raw["rule_version"], path=str(path))

    def valid(self, key: str, inspector: Inspector) -> Artifact | None:
        """产物存在且生产者 rule_version 与当前注册一致才可复用。"""
        artifact = self.get(key)
        if artifact and artifact.rule_code == inspector.code and artifact.rule_version == inspector.rule_version:
            return artifact
        return None
