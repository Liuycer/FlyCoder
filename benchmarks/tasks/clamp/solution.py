def solve(x, low, high):
    if low > high:
        raise ValueError("bounds")
    return min(max(x, low), high)
