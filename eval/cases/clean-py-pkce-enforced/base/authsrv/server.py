import secrets
import time

ISSUER = "https://auth.example.test"

# code -> {"client_id", "redirect_uri", "expires"}
_codes = {}


def metadata():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
    }


def authorize(client_id, redirect_uri):
    code = secrets.token_urlsafe(32)
    _codes[code] = {"client_id": client_id, "redirect_uri": redirect_uri,
                    "expires": time.time() + 60}
    return code


def token(client_id, code, redirect_uri):
    grant = _codes.pop(code, None)
    if grant is None or grant["expires"] < time.time():
        raise PermissionError("invalid_grant")
    if grant["client_id"] != client_id or grant["redirect_uri"] != redirect_uri:
        raise PermissionError("invalid_grant")
    return {"access_token": secrets.token_urlsafe(32), "token_type": "Bearer"}
