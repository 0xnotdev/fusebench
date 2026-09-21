"""Development-run input integrity manifests (not the CP-13 freeze manifest)."""

from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fusebench.dataset.validation import canonical_json


class DevRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dev_dataset: str
    dev_dataset_sha256: str
    critical_files: dict[str, str]
    test_dataset: str
    test_dataset_absent: bool
    run_seed: int
    information_threshold: float
    terra_model: str
    jev_model: str
    tool_protocol: str


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build_dev_manifest(
    *,
    dev_dataset: Path,
    critical_paths: tuple[Path, ...],
    test_dataset: Path,
    run_seed: int,
    information_threshold: float,
    terra_model: str,
    jev_model: str,
    tool_protocol: str,
) -> DevRunManifest:
    if test_dataset.exists():
        raise ValueError("test dataset must remain absent before CP-13")
    if not dev_dataset.is_file():
        raise ValueError("development dataset is missing")
    if any(not path.is_file() for path in critical_paths):
        raise ValueError("benchmark-critical input is missing")
    return DevRunManifest(
        dev_dataset=str(dev_dataset.resolve()),
        dev_dataset_sha256=file_sha256(dev_dataset),
        critical_files={str(path.resolve()): file_sha256(path) for path in critical_paths},
        test_dataset=str(test_dataset.resolve()),
        test_dataset_absent=True,
        run_seed=run_seed,
        information_threshold=information_threshold,
        terra_model=terra_model,
        jev_model=jev_model,
        tool_protocol=tool_protocol,
    )


def verify_dev_manifest(manifest: DevRunManifest) -> tuple[str, ...]:
    drift: list[str] = []
    dev_path = Path(manifest.dev_dataset)
    if not dev_path.is_file() or file_sha256(dev_path) != manifest.dev_dataset_sha256:
        drift.append(manifest.dev_dataset)
    for name, expected in manifest.critical_files.items():
        path = Path(name)
        if not path.is_file() or file_sha256(path) != expected:
            drift.append(name)
    if Path(manifest.test_dataset).exists():
        drift.append(manifest.test_dataset)
    return tuple(drift)


def write_dev_manifest(manifest: DevRunManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
