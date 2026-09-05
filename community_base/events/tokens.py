import datetime
import uuid

import jwt
from django.conf import settings

JWT_ALGORITHM = "HS256"


class RegistrationTokenError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def generate_registration_token(
    registration,
    *,
    action,
    issued_at=None,
    jti=None,
    expiry_hours=24,
):
    issued_at = issued_at or datetime.datetime.now(datetime.UTC)
    return jwt.encode(
        {
            "registration_id": str(registration.pk),
            "registration_version": registration.version,
            "action": action,
            "jti": str(jti or uuid.uuid4()),
            "exp": issued_at + datetime.timedelta(hours=expiry_hours),
        },
        settings.SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def load_registration_token(token, *, action):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise RegistrationTokenError("expired") from error
    except jwt.InvalidTokenError as error:
        raise RegistrationTokenError("invalid") from error
    if payload.get("action") != action or not payload.get("registration_id"):
        raise RegistrationTokenError("invalid")
    try:
        payload["registration_id"] = uuid.UUID(payload["registration_id"])
        payload["registration_version"] = int(payload["registration_version"])
    except (KeyError, TypeError, ValueError) as error:
        raise RegistrationTokenError("invalid") from error
    return payload
