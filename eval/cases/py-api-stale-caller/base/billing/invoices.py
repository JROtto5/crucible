from .charge import charge
from .customers import get_customer


def total_cents(lines):
    return sum(qty * unit_cents for qty, unit_cents in lines)


def issue_invoice(customer_id, lines):
    amount = total_cents(lines)
    charge_id = charge(customer_id, amount)
    return {"customer": customer_id, "amount_cents": amount, "charge_id": charge_id}
