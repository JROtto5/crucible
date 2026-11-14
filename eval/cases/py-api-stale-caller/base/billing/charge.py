from . import gateway
from .customers import get_customer


def charge(customer_id, amount_cents):
    """Charge a customer in their own currency; returns the gateway's charge id."""
    customer = get_customer(customer_id)
    return gateway.submit(f"cus-{customer.id}", amount_cents, customer.currency)
