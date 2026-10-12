"""Country calling codes used by landing page forms (ISO code, name, dial code)."""

COUNTRIES = [
    ("IN", "India", "+91"), ("AE", "United Arab Emirates", "+971"), ("US", "United States", "+1"),
    ("GB", "United Kingdom", "+44"), ("CA", "Canada", "+1"), ("AU", "Australia", "+61"),
    ("SG", "Singapore", "+65"), ("SA", "Saudi Arabia", "+966"), ("QA", "Qatar", "+974"),
    ("KW", "Kuwait", "+965"), ("OM", "Oman", "+968"), ("BH", "Bahrain", "+973"),
    ("NP", "Nepal", "+977"), ("BD", "Bangladesh", "+880"), ("LK", "Sri Lanka", "+94"),
    ("PK", "Pakistan", "+92"), ("MY", "Malaysia", "+60"), ("ID", "Indonesia", "+62"),
    ("TH", "Thailand", "+66"), ("PH", "Philippines", "+63"), ("VN", "Vietnam", "+84"),
    ("HK", "Hong Kong", "+852"), ("JP", "Japan", "+81"), ("KR", "South Korea", "+82"),
    ("CN", "China", "+86"), ("NZ", "New Zealand", "+64"), ("ZA", "South Africa", "+27"),
    ("NG", "Nigeria", "+234"), ("KE", "Kenya", "+254"), ("EG", "Egypt", "+20"),
    ("DE", "Germany", "+49"), ("FR", "France", "+33"), ("IT", "Italy", "+39"),
    ("ES", "Spain", "+34"), ("NL", "Netherlands", "+31"), ("BE", "Belgium", "+32"),
    ("CH", "Switzerland", "+41"), ("SE", "Sweden", "+46"), ("NO", "Norway", "+47"),
    ("DK", "Denmark", "+45"), ("IE", "Ireland", "+353"), ("PT", "Portugal", "+351"),
    ("PL", "Poland", "+48"), ("TR", "Turkey", "+90"), ("IL", "Israel", "+972"),
    ("RU", "Russia", "+7"), ("BR", "Brazil", "+55"), ("MX", "Mexico", "+52"),
    ("AR", "Argentina", "+54"), ("CL", "Chile", "+56"), ("CO", "Colombia", "+57"),
]
BY_ISO = {iso: {"iso": iso, "name": name, "dial": dial} for iso, name, dial in COUNTRIES}


def dial_code(value, default="+91"):
    """Accept an ISO code ('IN') or a dial code ('+91' / '91'); return '+91'."""
    value = str(value or "").strip()
    if not value:
        return default
    if value.upper() in BY_ISO:
        return BY_ISO[value.upper()]["dial"]
    digits = "".join(ch for ch in value if ch.isdigit())
    return f"+{digits}" if digits else default
