from cleaner import clean_name
def parse_rows(lines):
    rows=[]
    for line in lines:
        if not line.strip():
            continue
        parts=line.split(",")
        if len(parts)!=2:
            raise ValueError("row")
        rows.append((clean_name(parts[0]),int(parts[1].strip())))
    return rows
