from . import gateway


def charge(customer, amount_cents):
    """Charge a customer in their own currency; returns the gateway's charge id."""
    return gateway.submit(f"cus-{customer.id}", amount_cents, customer.currency)
