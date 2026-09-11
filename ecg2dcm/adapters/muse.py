"""GE MUSE ``<RestingECG>`` XML front end.

Element names follow the MUSE XML export (MUSE NX XML Developer Guide). Two
unit conventions of this format are handled here so that the writer never has
to know about them: ``<HighPassFilter>`` is expressed in hundredths of a hertz,
and the fiducial points ``<POnset>``, ``<POffset>``, ``<QOnset>``, ``<QOffset>``
and ``<TOffset>`` are sample positions within the median beat at
``<ECGSampleBase>`` hertz, not milliseconds.
"""
import base64
import xml.etree.ElementTree as ET

import numpy as np

from ..ir import EcgRecord, Measurements, Waveform, LEAD_ORDER, derive_leads
from ._common import text, number, sex, person_name

_TYPES = {'RHYTHM': ('Rhythm', 'ORIGINAL'), 'MEDIAN': ('Median', 'DERIVED')}
_AGE_UNITS = {'YEARS': 'Y', 'MONTHS': 'M', 'WEEKS': 'W', 'DAYS': 'D'}


def _date(s):
    """MUSE writes MM-DD-YYYY. A masked value such as XX-XX-XXXX yields None."""
    if not s:
        return None
    p = s.strip().split('-')
    if len(p) != 3 or not all(x.isdigit() for x in p):
        return None
    return f'{int(p[2]):04d}{int(p[0]):02d}{int(p[1]):02d}'


def _time(s):
    if not s:
        return None
    p = s.strip().split(':')
    if len(p) < 2 or not all(x.isdigit() for x in p):
        return None
    p = (p + ['0'])[:3]
    return ''.join(f'{int(x):02d}' for x in p)


def _measurements(meas) -> Measurements:
    m = Measurements()
    if meas is None:
        return m
    g = lambda tag: number(text(meas, tag))
    m.ventricular_rate = g('VentricularRate')
    m.atrial_rate = g('AtrialRate')
    m.pr_ms = g('PRInterval')
    m.qrs_ms = g('QRSDuration')
    m.qt_ms = g('QTInterval')
    m.qtc_ms = g('QTCorrected')
    m.p_axis_deg = g('PAxis')
    m.qrs_axis_deg = g('RAxis')
    m.t_axis_deg = g('TAxis')
    base = number(text(meas, 'ECGSampleBase')) or 500.0
    exp = number(text(meas, 'ECGSampleExponent')) or 0.0
    m.fiducial_sampling_frequency = base * (10 ** exp)
    for src, key in (('POnset', 'p_onset'), ('POffset', 'p_offset'), ('QOnset', 'qrs_onset'),
                     ('QOffset', 'qrs_offset'), ('TOffset', 't_offset')):
        v = number(text(meas, src))
        if v is not None and v >= 0:
            m.fiducials[key] = int(round(v))
    return m


def parse(source) -> EcgRecord:
    """``source`` is a path or a binary file-like object."""
    root = ET.parse(source).getroot()
    if root.tag != 'RestingECG':
        raise ValueError(f'not GE MUSE RestingECG (root <{root.tag}>)')
    rec = EcgRecord(source_format='GE MUSE')
    rec.manufacturer = 'GE Healthcare'
    rec.study_description = '12-Lead ECG'

    pat = root.find('PatientDemographics')
    test = root.find('TestDemographics')
    rec.patient_id = text(pat, 'PatientID')
    rec.patient_name = person_name(text(pat, 'PatientLastName'), text(pat, 'PatientFirstName'))
    rec.sex = sex(text(pat, 'Gender'))
    age = number(text(pat, 'PatientAge'))
    if age is not None:
        rec.age_value = int(age)
        rec.age_unit = _AGE_UNITS.get((text(pat, 'AgeUnits') or 'YEARS').upper(), 'Y')
    rec.birth_date = _date(text(pat, 'DateofBirth'))
    rec.ethnic_group = text(pat, 'Race')

    rec.model = text(test, 'AcquisitionDevice')
    rec.software_version = ' / '.join(x for x in (text(test, 'AcquisitionSoftwareVersion'),
                                                  text(test, 'AnalysisSoftwareVersion')) if x) or None
    rec.institution = text(test, 'SiteName')
    rec.department = text(test, 'LocationName')
    rec.station = text(test, 'RoomID')
    rec.operator = person_name(text(test, 'AcquisitionTechLastName'), text(test, 'AcquisitionTechFirstName'))
    rec.referring_physician = person_name(text(test, 'OverreaderLastName'), text(test, 'OverreaderFirstName'))
    rec.acquisition_date = _date(text(test, 'AcquisitionDate'))
    rec.acquisition_time = _time(text(test, 'AcquisitionTime'))
    rec.content_date = _date(text(test, 'EditDate'))
    rec.content_time = _time(text(test, 'EditTime'))

    meas = root.find('RestingECGMeasurements')
    if meas is not None:
        for m in meas:
            if len(m) == 0 and m.text and m.text.strip():
                rec.raw_measurements[m.tag] = m.text.strip()
    rec.measurements = _measurements(meas)

    diag = root.find('Diagnosis')
    if diag is not None:
        rec.diagnosis = [t for t in (text(s, 'StmtText') for s in diag.iter('DiagnosisStatement')) if t]

    for wf in root.iter('Waveform'):
        ty = (text(wf, 'WaveformType') or '').upper()
        label, orig = _TYPES.get(ty, (ty.title() or 'Rhythm', 'ORIGINAL'))
        base = number(text(wf, 'SampleBase')) or 500.0
        exp = number(text(wf, 'SampleExponent')) or 0.0
        fs = base * (10 ** exp)
        hp, lp, ac = text(wf, 'HighPassFilter'), text(wf, 'LowPassFilter'), text(wf, 'ACFilter')
        leads, upb, skew = {}, None, '0'
        for ld in wf.findall('LeadData'):
            lid, data = text(ld, 'LeadID'), text(ld, 'WaveFormData')
            if not lid or not data or lid not in LEAD_ORDER:
                continue
            n = int(number(text(ld, 'LeadSampleCountTotal')) or 0) or None
            arr = np.frombuffer(base64.b64decode(data), dtype='<i2')
            if n:
                arr = arr[:n]
            if arr.size:
                leads[lid] = arr.astype(np.int16)
            if upb is None:
                u = number(text(ld, 'LeadAmplitudeUnitsPerBit'))
                if u is not None:
                    upb = u * (1000.0 if 'MILLI' in (text(ld, 'LeadAmplitudeUnits') or '').upper() else 1.0)
                skew = text(ld, 'LeadOffsetFirstSample') or '0'
        if leads:
            ordered, derived = derive_leads(leads)
            rec.waveforms.append(Waveform(
                label=label, originality=orig, sampling_frequency=fs,
                units_per_bit=upb if upb is not None else 4.88,
                leads=ordered, derived=derived,
                highpass_hz=(number(hp) / 100.0) if number(hp) is not None else None,   # hundredths of Hz
                lowpass_hz=number(lp),
                notch_hz=number(ac) if ac and ac.strip().upper() != 'NONE' else None,
                sample_skew=skew))
    if not rec.waveforms:
        raise ValueError('no waveform data found')
    rec.waveforms.sort(key=lambda w: 0 if w.label == 'Rhythm' else 1)
    return rec
