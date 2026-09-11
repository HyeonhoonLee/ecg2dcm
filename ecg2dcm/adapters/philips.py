"""Philips Sierra ECG / ``<restingecgdata>`` front end.

Waveforms are stored base64-encoded and XLI-compressed; decompression is done
by the ``sierraecg`` package (an optional dependency: ``pip install ecg2dcm[philips]``).
"""
import re
import xml.etree.ElementTree as ET

import numpy as np

from ..ir import EcgRecord, Waveform, LEAD_ORDER, derive_leads
from ._common import sex, person_name

_DECL = re.compile(r'^\s*<\?xml[^>]*\?>')


def _read_text(path):
    raw = open(path, 'rb').read()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16')
    m = re.match(rb'<\?xml[^>]*encoding=["\']([^"\']+)', raw)
    return raw.decode(m.group(1).decode() if m else 'utf-8', 'replace')


def _strip_ns(tag):
    return tag.split('}')[-1]


def parse(source) -> EcgRecord:
    try:
        import sierraecg
    except ImportError as e:
        raise ImportError('Philips restingecgdata needs the sierraecg package: pip install "ecg2dcm[philips]"') from e
    path = str(source)
    txt = _DECL.sub('', _read_text(path), count=1)
    root = ET.fromstring(txt)
    if _strip_ns(root.tag) != 'restingecgdata':
        raise ValueError(f'not Philips restingecgdata (root <{_strip_ns(root.tag)}>)')
    find = lambda t: next((e for e in root.iter() if _strip_ns(e.tag) == t), None)
    txt_of = lambda t: (find(t).text.strip() if find(t) is not None and find(t).text else None)

    ecg = sierraecg.read_file(path)
    rec = EcgRecord(source_format='Philips Sierra')
    rec.manufacturer = 'Philips'
    rec.study_description = '12-Lead ECG'
    mach = find('machine')
    if mach is not None:
        rec.model = (mach.text or '').strip() or None
        rec.software_version = mach.get('detaildescription')
    rec.patient_id = txt_of('patientid')
    rec.patient_name = person_name(txt_of('familyname'), txt_of('givenname'))
    rec.sex = sex(txt_of('sex'))
    dob = (txt_of('dateofbirth') or '').replace('-', '')
    rec.birth_date = dob[:8] if len(dob) >= 8 else None
    acq = find('dataacquisition')
    if acq is not None:
        d, t = acq.get('date'), acq.get('time')
        if d:
            rec.acquisition_date = d.replace('-', '')
        if t:
            rec.acquisition_time = t.replace(':', '')[:6]
    fs = float(txt_of('samplingrate') or 500)
    res = float(txt_of('signalresolution') or 5)     # microvolts per LSB
    hp, lp = txt_of('highpass'), txt_of('lowpass')
    notch = txt_of('notchfilter') or txt_of('acsetting')
    notch_hz = float(notch) if notch and notch.replace('.', '', 1).isdigit() else None
    gm = find('globalmeasurements')
    if gm is not None:
        for e in gm:
            if len(e) == 0 and e.text and e.text.strip():
                rec.raw_measurements[_strip_ns(e.tag)] = e.text.strip()

    leads = {}
    for l in ecg.leads:
        arr = np.asarray(l.samples, dtype=np.int32)
        if l.label in LEAD_ORDER and arr.size:
            leads[l.label] = np.clip(arr, -32768, 32767).astype(np.int16)
    if not leads:
        raise ValueError('no decoded leads')
    ordered, derived = derive_leads(leads)
    rec.waveforms.append(Waveform(label='Rhythm', originality='ORIGINAL', sampling_frequency=fs,
                                  units_per_bit=res, leads=ordered, derived=derived,
                                  highpass_hz=float(hp) if hp else None,
                                  lowpass_hz=float(lp) if lp else None, notch_hz=notch_hz))
    rb = {}
    for b in getattr(ecg, 'repbeats', []) or []:
        arr = np.asarray(getattr(b, 'samples', []), dtype=np.int32)
        lab = getattr(b, 'label', None)
        if lab in LEAD_ORDER and arr.size:
            rb[lab] = np.clip(arr, -32768, 32767).astype(np.int16)
    if rb:
        ordered, derived = derive_leads(rb)
        rec.waveforms.append(Waveform(label='Median', originality='DERIVED', sampling_frequency=fs,
                                      units_per_bit=res, leads=ordered, derived=derived,
                                      highpass_hz=float(hp) if hp else None,
                                      lowpass_hz=float(lp) if lp else None))
    for st in root.iter():
        if _strip_ns(st.tag) == 'statement':
            s = ''.join(x.text or '' for x in st.iter() if (x.text or '').strip())
            if s.strip():
                rec.diagnosis.append(s.strip())
    return rec
