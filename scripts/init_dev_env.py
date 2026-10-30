"""Create a local-development .env from .env.example with random secrets.

    python scripts/init_dev_env.py              # writes .env (refuses to overwrite)
    python scripts/init_dev_env.py --out other.env

Every `change-me` placeholder gets its own random value. The file is git-ignored and is for
development only; real environments get their secrets from a secret store. Nothing secret
is printed.
"""

import argparse
import secrets
import sys
from pathlib import Path

PLACEHOLDER = "change-me"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--example", type=Path, default=Path(".env.example"))
    parser.add_argument("--out", type=Path, default=Path(".env"))
    args = parser.parse_args()

    if args.out.exists():
        print(f"{args.out} already exists; not overwriting it.", file=sys.stderr)
        return 1
    lines, generated = [], 0
    for line in args.example.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and value.strip() == PLACEHOLDER:
            line = f"{key}={secrets.token_urlsafe(24)}"
            generated += 1
        lines.append(line)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {args.out} with {generated} generated secrets (development only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
