from decimal import Decimal
from money import cents
def invoice_total(items, tax_rate):
    return cents(sum(Decimal(str(p)) for p,q in items) + Decimal(str(tax_rate)))
