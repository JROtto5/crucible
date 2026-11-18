"""Public edge: every external request comes through here."""
import logging

from .upstream import forward

log = logging.getLogger(__name__)


def handle(raw_path, user):
    return forward(raw_path, user)
