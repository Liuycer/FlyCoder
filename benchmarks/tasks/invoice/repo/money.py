from decimal import Decimal
def cents(value):
    return Decimal(str(value)).quantize(Decimal("1"))
