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

# DCS: DD MMM DESCRIPTION AMOUNT or DD/MM/YYYY DESCRIPTION AMOUNT
_DCS_RE = re.compile(
    r'^(?P<day>\d{1,2})\s+(?P<mon>[A-Z]{3})\s+(?P<desc>.+?)\s+(?P<amount>[\d,]+\.\d{2})(?:\s+[\d,]+\.\d{2})?$',
    re.IGNORECASE
)

_DCS_SLASH_RE = re.compile(
    r'^(?P<day>\d{1,2})[/-](?P<mon>\d{1,2})[/-](?P<year>\d{2,4})\s+(?P<desc>.+?)\s+(?P<amount>[\d,]+\.\d{2})(?:\s+[\d,]+\.\d{2})?$',
    re.IGNORECASE
)

_DCS_DUAL_DATE_RE = re.compile(
    r'^(?P<date1>\d{4}-\d{2}-\d{2})\s+(?P<date2>\d{4}-\d{2}-\d{2})\s+(?P<desc>.+?)\s+(?P<amount>[-]?(?:\$?\d[\d,]*\.\d{2}|\(\$?\d[\d,]*\.\d{2}\)))(?:\s*(?:CR|DR))?(?:\s+[\d,]+\.\d{2})?$',
    re.IGNORECASE
)

# OCBC continuation lines to skip
_OCBC_SKIP_RE = re.compile(
    r'^(?:via\s|OTHR|to\s+\d|\d{6,10}$|[A-Za-z0-9]{20,}$)',
    re.IGNORECASE
)

def _clean_amount(raw):
    if raw is None:
        return None
    s = str(raw).strip().upper()
    s = s.replace('CR', '').replace('DR', '')
    s = re.sub(r'(?i)^(?:SGD|MYR|USD|AUD|EUR|INR|IDR|RM)\s*', '', s)
    s = s.replace(',', '').replace('$', '').replace(' ', '')
    negative = s.startswith('(') or s.startswith('-')
    s = s.strip('()')
    s = s.strip('-')
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def _fmt_date(day, mon, year):
    try:
        return datetime.datetime.strptime(f"{day} {mon} {year}", "%d %b %Y").strftime("%d %b %Y")
    except Exception:
        return f"{day} {mon} {year}"


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


def _parse_dcs(lines, year):
    results = []

    for line in lines:
        if not line.strip() or _NOISE_RE.search(line):
            continue

        dual_match = _DCS_DUAL_DATE_RE.match(line)
        if dual_match:
            date_iso = dual_match.group('date2') or dual_match.group('date1')
            desc = dual_match.group('desc').strip()
            amount = _clean_amount(dual_match.group('amount'))
            if desc and amount is not None:
                try:
                    date_obj = datetime.datetime.strptime(date_iso, "%Y-%m-%d")
                    results.append([date_obj.strftime("%d %b %Y"), re.sub(r'\s+', ' ', desc), f"{abs(amount):.2f}"])
                except Exception:
                    pass
            continue

        date_match = re.match(
            r'^(?:(?P<day>\d{1,2})\s*(?P<mon>[A-Za-z]{3,9})(?:\s*(?P<year>\d{2,4}))?|(?P<day2>\d{1,2})[/-](?P<mon2>\d{1,2})[/-](?P<year2>\d{2,4}))\s*(?P<rest>.*)$',
            line,
            re.IGNORECASE
        )
        if not date_match:
            continue

        rest = date_match.group('rest').strip()
        amount_match = re.search(
            r'(?P<amount>[-]?(?:\$?\d[\d,]*\.\d{2}|\(\$?\d[\d,]*\.\d{2}\)))(?:\s*(?:CR|DR))?(?:\s+[\d,]+\.\d{2})?\s*$',
            rest,
            re.IGNORECASE
        )
        if not amount_match:
            continue

        desc = rest[:amount_match.start()].strip()
        amount = _clean_amount(amount_match.group('amount'))
        if not desc or amount is None:
            continue

        try:
            if date_match.group('day2') is not None:
                day = int(date_match.group('day2'))
                mon = int(date_match.group('mon2'))
                year_value = int(date_match.group('year2'))
                if year_value < 100:
                    year_value += 2000 if year_value < 50 else 1900
                date_str = datetime.datetime.strptime(f"{day} {mon} {year_value}", "%d %m %Y").strftime("%d %b %Y")
            else:
                day = int(date_match.group('day'))
                mon = (date_match.group('mon') or '').upper()
                year_value = date_match.group('year')
                if year_value:
                    year_value = int(year_value)
                    if year_value < 100:
                        year_value += 2000 if year_value < 50 else 1900
                    date_str = datetime.datetime.strptime(f"{day} {mon} {year_value}", "%d %b %Y").strftime("%d %b %Y")
                else:
                    date_str = _fmt_date(day, mon, year)
        except Exception:
            continue

        results.append([date_str, re.sub(r'\s+', ' ', desc), f"{abs(amount):.2f}"])

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
            dcs_rows = _parse_dcs(all_lines, year)
            if dcs_rows:
                rows.extend(dcs_rows)
            else:
                rows.extend(_parse_citibank(all_lines, year))

    return rows