"""Per-project settings."""
DEFAULTS = {
    "retries": 3,
    "timeout_s": 30,
    "allowed_origins": ["*"],
    "banner": "Welcome!",
}


def effective(project):
    """Settings for a project: its own value for every key it sets, the default for the rest."""
    overrides = project.get("settings", {})
    return {key: overrides.get(key) or default for key, default in DEFAULTS.items()}
