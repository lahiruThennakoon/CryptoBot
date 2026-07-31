"""File-based model registry with versioning and status lifecycle.

Layout:
    <registry_dir>/manifest.json          — all versions + metrics + status
    <registry_dir>/artifacts/<id>.pkl     — pickled model objects

Lifecycle: candidate → deployed → retired (or rejected). At most one
deployed model per (name, features_version). Promotion happens exclusively
through ml/promotion.py gates; the registry only records decisions.
"""

from __future__ import annotations

import json
import pickle
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ModelRecord:
    id: str
    name: str
    version: int
    algorithm: str
    seed: int
    features_version: str
    horizon: int
    trained_at: str
    train_rows: int
    metrics: dict[str, Any] = field(default_factory=dict)      # val + test EvalResults
    status: str = "candidate"        # candidate | deployed | retired | rejected
    promoted_at: str | None = None
    decision_note: str = ""
    reference_distribution: dict[str, list[float]] = field(default_factory=dict)


class ModelRegistry:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._artifacts = self._root / "artifacts"
        self._manifest = self._root / "manifest.json"
        self._artifacts.mkdir(parents=True, exist_ok=True)

    # ── manifest io ──────────────────────────────────────────────────
    def _load(self) -> list[ModelRecord]:
        if not self._manifest.exists():
            return []
        data = json.loads(self._manifest.read_text())
        return [ModelRecord(**r) for r in data]

    def _save(self, records: list[ModelRecord]) -> None:
        self._manifest.write_text(json.dumps([asdict(r) for r in records], indent=2))

    # ── operations ───────────────────────────────────────────────────
    def register(
        self,
        model: object,
        name: str,
        algorithm: str,
        seed: int,
        features_version: str,
        horizon: int,
        train_rows: int,
        metrics: dict[str, Any],
        reference_distribution: dict[str, list[float]] | None = None,
    ) -> ModelRecord:
        records = self._load()
        version = 1 + max(
            (r.version for r in records if r.name == name), default=0
        )
        record = ModelRecord(
            id=uuid.uuid4().hex, name=name, version=version, algorithm=algorithm,
            seed=seed, features_version=features_version, horizon=horizon,
            trained_at=datetime.now(UTC).isoformat(), train_rows=train_rows,
            metrics=metrics,
            reference_distribution=reference_distribution or {},
        )
        with open(self._artifacts / f"{record.id}.pkl", "wb") as fh:
            pickle.dump(model, fh)
        records.append(record)
        self._save(records)
        return record

    def load_model(self, record_id: str) -> object:
        with open(self._artifacts / f"{record_id}.pkl", "rb") as fh:
            return pickle.load(fh)  # noqa: S301 — local artifacts written by us

    def deployed(self, name: str, features_version: str | None = None) -> ModelRecord | None:
        for r in self._load():
            if r.name == name and r.status == "deployed" and (
                features_version is None or r.features_version == features_version
            ):
                return r
        return None

    def all_records(self, name: str | None = None) -> list[ModelRecord]:
        return [r for r in self._load() if name is None or r.name == name]

    def set_status(self, record_id: str, status: str, note: str = "") -> ModelRecord:
        records = self._load()
        target = next((r for r in records if r.id == record_id), None)
        if target is None:
            raise KeyError(record_id)
        if status == "deployed":
            # exactly one deployed model per name — retire the incumbent
            for r in records:
                if r.name == target.name and r.status == "deployed" and r.id != record_id:
                    r.status = "retired"
                    r.decision_note = f"superseded by {record_id}"
            target.promoted_at = datetime.now(UTC).isoformat()
        target.status = status
        target.decision_note = note or target.decision_note
        self._save(records)
        return target
