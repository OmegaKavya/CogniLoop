import hashlib
import secrets

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256', 
        password.encode('utf-8'), 
        salt.encode('utf-8'), 
        100000
    ).hex()
    return f"{salt}:{pw_hash}"

def verify_password(password: str, stored_value: str) -> bool:
    if not stored_value or ":" not in stored_value:
        return password == stored_value
    try:
        salt, pw_hash = stored_value.split(":")
        new_hash = hashlib.pbkdf2_hmac(
            'sha256', 
            password.encode('utf-8'), 
            salt.encode('utf-8'), 
            100000
        ).hex()
        return secrets.compare_digest(pw_hash, new_hash)
    except Exception:
        return False

class AuthService:
    """Service layer for authentication and secure credential management."""
    hash_password = staticmethod(hash_password)
    verify_password = staticmethod(verify_password)

auth_service = AuthService()
