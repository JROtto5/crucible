class Declined(Exception):
    pass


_LEDGER = []


def submit(account, amount_cents, currency):
    if amount_cents <= 0:
        raise ValueError("amount must be positive")
    if account.startswith("blocked-"):
        raise Declined(account)
    _LEDGER.append((account, amount_cents, currency))
    return len(_LEDGER)
