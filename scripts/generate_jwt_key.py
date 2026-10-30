"""Generate an RSA private key for auth_service token signing (RS256).

    python scripts/generate_jwt_key.py                    # writes secrets/jwt_private.pem
    python scripts/generate_jwt_key.py --out other/path.pem

Then set JWT_PRIVATE_KEY_PATH in .env. The secrets/ folder and *.pem files are git-ignored.
Only auth_service needs the private key; everyone else fetches the public key from JWKS.
"""

import argparse
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("secrets/jwt_private.pem"))
    parser.add_argument("--bits", type=int, default=3072, choices=[2048, 3072, 4096])
    args = parser.parse_args()

    if args.out.exists():
        print(f"{args.out} already exists; not overwriting it.", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=args.bits)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    # Create the file readable by the owner only (where the OS supports POSIX modes).
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    print(f"Wrote {args.out}. Set JWT_PRIVATE_KEY_PATH={args.out.as_posix()} in .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
