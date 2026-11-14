from .charge import charge
from .customers import get_customer


def total_cents(lines):
    return sum(qty * unit_cents for qty, unit_cents in lines)


def issue_invoice(customer_id, lines):
    customer = get_customer(customer_id)
    amount = total_cents(lines)
    charge_id = charge(customer, amount)
    return {"customer": customer.id, "amount_cents": amount, "charge_id": charge_id}
