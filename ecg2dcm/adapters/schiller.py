"""Schiller SEMA EDI XML front end."""
import xml.etree.ElementTree as ET

import numpy as np

from ..ir import EcgRecord, Measurements, Waveform, LEAD_ORDER, derive_leads
from ._common import text, number, sex, person_name

_TYPES = {'ECG_RHYTHM': ('Rhythm', 'ORIGINAL'), 'ECG_RHYTHMS': ('Rhythm', 'ORIGINAL'),
          'ECG_AVERAGES': ('Median', 'DERIVED')}


def parse(source) -> EcgRecord:
    root = ET.parse(source).getroot()
    if not root.tag.endswith('SchillerEDI'):
        raise ValueError(f'not Schiller SEMA EDI (root <{root.tag}>)')
    rec = EcgRecord(source_format='Schiller SEMA')
    rec.study_description = '12-Lead ECG'
    pat = next(root.iter('patdata'), None)
    rec.patient_id = text(pat, 'id')
    rec.sex = sex(text(pat, 'gender'))
    rec.birth_date = (text(pat, 'birthdate') or '')[:8] or None
    rec.patient_name = person_name(text(pat, 'lastname'), text(pat, 'firstname'))
    hw = next(root.iter('aquiringdevice'), None)
    if hw is not None:
        h, sw = hw.find('hardware'), hw.find('software')
        if h is not None:
            rec.manufacturer = text(h, 'vendor')
            rec.model = text(h, 'model')
        if sw is not None:
            rec.software_version = text(sw, 'version')
    sdt = next(root.iter('startdatetime'), None)
    if sdt is not None:
        d, t = text(sdt, 'date'), text(sdt, 'time')
        if d and len(d) >= 8:
            rec.acquisition_date = d[:8]
        if t and len(t) >= 6:
            rec.acquisition_time = t[:6]
    ann = next(root.iter('annotation_global'), None)
    m = Measurements()
    if ann is not None:
        names = [n.text.strip() for n in ann.findall('name') if n.text]
        vals = [v.text.strip() for v in ann.findall('value') if v.text]
        rec.raw_measurements = dict(zip(names, vals))
        m.ventricular_rate = number(rec.raw_measurements.get('HR'))
    rec.measurements = m
    for wd in root.iter('wavedata'):
        ty = (wd.findtext('type') or '').strip().upper()
        label, orig = _TYPES.get(ty, (ty.title() or 'Rhythm', 'ORIGINAL'))
        res = wd.find('resolution')
        fs = number(text(res, 'samplerate')) or 500.0
        yres = number(text(res, 'yres')) or 1.0      # microvolts per LSB
        leads = {}
        for ch in wd.findall('channel'):
            name = text(ch, 'name')
            dtype = (text(ch, 'datastype') or '').upper()
            raw = text(ch, 'data')
            if not name or not raw or name not in LEAD_ORDER:
                continue
            if dtype != 'COMMASEPARATE':
                raise ValueError(f'unsupported Schiller datastype {dtype!r}')
            arr = np.fromstring(raw.rstrip(','), dtype=np.float64, sep=',')
            if arr.size:
                leads[name] = np.clip(arr, -32768, 32767).astype(np.int16)
        if leads:
            ordered, derived = derive_leads(leads)
            rec.waveforms.append(Waveform(label=label, originality=orig, sampling_frequency=fs,
                                          units_per_bit=yres, leads=ordered, derived=derived))
    if not rec.waveforms:
        raise ValueError('no waveform data found')
    rec.waveforms.sort(key=lambda w: 0 if w.label == 'Rhythm' else 1)
    return rec
