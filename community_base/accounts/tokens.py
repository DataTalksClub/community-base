import datetime
import uuid

import jwt
from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

JWT_ALGORITHM = "HS256"
PASSWORD_RESET_ACTION = "password_reset"
PASSWORD_RESET_PROOF = "reset_proof"


class ActionTokenError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PasswordStateTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "community_base.accounts.PasswordStateTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{timestamp}"

    def check_token(self, user, token):
        if not user or not token:
            return False
        try:
            timestamp = base36_to_int(token.split("-", 1)[0])
        except (ValueError, TypeError):
            return False
        return any(
            constant_time_compare(self._make_token_with_timestamp(user, timestamp, secret), token)
            for secret in (self.secret, *self.secret_fallbacks)
        )


_password_proof = PasswordStateTokenGenerator()


def generate_verification_token(user, *, return_path="", expiry_hours=24):
    payload = {
        "user_id": user.pk,
        "email": user.email,
        "action": "verify_email",
        "jti": str(uuid.uuid4()),
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=expiry_hours),
    }
    if return_path:
        payload["return_path"] = return_path
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def load_verification_token(token):
    payload = _decode(token)
    if payload.get("action") != "verify_email" or not payload.get("user_id"):
        raise ActionTokenError("invalid")
    return payload


def generate_password_reset_token(user, *, expiry_hours=1):
    return jwt.encode(
        {
            "user_id": user.pk,
            "action": PASSWORD_RESET_ACTION,
            "jti": str(uuid.uuid4()),
            "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=expiry_hours),
            PASSWORD_RESET_PROOF: _password_proof.make_token(user),
        },
        settings.SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def load_password_reset_token(token):
    payload = _decode(token)
    if payload.get("action") != PASSWORD_RESET_ACTION or not payload.get("user_id"):
        raise ActionTokenError("invalid")
    return payload


def password_reset_token_matches(user, payload):
    return _password_proof.check_token(user, payload.get(PASSWORD_RESET_PROOF))


def _decode(token):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise ActionTokenError("expired") from error
    except jwt.InvalidTokenError as error:
        raise ActionTokenError("invalid") from error
