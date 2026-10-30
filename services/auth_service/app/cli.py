"""Operator commands for auth_service. Run from the repository root: python scripts/auth_cli.py --help

Uses the service's own runtime database credentials (AUTH_DB_*). It never prints passwords
or hashes; a new client secret is printed once and must be stored in the caller's secrets.
"""

import argparse
import os
import secrets
import sys

from sqlalchemy import select

from app.accounts import normalize_email
from app.config import get_settings
from app.db import Database
from app.models import AuthUser, Role, ServiceClient
from app.security.passwords import hash_password, verify_password

# Scopes from rest_api_notes.md Part 4.
KNOWN_SCOPES = {
    "products:read", "inventory:reserve", "addresses:read", "orders:read", "orders:payment", "payments:reconcile",
}


def promote_admin(db: Database, email: str) -> int:
    with db.session_scope() as session:
        user = session.scalars(select(AuthUser).where(AuthUser.email == normalize_email(email))).one_or_none()
        if user is None:
            print("No account with that email. Register it first.", file=sys.stderr)
            return 1
        user.role = Role.ADMIN
        print(f"User {user.id} is now an admin (applies to tokens issued from now on).")
    return 0


def create_service_client(db: Database, client_id: str, scopes: list[str], rotate: bool) -> int:
    if not client_id.startswith("svc:"):
        print("client_id must look like svc:<service>, e.g. svc:order", file=sys.stderr)
        return 1
    unknown = set(scopes) - KNOWN_SCOPES
    if unknown:
        print(f"Unknown scopes: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 1
    secret = secrets.token_urlsafe(32)
    with db.session_scope() as session:
        client = session.get(ServiceClient, client_id)
        if client is not None and not rotate:
            print("Client exists. Use --rotate to issue a new secret.", file=sys.stderr)
            return 1
        if client is None:
            client = ServiceClient(client_id=client_id, secret_hash="", allowed_scopes=[])
            session.add(client)
        client.secret_hash = hash_password(secret)
        client.allowed_scopes = sorted(set(scopes))
        client.active = True
    print(f"client_id={client_id}\nclient_secret={secret}\nscopes={' '.join(sorted(set(scopes)))}")
    print("Store the secret in that service's environment now; it is not shown again.", file=sys.stderr)
    return 0


def ensure_service_client(db: Database, client_id: str, scopes: list[str], secret_env: str) -> int:
    """Create or update a client from a secret already held in the environment (Compose bootstrap).

    Idempotent: re-running with the same values changes nothing that matters. The secret is
    read from the named environment variable and never printed.
    """
    secret = os.environ.get(secret_env, "")
    if len(secret) < 16 or secret == "change-me":
        print(f"{secret_env} must hold a real secret (16+ characters).", file=sys.stderr)
        return 1
    if not client_id.startswith("svc:") or set(scopes) - KNOWN_SCOPES:
        print("Invalid client_id or scopes.", file=sys.stderr)
        return 1
    with db.session_scope() as session:
        client = session.get(ServiceClient, client_id)
        if client is None:
            client = ServiceClient(client_id=client_id, secret_hash="", allowed_scopes=[])
            session.add(client)
        if not client.secret_hash or not verify_password(client.secret_hash, secret):
            client.secret_hash = hash_password(secret)
        client.allowed_scopes = sorted(set(scopes))
        client.active = True
    print(f"service client {client_id} ready (scopes: {' '.join(sorted(set(scopes)))})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auth_cli", description="auth_service operator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    ensure = sub.add_parser("ensure-service-client", help="create/update a client from a secret in the environment")
    ensure.add_argument("client_id")
    ensure.add_argument("--scope", action="append", default=[], required=True, help="repeatable")
    ensure.add_argument("--secret-env", required=True, help="name of the environment variable holding the secret")
    admin = sub.add_parser("promote-admin", help="give an existing account the admin role")
    admin.add_argument("email")
    client = sub.add_parser("create-service-client", help="register an internal service (ADR-08)")
    client.add_argument("client_id", help="e.g. svc:order")
    client.add_argument("--scope", action="append", default=[], required=True, help="repeatable")
    client.add_argument("--rotate", action="store_true", help="replace the secret of an existing client")
    args = parser.parse_args(argv)

    db = Database.from_settings(get_settings())
    try:
        if args.command == "promote-admin":
            return promote_admin(db, args.email)
        if args.command == "ensure-service-client":
            return ensure_service_client(db, args.client_id, args.scope, args.secret_env)
        return create_service_client(db, args.client_id, args.scope, args.rotate)
    finally:
        db.dispose()


if __name__ == "__main__":
    sys.exit(main())
