from billing.customers import Customer, add_customer
from billing.invoices import issue_invoice


def test_issue_invoice_charges_the_total():
    add_customer(Customer(id=7, email="a@example.com"))
    inv = issue_invoice(7, [(2, 150), (1, 200)])
    assert inv["amount_cents"] == 500
