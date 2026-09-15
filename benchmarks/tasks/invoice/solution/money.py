from decimal import Decimal, ROUND_HALF_UP
def cents(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
