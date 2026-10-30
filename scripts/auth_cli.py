"""Run auth_service operator commands from the repository root (so .env is found).

    python scripts/auth_cli.py promote-admin admin@example.com
    python scripts/auth_cli.py create-service-client svc:order --scope addresses:read --scope products:read
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "auth_service"))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
