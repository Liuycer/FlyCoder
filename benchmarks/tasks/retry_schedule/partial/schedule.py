from settings import validate
def delays(base, cap, attempts):
    validate(base, cap, attempts)
    return [max(cap,base*2**i) for i in range(1,attempts)]
