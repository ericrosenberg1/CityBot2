import secrets
from datetime import datetime
from pathlib import Path
from passlib.hash import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request

SECRET_KEY_PATH = Path("data/secret.key")


def get_secret_key():
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.parent.mkdir(exist_ok=True)
    SECRET_KEY_PATH.write_text(key)
    return key


_serializer = None


def get_serializer():
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(get_secret_key())
    return _serializer


def hash_password(password):
    return bcrypt.hash(password)


def verify_password(password, hashed):
    return bcrypt.verify(password, hashed)


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
