"""The single DICOM writer: :class:`~ecg2dcm.ir.EcgRecord` -> General ECG Waveform Storage.

Every source format reaches DICOM through this module, so the attribute
mapping (Tables 3 and 4 of the manuscript, ``docs/mapping/attribute_mapping.csv``),
the coded values (:mod:`ecg2dcm.codes`) and the de-identification rules
(``docs/deidentification.md``) are implemented exactly once.

Why General ECG rather than 12-Lead ECG Waveform Storage: the 12-Lead ECG IOD
caps the number of channels across all multiplex groups at 13 (PS3.3
A.34.3.4.4), and a record with a twelve-channel rhythm group and a
twelve-channel median group carries 24. The General ECG IOD has the same
module table and allows up to four groups of 24 channels (A.34.4.4.2-3).
"""
import copy
import random
from datetime import datetime
from typing import Optional

import numpy as np
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID, generate_uid

from . import codes
from .ir import EcgRecord, Measurements

ANONYMIZED = 'Anonymized'
DEID_TIME = '000000'


# --------------------------------------------------------------------------- helpers
def _ds(v) -> str:
    """Format a number for VR DS, which is capped at 16 bytes.

    A gain expressed as microvolts per least significant bit can carry more
    digits than that: WFDB stores gain as ADC units per millivolt, so 2317
    units/mV gives 0.43159257660768235. Shorten to the longest representation
    that fits rather than emit a value that violates the VR.
    """
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        s = str(int(f))
        return s if len(s) <= 16 else f'{f:.9g}'
    s = repr(f)
    if len(s) <= 16:
        return s
    for digits in range(15, 0, -1):
        s = f'{f:.{digits}g}'
        if len(s) <= 16:
            return s
    return f'{f:.6g}'


def _code(c: codes.Code) -> Dataset:
    d = Dataset()
    d.CodeValue = c.value
    d.CodingSchemeDesignator = c.scheme
    d.CodeMeaning = c.meaning
    return d


def _lo(v, n=64) -> Optional[str]:
    """LO and SH are length-capped; some vendors put long descriptors in them."""
    return str(v)[:n] if v is not None and str(v) != '' else None


def _study_id() -> str:
    """Study ID (0020,0010) is SH, at most 16 characters; generated, as in Supplementary Table 3."""
    return ''.join(random.choice('0123456789') for _ in range(16))


# --------------------------------------------------------------------------- de-identification
def deidentify(rec: EcgRecord, patient_id: str) -> EcgRecord:
    """Apply the rule set of Supplementary Tables 5 and 6 and return a new record.

    Identifiers are replaced by the literal ``Anonymized``, the patient ID by
    the caller's surrogate, dates keep year and month with the day set to 01,
    times become 00:00:00, the birth date is dropped, and free-text diagnosis
    statements are dropped because vendor reports can embed reader names.
    """
    r = copy.copy(rec)
    r.patient_name = ANONYMIZED
    r.patient_id = patient_id
    r.birth_date = None
    r.referring_physician = ANONYMIZED
    r.operator = ANONYMIZED
    r.institution = ANONYMIZED
    r.department = ANONYMIZED
    r.station = ANONYMIZED
    for f in ('acquisition_date', 'content_date'):
        v = getattr(r, f)
        if v and len(v) == 8:
            setattr(r, f, v[:6] + '01')
    r.acquisition_time = DEID_TIME
    r.content_time = DEID_TIME if r.content_time else None
    r.diagnosis = []
    return r


# --------------------------------------------------------------------------- annotations
def _fiducial_positions(rec: EcgRecord, group_index: int):
    """Map the record's fiducials onto 1-based sample positions of the median group.

    Returns ``{}`` when the record has no median group, no fiducials, or when a
    position falls outside the group; the numeric measurements are written
    regardless, only the temporal range is omitted.
    """
    m = rec.measurements
    if group_index is None or not m.fiducials:
        return {}
    w = rec.waveforms[group_index - 1]
    n = min(len(v) for v in w.leads.values())
    src_fs = m.fiducial_sampling_frequency or w.sampling_frequency
    scale = w.sampling_frequency / src_fs if src_fs else 1.0
    out = {}
    for k, v in m.fiducials.items():
        try:
            pos = int(round(float(v) * scale)) + 1       # DICOM sample positions start at 1
        except (TypeError, ValueError):
            continue
        if 1 <= pos <= n:
            out[k] = pos
    return out


def _annotation(concept: codes.Code, ref, value=None, unit: codes.Code = None,
                segment=None, point=None) -> Dataset:
    a = Dataset()
    a.ConceptNameCodeSequence = Sequence([_code(concept)])
    a.ReferencedWaveformChannels = list(ref)
    if value is not None:
        a.NumericValue = _ds(value)
        a.MeasurementUnitsCodeSequence = Sequence([_code(unit)])
    if segment is not None:
        a.TemporalRangeType = 'SEGMENT'
        a.ReferencedSamplePositions = [int(segment[0]), int(segment[1])]
    elif point is not None:
        a.TemporalRangeType = 'POINT'
        a.ReferencedSamplePositions = [int(point)]
    return a


def build_annotations(rec: EcgRecord) -> Sequence:
    """Waveform Annotation Sequence for the global measurements and the P wave.

    Rates reference the rhythm group (they are counted on the strip); intervals,
    QTc and axes reference the median group when there is one (they are
    measured on the representative beat), otherwise the rhythm group. The PR,
    QRS and QT items also carry the interval as a SEGMENT of sample positions
    when the source supplies the fiducial points, and the P wave is written as
    a SEGMENT with its CID 3335 concept name.
    """
    m: Measurements = rec.measurements
    seq = Sequence()
    if not rec.waveforms:
        return seq
    rhythm = [1, 0]
    med_i = rec.median_group_index()
    beat = [med_i, 0] if med_i else rhythm
    fid = _fiducial_positions(rec, med_i)
    seg = lambda a, b: (fid[a], fid[b]) if a in fid and b in fid and fid[a] < fid[b] else None

    if m.ventricular_rate is not None:
        seq.append(_annotation(codes.VENTRICULAR_RATE, rhythm, m.ventricular_rate, codes.UNIT_BEATS_PER_MINUTE))
    if m.atrial_rate is not None:
        seq.append(_annotation(codes.ATRIAL_RATE, rhythm, m.atrial_rate, codes.UNIT_BEATS_PER_MINUTE))
    if m.pr_ms is not None:
        seq.append(_annotation(codes.PR_INTERVAL, beat, m.pr_ms, codes.UNIT_MILLISECOND, segment=seg('p_onset', 'qrs_onset')))
    if m.qrs_ms is not None:
        seq.append(_annotation(codes.QRS_DURATION, beat, m.qrs_ms, codes.UNIT_MILLISECOND, segment=seg('qrs_onset', 'qrs_offset')))
    if m.qt_ms is not None:
        seq.append(_annotation(codes.QT_INTERVAL, beat, m.qt_ms, codes.UNIT_MILLISECOND, segment=seg('qrs_onset', 't_offset')))
    if m.qtc_ms is not None:
        seq.append(_annotation(codes.QTC_INTERVAL, beat, m.qtc_ms, codes.UNIT_MILLISECOND))
    if m.p_axis_deg is not None:
        seq.append(_annotation(codes.P_AXIS, beat, m.p_axis_deg, codes.UNIT_DEGREE))
    if m.qrs_axis_deg is not None:
        seq.append(_annotation(codes.QRS_AXIS, beat, m.qrs_axis_deg, codes.UNIT_DEGREE))
    if m.t_axis_deg is not None:
        seq.append(_annotation(codes.T_AXIS, beat, m.t_axis_deg, codes.UNIT_DEGREE))
    p = seg('p_onset', 'p_offset')
    if p is not None:
        seq.append(_annotation(codes.P_WAVE, beat, segment=p))
    for text in rec.diagnosis:
        t = ' '.join(str(text).split())
        if t:
            a = Dataset()
            a.UnformattedTextValue = t[:1024]
            a.ReferencedWaveformChannels = rhythm
            seq.append(a)
    return seq


# --------------------------------------------------------------------------- waveform groups
def _waveform_item(w) -> Dataset:
    item = Dataset()
    item.WaveformOriginality = w.originality
    item.MultiplexGroupLabel = _lo(w.label, 16)
    n = min(len(v) for v in w.leads.values())
    item.NumberOfWaveformChannels = len(w.leads)
    item.NumberOfWaveformSamples = n
    item.SamplingFrequency = _ds(w.sampling_frequency)
    item.WaveformBitsAllocated = 16
    item.WaveformSampleInterpretation = 'SS'
    arr = np.stack([np.asarray(v[:n], dtype=np.int16) for v in w.leads.values()], axis=1)
    item.WaveformData = arr.tobytes()
    chans = []
    for lid in w.leads:
        c = Dataset()
        code = codes.CID_3001_ECG_LEAD.get(lid)
        if code is None:
            # A lead outside the standard twelve cannot be coded from CID 3001
            # in a way the General ECG IOD accepts; refuse rather than guess.
            raise ValueError(f'lead {lid!r} has no CID 3001 code; only the standard 12 leads are supported')
        c.ChannelSourceSequence = Sequence([_code(code)])
        c.ChannelSensitivity = '1'
        c.ChannelSensitivityUnitsSequence = Sequence([_code(codes.UNIT_MICROVOLT)])
        c.ChannelSensitivityCorrectionFactor = _ds(w.units_per_bit)
        c.ChannelBaseline = '0.0'
        c.ChannelSampleSkew = str(w.sample_skew or '0')
        c.WaveformBitsStored = 16
        if w.highpass_hz is not None:
            c.FilterLowFrequency = _ds(w.highpass_hz)       # lower edge of the pass band
        if w.lowpass_hz is not None:
            c.FilterHighFrequency = _ds(w.lowpass_hz)       # upper edge of the pass band
        if w.notch_hz is not None:
            c.NotchFilterFrequency = _ds(w.notch_hz)
        if lid in w.derived:
            c.ChannelDerivationDescription = 'Derived from leads I and II'
        chans.append(c)
    item.ChannelDefinitionSequence = Sequence(chans)
    return item


# --------------------------------------------------------------------------- the object
def build(rec: EcgRecord, *, index: int = 1, deidentify_record: bool = True,
          patient_id: Optional[str] = None, uid_root: str = codes.DEFAULT_UID_ROOT,
          study_description: Optional[str] = None) -> FileDataset:
    """Return the DICOM object for one record without writing it.

    ``index`` numbers the object within a conversion run (Instance Number,
    Series Number, and the default de-identified Patient ID). Building without
    writing lets a corpus be converted and validated in memory.
    """
    if not rec.waveforms:
        raise ValueError('no waveform groups in record')
    for w in rec.waveforms:
        if not w.leads:
            raise ValueError(f'waveform group {w.label} has no leads')
    if not rec.acquisition_date or len(rec.acquisition_date) != 8:
        raise ValueError('unparsable acquisition date; Type 1 (0008,0023)/(0008,002A) cannot be populated')

    if deidentify_record:
        rec = deidentify(rec, patient_id or f'{index:06d}')
    else:
        rec = copy.copy(rec)
        if patient_id:
            rec.patient_id = patient_id

    root = uid_root.rstrip('.')
    today = datetime.now().strftime('%Y%m%d')
    study_prefix = f'{root}.{today}.'          # Supplementary Table 4: [OID].[CURRENT DATE].
    series_prefix = study_prefix + '1.'
    instance_prefix = series_prefix + '1.'

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = codes.SOP_GENERAL_ECG
    fm.MediaStorageSOPInstanceUID = generate_uid(instance_prefix)
    fm.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset('', {}, file_meta=fm, preamble=b'\0' * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # SOP Common
    ds.SpecificCharacterSet = 'ISO_IR 192'
    ds.SOPClassUID = codes.SOP_GENERAL_ECG
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID

    # Patient / Patient Study
    ds.PatientName = _lo(rec.patient_name, 64) or ''
    ds.PatientID = _lo(rec.patient_id, 64) or ''
    ds.PatientSex = rec.sex if rec.sex in ('M', 'F', 'O') else ''
    ds.PatientBirthDate = rec.birth_date or ''
    if rec.ethnic_group:
        ds.EthnicGroup = _lo(rec.ethnic_group, 16)
    if rec.age_value is not None:
        ds.PatientAge = f'{min(int(rec.age_value), 999):03d}{rec.age_unit or "Y"}'

    # General Study
    ds.StudyInstanceUID = generate_uid(study_prefix)
    ds.StudyDate = rec.acquisition_date
    ds.StudyTime = rec.acquisition_time or DEID_TIME
    ds.ReferringPhysicianName = _lo(rec.referring_physician, 64) or ''
    ds.StudyID = _study_id()
    ds.AccessionNumber = ''
    ds.StudyDescription = _lo(study_description or rec.study_description or '12-Lead ECG', 64)

    # General Series
    ds.Modality = 'ECG'
    ds.SeriesInstanceUID = generate_uid(series_prefix)
    ds.SeriesNumber = str(index)
    if rec.operator:
        ds.OperatorsName = _lo(rec.operator, 64)

    # General Equipment
    ds.Manufacturer = _lo(rec.manufacturer, 64) or ''
    if rec.institution:
        ds.InstitutionName = _lo(rec.institution, 64)
    if rec.department:
        ds.InstitutionalDepartmentName = _lo(rec.department, 64)
    if rec.station:
        ds.StationName = _lo(rec.station, 16)
    if rec.model:
        ds.ManufacturerModelName = _lo(rec.model, 64)
    if rec.software_version:
        ds.SoftwareVersions = _lo(rec.software_version, 64)

    # Waveform Identification
    ds.InstanceNumber = str(index)
    ds.ContentDate = rec.content_date or rec.acquisition_date
    ds.ContentTime = rec.content_time or rec.acquisition_time or DEID_TIME
    ds.AcquisitionDateTime = rec.acquisition_date + (rec.acquisition_time or DEID_TIME)

    # Acquisition Context (TID 3401)
    lead_sys = Dataset()
    lead_sys.ValueType = 'CODE'
    lead_sys.ConceptNameCodeSequence = Sequence([_code(codes.LEAD_SYSTEM)])
    lead_sys.ConceptCodeSequence = Sequence([_code(codes.STANDARD_12_LEAD)])
    state = Dataset()
    state.ValueType = 'CODE'
    state.ConceptNameCodeSequence = Sequence([_code(codes.PATIENT_STATE)])
    state.ConceptCodeSequence = Sequence([_code(codes.RESTING_STATE)])
    ds.AcquisitionContextSequence = Sequence([lead_sys, state])

    # Waveform
    ds.WaveformSequence = Sequence([_waveform_item(w) for w in rec.waveforms])

    # Waveform Annotation (conditional module: present only when there is something to say)
    ann = build_annotations(rec)
    if len(ann):
        ds.WaveformAnnotationSequence = ann
    return ds


def write(rec: EcgRecord, out_path: str, **kwargs) -> str:
    ds = build(rec, **kwargs)
    ds.save_as(out_path, write_like_original=False)
    return out_path
