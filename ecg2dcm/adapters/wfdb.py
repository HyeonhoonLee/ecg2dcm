"""WFDB front end, producing the same IR as the vendor-format adapters.

WFDB is not a vendor format. Datasets distributed this way (PTB-XL, LUDB,
ECGDMMLD, Chapman-Shaoxing and Ningbo, MIMIC-IV-ECG) were converted from their
original vendor formats by the publishers, so this adapter exercises the mapping
and writing stages against records acquired at other institutions on other
manufacturers' equipment. It does not exercise native vendor-format parsing.

Only the parts of the format the published 12-lead datasets use are implemented:
single-segment records, storage formats 16, 61, 80 and 212, and per-signal gain,
baseline and ADC resolution. Anything else raises, rather than being guessed at.

Header layout (WFDB spec, https://physionet.org/physiotools/wag/header-5.htm):

    <record> <nsig> <fs> <nsamp> <base time> <base date>
    <file> <format>x<samples-per-frame>:<skew>+<offset> <gain>(<baseline>)/<units>
        <adc-res> <adc-zero> <init> <checksum> <blocksize> <description>
"""
import os
import re
import numpy as np

from ..ir import EcgRecord, Waveform, LEAD_ORDER, derive_leads

# WFDB lead names are case- and punctuation-inconsistent across datasets.
_LEAD_ALIASES = {
    'i': 'I', 'ii': 'II', 'iii': 'III',
    'avr': 'aVR', 'avl': 'aVL', 'avf': 'aVF',
    'v1': 'V1', 'v2': 'V2', 'v3': 'V3', 'v4': 'V4', 'v5': 'V5', 'v6': 'V6',
    'mlii': 'II', 'lead i': 'I', 'lead ii': 'II', 'lead iii': 'III',
}

_SIGNAL_RE = re.compile(
    r'^(?P<file>\S+)\s+'
    r'(?P<fmt>\d+)(?:x(?P<spf>\d+))?(?::(?P<skew>\d+))?(?:\+(?P<offset>\d+))?\s*'
    r'(?P<gain>[-\d.eE+]+)?(?:\((?P<baseline>[-\d]+)\))?(?:/(?P<units>\S+))?\s*'
    r'(?P<adcres>\d+)?\s*(?P<adczero>[-\d]+)?\s*(?P<init>[-\d]+)?\s*'
    r'(?P<cksum>[-\d]+)?\s*(?P<bsize>\d+)?\s*(?P<desc>.*)$')


_MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
     'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], start=1)}


def _as_time(tok):
    """HH:MM[:SS[.ffffff]] -> HHMMSS, else None."""
    if ':' not in tok:
        return None
    parts = tok.split('.')[0].split(':')
    if len(parts) < 2 or not all(x.isdigit() for x in parts):
        return None
    parts = (parts + ['0'])[:3]
    return ''.join(f'{int(x):02d}' for x in parts)


def _as_date(tok):
    """DD/MM/YYYY (the WFDB spec) or DD-Mon-YYYY -> YYYYMMDD, else None."""
    if '/' in tok:
        parts = tok.split('/')
        if len(parts) == 3 and all(x.isdigit() for x in parts):
            return f'{int(parts[2]):04d}{int(parts[1]):02d}{int(parts[0]):02d}'
        return None
    if '-' in tok:
        parts = tok.split('-')
        if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
            mon = _MONTHS.get(parts[1][:3].lower())
            if mon:
                return f'{int(parts[2]):04d}{mon:02d}{int(parts[0]):02d}'
    return None


def _read_header(path):
    with open(path, 'r', errors='replace') as fh:
        lines = [l.rstrip('\n') for l in fh
                 if l.strip() and not l.lstrip().startswith('#')]
    if not lines:
        raise ValueError('empty WFDB header')
    f = lines[0].split()
    name, nsig = f[0], int(f[1])
    if '/' in name:
        raise ValueError('multi-segment WFDB records are not supported')
    fs = float(f[2].split('/')[0]) if len(f) > 2 else 250.0
    nsamp = int(f[3]) if len(f) > 3 else None
    # The spec puts the base time (HH:MM:SS[.ffffff]) in field 5 and the base
    # date (DD/MM/YYYY) in field 6, and most published 12-lead datasets omit
    # both. Chapman-Shaoxing and Ningbo deviate: 1,000 of its 45,152 headers
    # carry "24-Mar-2021 05:42:20", which is the date first and in DD-Mon-YYYY
    # form. Classify each of the two fields by shape instead of by position, so
    # that both layouts are read and neither is mistaken for the other.
    base_time = base_date = None
    for tok in f[4:6]:
        t = _as_time(tok)
        if t and base_time is None:
            base_time = t
            continue
        d = _as_date(tok)
        if d and base_date is None:
            base_date = d
    signals = []
    for line in lines[1:1 + nsig]:
        m = _SIGNAL_RE.match(line.strip())
        if not m:
            raise ValueError(f'unparsable WFDB signal line: {line[:60]}')
        g = m.groupdict()
        signals.append({
            'file': g['file'],
            'fmt': int(g['fmt']),
            'spf': int(g['spf'] or 1),
            'offset': int(g['offset'] or 0),
            'gain': float(g['gain']) if g['gain'] else 200.0,
            'baseline': int(g['baseline']) if g['baseline'] else None,
            'units': (g['units'] or 'mV'),
            'adcres': int(g['adcres']) if g['adcres'] else 16,
            'adczero': int(g['adczero']) if g['adczero'] else 0,
            'desc': (g['desc'] or '').strip(),
        })
    if len(signals) != nsig:
        raise ValueError(f'header declares {nsig} signals but lists {len(signals)}')
    # Comment lines carry the per-record metadata in every dataset examined.
    comments = []
    with open(path, 'r', errors='replace') as fh:
        comments = [l.strip('# \n') for l in fh if l.lstrip().startswith('#')]
    return name, fs, nsamp, signals, comments, base_date, base_time


def _read_format16(path, nsig, nsamp, dtype, offset=0):
    raw = np.fromfile(path, dtype=dtype, offset=offset)
    n = len(raw) // nsig
    if nsamp:
        n = min(n, nsamp)
    return raw[:n * nsig].reshape(n, nsig)


def _read_format212(path, nsig, nsamp, offset=0):
    """Two 12-bit samples packed into three bytes, little end first."""
    b = np.fromfile(path, dtype=np.uint8, offset=offset)
    n_triplet = len(b) // 3
    b = b[:n_triplet * 3].reshape(-1, 3).astype(np.int32)
    first = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
    second = b[:, 2] | ((b[:, 1] >> 4) << 8)
    first[first > 2047] -= 4096
    second[second > 2047] -= 4096
    flat = np.empty(n_triplet * 2, dtype=np.int32)
    flat[0::2] = first
    flat[1::2] = second
    n = len(flat) // nsig
    if nsamp:
        n = min(n, nsamp)
    return flat[:n * nsig].reshape(n, nsig)


def _read_signals(hea_path, signals, nsamp):
    """Return an (nsamp, nsig) int array. All signals share one file in every
    12-lead dataset examined; a record that splits them across files raises."""
    files = {s['file'] for s in signals}
    if len(files) != 1:
        raise ValueError('per-signal WFDB data files are not supported')
    if any(s['spf'] != 1 for s in signals):
        raise ValueError('WFDB records with samples-per-frame > 1 are not supported')
    fmts = {s['fmt'] for s in signals}
    if len(fmts) != 1:
        raise ValueError(f'mixed WFDB storage formats in one record: {sorted(fmts)}')
    fmt = fmts.pop()
    # A byte offset in the signal specification skips a wrapping header. The
    # Chapman-Shaoxing and Ningbo records declare '16+24' because their signals
    # sit in a MATLAB v4 file whose header is 24 bytes long.
    offsets = {s['offset'] for s in signals}
    if len(offsets) != 1:
        raise ValueError(f'differing byte offsets in one record: {sorted(offsets)}')
    offset = offsets.pop()
    dat = os.path.join(os.path.dirname(hea_path), files.pop())
    nsig = len(signals)
    if fmt == 16:
        return _read_format16(dat, nsig, nsamp, '<i2', offset)
    if fmt == 61:
        return _read_format16(dat, nsig, nsamp, '>i2', offset)
    if fmt == 80:
        b = np.fromfile(dat, dtype=np.uint8, offset=offset).astype(np.int32)
        return b[:(len(b) // nsig) * nsig].reshape(-1, nsig)[:nsamp] - 128
    if fmt == 212:
        return _read_format212(dat, nsig, nsamp, offset)
    raise ValueError(f'WFDB storage format {fmt} is not supported')


def parse(source, acquisition_date=None, acquisition_time=None):
    path = str(source)
    """Read a WFDB record. `path` is the .hea file, or the record name.

    WFDB carries no acquisition instant unless the header supplies a base date,
    and most published 12-lead datasets omit it. Content Date (0008,0023) and
    Acquisition DateTime (0008,002A) are Type 1, so a record with no date cannot
    be written as a conformant object. Callers that hold the date in a sidecar
    table (PTB-XL records it in ptbxl_database.csv) pass it in here; callers that
    do not leave it None and the writer refuses the record with a stated reason.
    """
    hea = path if str(path).endswith('.hea') else str(path) + '.hea'
    name, fs, nsamp, signals, comments, base_date, base_time = _read_header(hea)
    raw = _read_signals(hea, signals, nsamp)

    rec = EcgRecord(source_format='WFDB')
    rec.patient_id = name
    rec.acquisition_date = acquisition_date or base_date
    rec.acquisition_time = acquisition_time or base_time
    for c in comments:
        # Datasets differ on whether the key is bracketed: '#age: 51' in
        # PhysioNet challenge records, '#<age>: 51' in LUDB.
        key, _, val = c.partition(':')
        key = key.strip().strip('<>').lower()
        val = val.strip()
        if key == 'age' and val.replace('.', '', 1).isdigit():
            rec.age = str(int(float(val)))
        elif key == 'sex':
            rec.sex = {'M': 'M', 'MALE': 'M', 'F': 'F', 'FEMALE': 'F'}.get(val.upper())
        elif key in ('dx', 'diagnoses') and val:
            rec.diagnosis = [x.strip() for x in val.split(',') if x.strip()]

    # Convert each signal to microvolts per least significant bit. WFDB stores
    # gain in ADC units per physical unit, so the reciprocal is the scale, and
    # the writer needs one common scale for the multiplex group. Rescale each
    # signal onto the finest of them rather than assuming they agree.
    scales = []
    for s in signals:
        u = s['units'].lower()
        per_unit = {'mv': 1000.0, 'uv': 1.0, 'v': 1e6}.get(u)
        if per_unit is None:
            raise ValueError(f'unsupported WFDB signal units: {s["units"]}')
        gain = s['gain'] or 200.0
        scales.append(per_unit / gain)          # microvolts per stored unit
    upb = min(scales)

    leads = {}
    for i, s in enumerate(signals):
        label = _LEAD_ALIASES.get(s['desc'].strip().lower())
        if label is None or label in leads or label not in LEAD_ORDER:
            continue
        col = raw[:, i].astype(np.float64)
        base = s['baseline'] if s['baseline'] is not None else s['adczero']
        col = (col - base) * (scales[i] / upb)
        leads[label] = np.clip(np.rint(col), -32768, 32767).astype(np.int16)
    if not leads:
        raise ValueError('no recognizable ECG leads in WFDB record '
                         f'(signals: {[s["desc"] for s in signals]})')

    ordered, derived = derive_leads(leads)
    rec.waveforms.append(Waveform(
        label='Rhythm', originality='ORIGINAL', sampling_frequency=fs,
        units_per_bit=upb, leads=ordered, derived=derived))
    return rec
