from cleaner import clean_name
def parse_rows(lines):
    return [(clean_name(line.split(",")[0]),line.split(",")[1]) for line in lines]
