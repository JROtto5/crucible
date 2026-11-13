import os
import smtplib
import time


def smtp_host():
    return os.environ.get("MAILER_SMTP_HOST", "localhost")


def deliver_message(to, subject, body, retries=3):
    """Send one message.

    :param to: recipient address
    :param retries: how many times to retry after the first failure (so up to retries + 1 tries)

    Waits one second between tries.
    """
    last = None
    for i in range(retries + 1):
        try:
            with smtplib.SMTP(smtp_host()) as s:
                s.sendmail("noreply@example.com", [to], f"Subject: {subject}\n\n{body}")
            return True
        except smtplib.SMTPException as e:
            last = e
            time.sleep(1)
    raise last
