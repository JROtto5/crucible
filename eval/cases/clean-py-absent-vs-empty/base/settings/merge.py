"""Per-project settings."""
DEFAULTS = {
    "retries": 3,
    "timeout_s": 30,
    "allowed_origins": ["*"],
    "banner": "Welcome!",
}


def effective(project):
    """Settings for a project. Every project uses the defaults for now."""
    return dict(DEFAULTS)
