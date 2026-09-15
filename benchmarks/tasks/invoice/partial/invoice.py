from decimal import Decimal
from money import cents
def invoice_total(items, tax_rate):
    subtotal = sum((Decimal(str(p))*q for p,q in items), Decimal(0))
    return cents(subtotal*(1+Decimal(str(tax_rate))))
