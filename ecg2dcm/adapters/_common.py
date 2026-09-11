"""Small helpers shared by the adapters."""
from typing import Optional


def text(el, path: str, default=None):
    """Stripped text of ``el.find(path)``, or ``default`` when absent or empty."""
    if el is None:
        return default
    n = el.find(path)
    if n is None or n.text is None:
        return default
    v = n.text.strip()
    return v if v else default


def number(s) -> Optional[float]:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def sex(s) -> Optional[str]:
    """Normalise a vendor sex/gender string to DICOM 'M' / 'F', else None (unknown)."""
    if s is None:
        return None
    v = str(s).strip().upper()
    if v in ('M', 'MALE', '1'):
        return 'M'
    if v in ('F', 'FEMALE', '2'):
        return 'F'
    return None


def person_name(family, given) -> Optional[str]:
    parts = [str(x).strip() for x in (family, given) if x and str(x).strip()]
    return '^'.join(parts) if parts else None
