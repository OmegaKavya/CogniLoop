import hashlib
import secrets

# OWASP's current guidance for PBKDF2-HMAC-SHA256 is 600,000 iterations.
PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        PBKDF2_ITERATIONS
    ).hex()
    return f"{salt}:{pw_hash}"

def verify_password(password: str, stored_value: str) -> bool:
    """Check a password against a stored `salt:hash` value.

    Anything not in that form is rejected rather than compared directly. The
    previous implementation fell back to `password == stored_value`, which
    accepted plaintext-stored passwords and, because an empty stored value also
    took that branch, authenticated an account whose password field was empty
    when an empty password was supplied.
    """
    if not isinstance(stored_value, str) or not isinstance(password, str):
        return False
    if stored_value.count(":") != 1:
        return False

    salt, pw_hash = stored_value.split(":")
    if not salt or not pw_hash:
        return False

    new_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        PBKDF2_ITERATIONS
    ).hex()
    return secrets.compare_digest(pw_hash, new_hash)

class AuthService:
    """Service layer for authentication and secure credential management."""
    hash_password = staticmethod(hash_password)
    verify_password = staticmethod(verify_password)

auth_service = AuthService()
