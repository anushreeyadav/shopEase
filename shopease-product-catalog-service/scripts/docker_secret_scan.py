"""Check that no secret from .env is baked into the Docker image or the Docker evidence.

    python -m scripts.docker_secret_scan [image]      (default image: shopease-product-catalog-service:dev)

Reads the password and secret values from .env and searches, byte for byte:
  - the image's build history (docker history --no-trunc),
  - every file in every layer of the image (docker image save),
  - every file in DELIVERABELS/Docker_Evidence.
Only counts are printed, never a value. Exit code 1 if anything is found.
"""

import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "DELIVERABELS" / "Docker_Evidence"


def secret_values() -> dict[str, bytes]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            if any(word in name for word in ("PASSWORD", "SECRET", "KEY")) and len(value.strip()) >= 8:
                values[name.strip()] = value.strip().encode()
    return values


def count(data: bytes, secrets: dict[str, bytes]) -> int:
    return sum(data.count(value) for value in secrets.values())


def scan_image(image: str, secrets: dict[str, bytes]) -> tuple[int, int, list[str]]:
    hits, files, env_files = 0, 0, []
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "image.tar"
        subprocess.run(["docker", "image", "save", image, "-o", str(archive)], check=True)
        with tarfile.open(archive) as outer:
            for member in outer.getmembers():
                if not member.isfile():
                    continue
                data = outer.extractfile(member).read()
                try:
                    layer = tarfile.open(fileobj=io.BytesIO(data))
                except tarfile.TarError:  # image config and manifest files
                    hits += count(data, secrets)
                    continue
                with layer:
                    for item in layer.getmembers():
                        if item.isfile():
                            files += 1
                            if Path(item.name).name == ".env":
                                env_files.append(item.name)
                            hits += count(layer.extractfile(item).read(), secrets)
    return hits, files, env_files


def main() -> int:
    image = sys.argv[1] if len(sys.argv) > 1 else "shopease-product-catalog-service:dev"
    secrets = secret_values()
    print(f"Secret values taken from .env (names only): {sorted(secrets)}")
    history = subprocess.run(["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image],
                             check=True, capture_output=True).stdout
    history_hits = count(history, secrets)
    print(f"Image build history ({image}): {history_hits} matches")
    image_hits, files, env_files = scan_image(image, secrets)
    print(f"Image filesystem: {files} files in all layers, .env files {env_files}, {image_hits} matches")
    evidence_hits = sum(count(p.read_bytes(), secrets) for p in EVIDENCE.iterdir() if p.is_file())
    print(f"Docker evidence files: {evidence_hits} matches")
    total = history_hits + image_hits + evidence_hits + len(env_files)
    print("RESULT:", "no secret found" if total == 0 else "SECRET FOUND")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
