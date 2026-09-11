"""Mortara / Welch Allyn ELI Link XML front end."""
import base64
import xml.etree.ElementTree as ET

import numpy as np

from ..ir import EcgRecord, Waveform, LEAD_ORDER, derive_leads
from ._common import sex, person_name


def parse(source) -> EcgRecord:
    root = ET.parse(source).getroot()
    if root.tag != 'ECG':
        raise ValueError(f'not Mortara ELI Link XML (root <{root.tag}>)')
    rec = EcgRecord(source_format='Mortara ELI')
    rec.study_description = '12-Lead ECG'
    src = next(root.iter('SOURCE'), None)
    if src is not None:
        rec.manufacturer = src.get('MANUFACTURER')
        rec.model = src.get('MODEL')
    subj = next(root.iter('SUBJECT'), None)
    if subj is not None:
        rec.patient_name = person_name(subj.get('LAST_NAME'), subj.get('FIRST_NAME'))
        rec.patient_id = subj.get('ID') or subj.get('LOCAL_ID')
        rec.sex = sex(subj.get('GENDER'))
        rec.birth_date = (subj.get('DOB_XML') or '').replace('-', '') or None
    at = root.get('ACQUISITION_TIME') or ''
    if len(at) >= 14:
        rec.acquisition_date, rec.acquisition_time = at[:8], at[8:14]
    interp = next(root.iter('AUTOMATIC_INTERPRETATION'), None)
    if interp is not None:
        rec.diagnosis = [s.get('TEXT') for s in interp.iter('STATEMENT') if s.get('TEXT')]

    def _decode(node):
        data = node.get('DATA') or (node.text or '')
        if not data.strip():
            return None, None
        bits = int(node.get('BITS', '16'))
        if bits != 16:
            raise ValueError(f'unsupported Mortara BITS={bits}')
        return node.get('NAME'), np.frombuffer(base64.b64decode(data), dtype='<i2')

    chans = list(root.iter('CHANNEL'))
    fs = float(chans[0].get('SAMPLE_FREQ', '1000')) if chans else 1000.0
    upmv = float(chans[0].get('UNITS_PER_MV', '1000')) if chans else 1000.0
    for nodes, label, orig in ((chans, 'Rhythm', 'ORIGINAL'),
                               (list((next(root.iter('TYPICAL_CYCLE'), None) or []).iter('TYPICAL_CYCLE_CHANNEL'))
                                if next(root.iter('TYPICAL_CYCLE'), None) is not None else [], 'Median', 'DERIVED')):
        leads = {}
        for c in nodes:
            n, a = _decode(c)
            if n in LEAD_ORDER and a is not None and a.size:
                leads[n] = a.astype(np.int16)
        if leads:
            ordered, derived = derive_leads(leads)
            rec.waveforms.append(Waveform(label=label, originality=orig, sampling_frequency=fs,
                                          units_per_bit=1000.0 / upmv, leads=ordered, derived=derived))
    if not rec.waveforms:
        raise ValueError('no waveform data found')
    return rec
