"""Detect the source format of a file and hand it to the right front end."""
import re
import xml.etree.ElementTree as ET  # noqa: F401  (kept for callers that want the parser)

from . import muse, cardiosoft, philips, schiller, mortara, aecg, wfdb


class UnsupportedFormatError(ValueError):
    pass


# (root element, human name, adapter module)
_ROOTS = [
    ('RestingECG', 'GE MUSE', muse),
    ('CardiologyXML', 'GE CardioSoft', cardiosoft),
    ('restingecgdata', 'Philips Sierra', philips),
    ('SchillerEDI', 'Schiller SEMA', schiller),
    ('ECG', 'Mortara ELI', mortara),
    ('AnnotatedECG', 'HL7 aECG', aecg),
]


def sniff(path):
    """Return ``(format name, module)`` from the file itself, without a full parse."""
    p = str(path)
    if p.lower().endswith('.hea'):
        return 'WFDB', wfdb
    raw = open(p, 'rb').read(4096)
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        head = raw.decode('utf-16', 'replace')
    else:
        m = re.match(rb'<\?xml[^>]*encoding=["\']([^"\']+)', raw)
        head = raw.decode(m.group(1).decode() if m else 'utf-8', 'replace')
    m = re.search(r'<([A-Za-z_][\w.\-]*)[\s>]',
                  re.sub(r'<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>', '', head, flags=re.S))
    root = (m.group(1).split(':')[-1] if m else '').split('.')[-1]
    for tag, name, mod in _ROOTS:
        if root == tag:
            return name, mod
    raise UnsupportedFormatError(
        f'unrecognised root element <{root}>; supported: ' + ', '.join(t for t, _, _ in _ROOTS) + ', WFDB (.hea)')


def parse(path, **kwargs):
    """Parse any supported file into an :class:`~ecg2dcm.ir.EcgRecord`."""
    _, mod = sniff(path)
    return mod.parse(path, **kwargs) if mod is wfdb else mod.parse(path)
