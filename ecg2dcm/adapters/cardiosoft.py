"""GE CardioSoft ``<CardiologyXML>`` front end.

Unlike MUSE, CardioSoft states units on its measurement elements and records
the fiducial points in milliseconds; they are converted to sample positions of
the median block here.
"""
import xml.etree.ElementTree as ET

import numpy as np

from ..ir import EcgRecord, Measurements, Waveform, LEAD_ORDER, derive_leads
from ._common import text, number, sex, person_name


def _samples(node):
    """WaveformData holds comma-separated integers (whitespace and newlines allowed)."""
    txt = (node.text or '').strip()
    if not txt:
        return None
    return np.fromstring(txt.replace('\n', '').replace('\t', ''), dtype=np.int32, sep=',').astype(np.int16)


def parse(source) -> EcgRecord:
    root = ET.parse(source).getroot()
    if root.tag != 'CardiologyXML':
        raise ValueError(f'not CardioSoft CardiologyXML (root <{root.tag}>)')
    nxt = lambda tag: next(root.iter(tag), None)
    dev, pat, filt = nxt('DeviceInfo'), nxt('PatientInfo'), nxt('FilterSetting')
    rec = EcgRecord(source_format='GE CardioSoft')
    rec.manufacturer = 'GE Healthcare'
    rec.study_description = '12-Lead ECG'
    rec.model = text(dev, 'Desc')
    rec.software_version = text(dev, 'SoftwareVer')
    rec.patient_id = text(pat, 'PID')
    rec.sex = sex(text(pat, 'Gender'))
    age = pat.find('Age') if pat is not None else None
    if age is not None and number(age.text) is not None:
        rec.age_value = int(number(age.text))
        rec.age_unit = {'YEARS': 'Y', 'MONTHS': 'M', 'DAYS': 'D'}.get((age.get('units') or 'Years').upper(), 'Y')
    name = pat.find('Name') if pat is not None else None
    if name is not None:
        rec.patient_name = person_name(text(name, 'FamilyName'), text(name, 'GivenName'))
    d = root.find('ObservationDateTime')
    if d is not None:
        y, mo, da = text(d, 'Year'), text(d, 'Month'), text(d, 'Day')
        h, mi, s = text(d, 'Hour'), text(d, 'Minute'), text(d, 'Second')
        if y and mo and da:
            rec.acquisition_date = f'{int(y):04d}{int(mo):02d}{int(da):02d}'
        if h and mi and s:
            rec.acquisition_time = f'{int(h):02d}{int(mi):02d}{int(s):02d}'
    hp, lp = number(text(filt, 'HighPass')), number(text(filt, 'LowPass'))
    notch = 50.0 if text(filt, 'Filter50Hz') == 'Yes' else (60.0 if text(filt, 'Filter60Hz') == 'Yes' else None)

    meas = nxt('RestingECGMeasurements')
    m = Measurements()
    fid_ms = {}
    if meas is not None:
        for e in meas:
            if e.tag == 'MedianSamples':
                continue
            if e.text and e.text.strip():
                rec.raw_measurements[e.tag] = e.text.strip()
        g = lambda tag: number(text(meas, tag))
        m.ventricular_rate = g('VentricularRate')
        m.pr_ms = g('PQInterval')
        m.qrs_ms = g('QRSDuration')
        m.qt_ms = g('QTInterval')
        m.qtc_ms = g('QTCInterval')
        m.p_axis_deg = g('PAxis')
        m.qrs_axis_deg = g('RAxis')
        m.t_axis_deg = g('TAxis')
        for src, key in (('POnset', 'p_onset'), ('POffset', 'p_offset'), ('QOnset', 'qrs_onset'),
                         ('QOffset', 'qrs_offset'), ('TOffset', 't_offset')):
            v = g(src)
            if v is not None:
                fid_ms[key] = v
    interp = root.find('Interpretation')
    if interp is not None:
        rec.diagnosis = [s.text.strip() for s in interp.iter('Statement') if s.text and s.text.strip()]

    median_fs = None
    for tag, label, orig in (('StripData', 'Rhythm', 'ORIGINAL'), ('MedianSamples', 'Median', 'DERIVED')):
        blk = nxt(tag)
        if blk is None:
            continue
        fs = number(text(blk, 'SampleRate')) or 500.0
        res = number(text(blk, 'Resolution')) or 5.0         # microvolts per LSB
        leads = {}
        for wd in blk.iter('WaveformData'):
            lid = wd.get('lead')
            arr = _samples(wd)
            if lid in LEAD_ORDER and arr is not None and arr.size:
                leads[lid] = arr
        if not leads:
            continue
        ordered, derived = derive_leads(leads)
        rec.waveforms.append(Waveform(label=label, originality=orig, sampling_frequency=fs,
                                      units_per_bit=res, leads=ordered, derived=derived,
                                      highpass_hz=hp, lowpass_hz=lp, notch_hz=notch))
        if label == 'Median':
            median_fs = fs
    if fid_ms and median_fs:
        # milliseconds from the start of the median block -> sample positions
        m.fiducial_sampling_frequency = median_fs
        m.fiducials = {k: int(round(v * median_fs / 1000.0)) for k, v in fid_ms.items()}
    rec.measurements = m
    if not rec.waveforms:
        raise ValueError('no waveform data found')
    return rec
