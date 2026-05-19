import pdfplumber
import re

def extract_pdf_text(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for p in pdf.pages:
            text += p.extract_text() or ""
    return text

def extract_pdf_tables(file):
    text = extract_pdf_text(file)
    lines = text.split('\n')

    rows = [["Date", "Description", "Amount"]]
    date_regex = r"^(\d{2}\s[A-Z]{3})\s"
    current = None

    for line in lines:
        line = line.strip()
        m = re.match(date_regex, line)

        if m:
            if current:
                rows.append(current)

            nums = re.findall(r"(\d[\d,.]*\.\d{2})", line)
            date = m.group(1)

            desc = line[len(date):].strip()
            for n in nums:
                desc = desc.replace(n, "").strip()

            current = [date, desc, nums[0] if nums else "0.00"]
            continue

        if current:
            if len(current[1]) > 150 or any(x in line.upper() for x in ["PAGE", "TOTAL"]):
                rows.append(current)
                current = None
            else:
                if not re.match(r"^\d{5,}$", line):
                    current[1] += f" {line}"

    if current:
        rows.append(current)

    return rows
