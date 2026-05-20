import pdfplumber
import re
import datetime
from statistics import median


_NOISE_RE = re.compile(
    r'(?:'
    r'PREVIOUS\s+BALANCE|CREDIT\s+LIMIT|MINIMUM\s+PAYMENT'
    r'|SUB.?TOTAL|GRAND\s+TOTAL|BALANCE\s+PREVIOUS|STATEMENT\s+DATE'
    r'|PAYMENT\s+DUE|INTEREST\s+RATE|CASH\s+INTEREST|RETAIL\s+INTEREST'
    r'|CITI\s*MILES|CARRIED\s+FORWARD|EARNED\s+THIS|REDEEMED'
    r'|^Page\s+\d+\s+of\s+\d+|GST\s+Reg|Robinson\s+Road|P\.O\.\s*Box'
    r'|ALL\s+TRANSACTIONS|TRANSACTIONS\s+FOR|KINDLY\s+ENSURE'
    r'|EMERGENCY\s+HOTLINE|CONTACT\s+DETAIL'
    r'|^Transaction\s+Date|^Value\s+Date|^Cheque\b|^Withdrawal\b|^Deposit\b'
    r'|BALANCE\s+B/?F|STATEMENT\s+OF\s+ACCOUNT|For\s+enquiries'
    r'|Customer\s+Service|OCBC\s+Centre|Account\s+No'
    r'|^360\s+ACCOUNT|^[A-Z0-9]{15,}$'
    r')',
    re.IGNORECASE
)

# OCBC: DD MMM DD MMM DESCRIPTION [CHEQUE] AMOUNT BALANCE
_OCBC_RE = re.compile(
    r'^(\d{2})\s+([A-Z]{3})\s+\d{2}\s+[A-Z]{3}\s+(.*?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$'
)

# Citibank: DDMMM DESCRIPTION AMOUNT (no space in date, no year)
_CITI_RE = re.compile(
    r'^(\d{2})([A-Z]{3})\s+(.+?)\s+([\(\-]?[\d,]+\.\d{2}\)?)$'
)

# OCBC continuation lines to skip
_OCBC_SKIP_RE = re.compile(
    r'^(?:via\s|OTHR|to\s+\d|\d{6,10}$|[A-Za-z0-9]{20,}$)',
    re.IGNORECASE
)


def _clean_amount(raw):
    s = raw.strip().replace(',', '').replace('$', '').replace(' ', '')
    negative = s.startswith('(') or s.startswith('-')
    s = s.strip('()-')
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def _fmt_date(day, mon, year):
    try:
        return datetime.datetime.strptime(f"{day} {mon} {year}", "%d %b %Y").strftime("%d %b")
    except Exception:
        return f"{day} {mon}"


def _get_lines(pdf):
    """Get all lines across all pages using extract_text() first, fallback to word grouping."""
    lines = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        if text.strip():
            for line in text.splitlines():
                line = line.strip()
                if line:
                    lines.append(line)
        else:
            # Fallback: word bounding box grouping
            words = page.extract_words()
            if not words:
                continue
            if len(words) > 1:
                heights = [(w['bottom'] - w['top']) for w in words]
                from statistics import median
                snap = max(median(heights) * 0.8, 3.0)
            else:
                snap = 5.0
            buckets = {}
            for w in words:
                mid_y = (w['top'] + w['bottom']) / 2
                key = int(mid_y / snap)
                buckets.setdefault(key, []).append(w)
            for key in sorted(buckets):
                row = sorted(buckets[key], key=lambda w: w['x0'])
                line = ' '.join(w['text'] for w in row).strip()
                if line:
                    lines.append(line)
    return lines


def _parse_ocbc(lines, year):
    results = []
    pending_date = None
    pending_desc_parts = []
    pending_amount = None

    def flush():
        if pending_date and pending_amount is not None:
            desc = ' '.join(pending_desc_parts).strip()
            desc = re.sub(r'\s+', ' ', desc)
            if desc:
                results.append([pending_date, desc, f"{abs(pending_amount):.2f}"])

    for line in lines:
        if not line.strip():
            continue
        if _NOISE_RE.search(line):
            flush()
            pending_date = None
            pending_desc_parts = []
            pending_amount = None
            continue

        m = _OCBC_RE.match(line)
        if m:
            flush()
            day, mon = m.group(1), m.group(2)
            raw_desc = m.group(3).strip()
            amt_str = m.group(4)
            pending_date = _fmt_date(day, mon, year)
            pending_amount = _clean_amount(amt_str)
            raw_desc = re.sub(r'\s+\d{6,10}$', '', raw_desc).strip()
            pending_desc_parts = [raw_desc] if raw_desc else []
        elif pending_date is not None:
            if re.match(r'^\d{6,10}$', line):
                continue
            if _OCBC_SKIP_RE.match(line):
                continue
            cleaned = re.sub(r'\s+', ' ', line.strip())
            if cleaned:
                pending_desc_parts.append(cleaned)

    flush()
    return results


def _parse_citibank(lines, year):
    results = []
    for line in lines:
        if not line.strip() or _NOISE_RE.search(line):
            continue
        m = _CITI_RE.match(line)
        if m:
            day, mon, desc, amt_str = m.group(1), m.group(2), m.group(3), m.group(4)
            amount = _clean_amount(amt_str)
            if amount is not None:
                results.append([_fmt_date(day, mon, year), desc.strip(), f"{abs(amount):.2f}"])
    return results


def extract_pdf_tables(file, debug=False):
    rows = [["Date", "Description", "Amount"]]

    with pdfplumber.open(file) as pdf:
        year = datetime.datetime.now().year
        try:
            first_text = pdf.pages[0].extract_text() or ""
            m = re.search(r'\b(20\d{2})\b', first_text)
            if m:
                year = int(m.group(1))
        except Exception:
            pass

        all_lines = _get_lines(pdf)

        ocbc_rows = _parse_ocbc(all_lines, year)
        if ocbc_rows:
            rows.extend(ocbc_rows)
        else:
            rows.extend(_parse_citibank(all_lines, year))

    return rows