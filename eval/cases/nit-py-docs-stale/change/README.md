# mailer

Small SMTP helper.

```python
from mailer.send import deliver_message
deliver_message("a@example.com", "Hi", "Hello", retries=3)
```

`retries` is how many times a failed send is retried (default 3).

The SMTP server comes from `MAILER_SMTP_HOST` (default `localhost`).
