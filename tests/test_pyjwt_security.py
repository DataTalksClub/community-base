"""Exercise the patched dependency with real RSA keys and signed tokens."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

AUDIENCE = "synthetic-package-client"
ISSUER = "synthetic-issuer"


@pytest.fixture
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def signed_token(key, **claims):
    payload = {
        "sub": "synthetic-learner",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "valid"})


def verified_claims(token, key, algorithms=("RS256",)):
    return jwt.decode(token, key, algorithms=algorithms, audience=AUDIENCE, issuer=ISSUER)


def test_malformed_rsa_jwk_does_not_discard_valid_signing_key(private_key):
    valid_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    valid_jwk["kid"] = "valid"
    malformed_jwk = {**valid_jwk, "kid": "malformed", "d": "AAAAAA"}

    key_set = jwt.PyJWKSet.from_dict({"keys": [malformed_jwk, valid_jwk]})

    assert [key.key_id for key in key_set] == ["valid"]
    claims = verified_claims(signed_token(private_key), key_set["valid"].key)
    assert claims["sub"] == "synthetic-learner"


def test_valid_signed_token_and_rejected_wrong_signature(private_key):
    public_key = private_key.public_key()
    assert verified_claims(signed_token(private_key), public_key)["sub"] == "synthetic-learner"
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(jwt.InvalidSignatureError):
        verified_claims(signed_token(other_key), public_key)


def test_expiry_audience_issuer_and_algorithm_denials_remain_effective(private_key):
    public_key = private_key.public_key()
    expired_at = datetime.now(UTC) - timedelta(minutes=5)
    with pytest.raises(jwt.ExpiredSignatureError):
        verified_claims(signed_token(private_key, exp=expired_at), public_key)
    with pytest.raises(jwt.InvalidAudienceError):
        verified_claims(signed_token(private_key, aud="other-client"), public_key)
    with pytest.raises(jwt.InvalidIssuerError):
        verified_claims(signed_token(private_key, iss="other-issuer"), public_key)
    with pytest.raises(jwt.InvalidAlgorithmError):
        verified_claims(signed_token(private_key), public_key, algorithms=("HS256",))
