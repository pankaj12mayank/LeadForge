from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="leadforge-session")


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str, max_age: int = 60 * 60 * 24 * 30) -> int | None:
    try:
        data = _serializer.loads(token, max_age=max_age)
        return int(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


_csrf = URLSafeTimedSerializer(settings.SECRET_KEY, salt="leadforge-csrf")


def create_csrf_token(session_id: str) -> str:
    return _csrf.dumps(session_id)


def verify_csrf_token(token: str, session_id: str, max_age: int = 60 * 60 * 2) -> bool:
    try:
        val = _csrf.loads(token, max_age=max_age)
        return val == session_id
    except (BadSignature, SignatureExpired):
        return False
