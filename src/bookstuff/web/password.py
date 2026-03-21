"""Password security with Argon2id hashing, random salting, and HMAC peppering.

Argon2id is memory-hard (resists GPU/ASIC attacks) and won the Password
Hashing Competition.  The pepper adds a server-side secret so a leaked
hash database alone is not enough to crack passwords.

Usage — generate a hash and pepper for deployment:

    python -m bookstuff.web.password

Then set the printed environment variables:

    export UPLOAD_PASSWORD_HASH="..."
    export UPLOAD_PEPPER="..."
"""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

# Argon2id parameters (OWASP recommended minimums: 19 MiB, 2 iterations)
_hasher = PasswordHasher(
    time_cost=3,         # iterations
    memory_cost=65536,   # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def _apply_pepper(password: str, pepper: str) -> str:
    """HMAC the password with the pepper so the hash is useless without it."""
    return hmac.new(
        pepper.encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_password(password: str, pepper: str = "") -> str:
    """Hash a password with Argon2id + random salt + HMAC pepper.

    Returns the standard Argon2 PHC string:
        $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
    """
    peppered = _apply_pepper(password, pepper)
    return _hasher.hash(peppered)


def verify_password(password: str, password_hash: str, pepper: str = "") -> bool:
    """Verify a password against a stored Argon2id hash.

    Returns False on any failure (wrong password, corrupt hash, etc.).
    """
    if not password_hash:
        return False
    peppered = _apply_pepper(password, pepper)
    try:
        return _hasher.verify(password_hash, peppered)
    except (VerifyMismatchError, VerificationError, HashingError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check if the hash parameters are outdated and need rehashing."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return True


def generate_pepper() -> str:
    """Generate a cryptographically secure 256-bit pepper."""
    return secrets.token_hex(32)


if __name__ == "__main__":
    import argparse
    import getpass
    import sys

    parser = argparse.ArgumentParser(description="Generate password hash for deployment")
    parser.add_argument("--password", help="Password (omit for interactive prompt)")
    parser.add_argument("--pepper", help="Pepper (omit to generate one)")
    parser.add_argument("--kubectl", action="store_true",
                        help="Print kubectl command to create the k8s secret")
    args = parser.parse_args()

    pepper = args.pepper or generate_pepper()
    if not args.pepper:
        print(f"Generated pepper: {pepper}", file=sys.stderr)

    if args.password:
        pw = args.password
    else:
        pw = getpass.getpass("Enter password: ")
        confirm = getpass.getpass("Confirm password: ")
        if pw != confirm:
            print("Passwords don't match!", file=sys.stderr)
            sys.exit(1)

    h = hash_password(pw, pepper)

    if args.kubectl:
        print(f"kubectl create secret generic books-web-auth "
              f"--from-literal=password-hash='{h}' "
              f"--from-literal=pepper='{pepper}'")
    else:
        print(f"UPLOAD_PASSWORD_HASH={h}")
        print(f"UPLOAD_PEPPER={pepper}")
