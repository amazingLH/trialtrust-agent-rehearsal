"""Offline integrity checks for the frozen development and deployment records."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    checked = []
    for name in ("plan-probes-v1.json", "retrieval-v1.json"):
        path = ROOT / "evals" / name
        expected = path.with_suffix(".sha256").read_text(encoding="utf-8").strip()
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen manifest checksum mismatch: {name}")
        checked.append(name)
    folder = ROOT / "evals" / "results"
    deployment = json.loads((folder / "deployment-v0.4.json").read_text(encoding="utf-8"))
    for name, expected in deployment["evidence"].items():
        if Path(name).name != name or hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Deployment evidence checksum mismatch: {name}")
        checked.append(name)
    print(json.dumps({"offline_evidence_integrity": "passed", "checked": checked}))


if __name__ == "__main__":
    main()
