def solve(values, size):
    if size <= 0:
        raise ValueError("size")
    return [values[i:i+size] for i in range(0,len(values),size)]
