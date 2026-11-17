import base64
import hashlib
import secrets
import time

ISSUER = "https://auth.example.test"

# code -> {"client_id", "redirect_uri", "expires", "challenge"}
_codes = {}


def _s256(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def metadata():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    }


def authorize(client_id, redirect_uri, code_challenge, code_challenge_method="S256"):
    if code_challenge_method != "S256" or not code_challenge:
        raise ValueError("invalid_request: PKCE S256 challenge required")
    code = secrets.token_urlsafe(32)
    _codes[code] = {"client_id": client_id, "redirect_uri": redirect_uri,
                    "expires": time.time() + 60,
                    "challenge": code_challenge}
    return code


def token(client_id, code, redirect_uri, code_verifier):
    grant = _codes.pop(code, None)
    if grant is None or grant["expires"] < time.time():
        raise PermissionError("invalid_grant")
    if grant["client_id"] != client_id or grant["redirect_uri"] != redirect_uri:
        raise PermissionError("invalid_grant")
    if not code_verifier or not secrets.compare_digest(_s256(code_verifier), grant["challenge"]):
        raise PermissionError("invalid_grant")
    return {"access_token": secrets.token_urlsafe(32), "token_type": "Bearer"}
