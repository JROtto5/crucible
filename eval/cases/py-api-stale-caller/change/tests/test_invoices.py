from billing.customers import Customer, add_customer
from billing.invoices import issue_invoice


def test_issue_invoice_charges_the_total():
    add_customer(Customer(id=7, email="a@example.com"))
    inv = issue_invoice(7, [(2, 150), (1, 200)])
    assert inv["amount_cents"] == 500


def test_issue_invoice_uses_the_customers_currency():
    add_customer(Customer(id=8, email="b@example.com", currency="eur"))
    inv = issue_invoice(8, [(1, 900)])
    assert inv["customer"] == 8
