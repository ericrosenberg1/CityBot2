import base64
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request

SECRET_KEY_PATH = Path("data/secret.key")


def get_secret_key():
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.parent.mkdir(exist_ok=True)
    SECRET_KEY_PATH.write_text(key)
    return key


_fernet = None


def get_fernet() -> Fernet:
    """Symmetric cipher for encrypting secrets at rest (e.g. social platform
    credentials), derived from the same app secret key used for sessions."""
    global _fernet
    if _fernet is None:
        digest = hashlib.sha256(get_secret_key().encode("utf-8")).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a string for storage at rest."""
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a value previously encrypted with encrypt_secret.
    Returns "" if the token is invalid or was stored before encryption
    was added (legacy plaintext), rather than raising."""
    try:
        return get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


_serializer = None


def get_serializer():
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(get_secret_key())
    return _serializer


MAX_PASSWORD_BYTES = 72  # bcrypt's own hard limit


def hash_password(password: str) -> str:
    # Use the bcrypt package directly rather than passlib.hash.bcrypt: passlib
    # 1.7.4 (unmaintained since 2020) misdetects modern bcrypt (>=4.1, which
    # dropped the __about__.__version__ attribute passlib's backend probe
    # relies on) and raises "password cannot be longer than 72 bytes" even for
    # short passwords, during its own internal self-test.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_session_token(user_id):
    return get_serializer().dumps({"uid": user_id})


def validate_session_token(token, max_age=86400):
    try:
        data = get_serializer().loads(token, max_age=max_age)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


SESSION_COOKIE = "citybot_session"


def generate_invite_token():
    return secrets.token_urlsafe(32)


ROLE_HIERARCHY = {'superadmin': 3, 'admin': 2, 'editor': 1}


def has_role(user, minimum_role):
    if not user:
        return False
    return ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY.get(minimum_role, 0)
