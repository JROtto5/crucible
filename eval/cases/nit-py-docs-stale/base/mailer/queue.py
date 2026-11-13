from .send import deliver_message


def flush(pending):
    """Send everything queued. Each item goes through deliver_message, which retries 3 times after the
    first failure before giving up, so a flush of n items makes at most 4n SMTP attempts."""
    for to, subject, body in pending:
        deliver_message(to, subject, body)
