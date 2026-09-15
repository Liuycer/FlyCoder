def validate(base, cap, attempts):
    if min(base,cap,attempts)<0:
        raise ValueError("negative")
