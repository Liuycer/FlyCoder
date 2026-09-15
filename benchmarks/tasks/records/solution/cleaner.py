def clean_name(value):
    value=value.strip().lower()
    if not value:
        raise ValueError("empty name")
    return value
