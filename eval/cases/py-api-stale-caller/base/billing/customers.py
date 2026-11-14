from dataclasses import dataclass


@dataclass
class Customer:
    id: int
    email: str
    currency: str = "usd"


_CUSTOMERS = {}


def add_customer(c):
    _CUSTOMERS[c.id] = c
    return c


def get_customer(customer_id):
    return _CUSTOMERS[customer_id]
