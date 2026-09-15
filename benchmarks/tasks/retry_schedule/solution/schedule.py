from settings import validate
def delays(base, cap, attempts):
    validate(base, cap, attempts)
    return [min(cap,base*2**i) for i in range(attempts)]
