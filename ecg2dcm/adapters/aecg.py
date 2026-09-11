"""HL7 v3 Annotated ECG (aECG) front end."""
import xml.etree.ElementTree as ET

import numpy as np

from ..ir import EcgRecord, Waveform, LEAD_ORDER, derive_leads
from ._common import sex

NS = '{urn:hl7-org:v3}'
_LEAD = {'MDC_ECG_LEAD_I': 'I', 'MDC_ECG_LEAD_II': 'II', 'MDC_ECG_LEAD_III': 'III',
         'MDC_ECG_LEAD_AVR': 'aVR', 'MDC_ECG_LEAD_AVL': 'aVL', 'MDC_ECG_LEAD_AVF': 'aVF',
         'MDC_ECG_LEAD_V1': 'V1', 'MDC_ECG_LEAD_V2': 'V2', 'MDC_ECG_LEAD_V3': 'V3',
         'MDC_ECG_LEAD_V4': 'V4', 'MDC_ECG_LEAD_V5': 'V5', 'MDC_ECG_LEAD_V6': 'V6'}


def _txt(node):
    return (node.text or '').strip() if node is not None and node.text else None


def parse(source) -> EcgRecord:
    root = ET.parse(source).getroot()
    if not root.tag.endswith('AnnotatedECG'):
        raise ValueError(f'not HL7 aECG (root <{root.tag.split("}")[-1]}>)')
    rec = EcgRecord(source_format='HL7 aECG')
    rec.study_description = '12-Lead ECG'
    dev = next(root.iter(NS + 'manufacturedSeriesDevice'), None) or next(root.iter(NS + 'manufacturedDevice'), None)
    if dev is not None:
        rec.model = _txt(dev.find(NS + 'manufacturerModelName'))
        rec.software_version = _txt(dev.find(NS + 'softwareName'))
    org = next(root.iter(NS + 'manufacturerOrganization'), None)
    if org is not None:
        rec.manufacturer = _txt(org.find(NS + 'name'))
    subj = next(root.iter(NS + 'trialSubject'), None)
    if subj is not None:
        sid = subj.find(NS + 'id')
        if sid is not None:
            rec.patient_id = sid.get('extension') or sid.get('root')
        dem = next(subj.iter(NS + 'subjectDemographicPerson'), None)
        if dem is not None:
            rec.patient_name = _txt(dem.find(NS + 'name'))
            g, b = dem.find(NS + 'administrativeGenderCode'), dem.find(NS + 'birthTime')
            if g is not None:
                rec.sex = sex(g.get('code'))
            if b is not None and b.get('value'):
                rec.birth_date = b.get('value')[:8]

    scope = None
    for ser in root.iter(NS + 'series'):
        c = ser.find(NS + 'code')
        if c is not None and (c.get('code') or '').upper() == 'RHYTHM':
            scope = ser
            break
    if scope is None:
        scope = root
    seqsets = list(scope.iter(NS + 'sequenceSet')) or [scope]
    for ss in seqsets:
        leads, fs, scale, kind = {}, None, None, None
        for s_ in ss.iter(NS + 'sequence'):
            code, val = s_.find(NS + 'code'), s_.find(NS + 'value')
            if code is None or val is None:
                continue
            c = (code.get('code') or '').upper()
            if c in ('TIME_ABSOLUTE', 'TIME_RELATIVE'):
                kind = c
                head, inc = val.find(NS + 'head'), val.find(NS + 'increment')
                if c == 'TIME_ABSOLUTE' and head is not None and head.get('value'):
                    v = head.get('value')
                    rec.acquisition_date, rec.acquisition_time = v[:8], (v[8:14] or '000000').ljust(6, '0')
                if inc is not None and inc.get('value'):
                    step = float(inc.get('value'))
                    step_s = step / 1000.0 if inc.get('unit', 's') == 'ms' else step
                    if step_s > 0:
                        fs = 1.0 / step_s
                continue
            lead = _LEAD.get(c)
            if lead is None or lead not in LEAD_ORDER:
                continue
            dg, sc = val.find(NS + 'digits'), val.find(NS + 'scale')
            if dg is None or not (dg.text or '').strip():
                continue
            arr = np.fromstring(dg.text.strip(), dtype=np.float64, sep=' ')
            if not arr.size:
                continue
            leads[lead] = np.clip(arr, -32768, 32767).astype(np.int16)
            if sc is not None and sc.get('value'):
                scale = float(sc.get('value'))
        if not leads:
            continue
        label, orig = ('Median', 'DERIVED') if kind == 'TIME_RELATIVE' else ('Rhythm', 'ORIGINAL')
        ordered, derived = derive_leads(leads)
        rec.waveforms.append(Waveform(label=label, originality=orig, sampling_frequency=fs or 500.0,
                                      units_per_bit=scale or 1.0, leads=ordered, derived=derived))
    if not rec.waveforms:
        raise ValueError('no lead sequences found')
    rec.waveforms.sort(key=lambda w: 0 if w.label == 'Rhythm' else 1)
    return rec
