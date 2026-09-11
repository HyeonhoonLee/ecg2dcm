"""Every coded value the writer emits, with the context group or template that governs it.

This module is the machine-readable form of Supplementary Table 8 of the
manuscript; ``docs/mapping/coded_values.csv`` is generated from it.

Coding scheme designators follow PS3.16 Section 8: ``MDC`` for ISO/IEEE
11073-10101/-10102, ``UCUM`` for units, ``DCM`` for DICOM controlled
terminology, ``SCT`` for SNOMED CT.
"""
from collections import namedtuple

Code = namedtuple('Code', 'value scheme meaning')

# SOP Classes (PS3.4 Table B.5-1)
SOP_GENERAL_ECG = '1.2.840.10008.5.1.4.1.1.9.1.2'      # General ECG Waveform Storage
SOP_TWELVE_LEAD_ECG = '1.2.840.10008.5.1.4.1.1.9.1.1'  # 12-Lead ECG Waveform Storage

# The root under which Study, Series and SOP Instance UIDs are issued. This is
# pydicom's registered root, whose use it permits; it is a placeholder for an
# organisation that has not yet registered its own OID. Pass ``--uid-root`` to
# the command-line tools, or ``uid_root=`` to :func:`ecg2dcm.writer.build`, to
# issue UIDs under your own root.
DEFAULT_UID_ROOT = '1.2.826.0.1.3680043.8.498'

# CID 3001 "ECG Lead" (ISO/IEEE 11073-10101). Defined context group for
# Channel Source Sequence in the General ECG IOD (PS3.3 A.34.4.4.5).
CID_3001_ECG_LEAD = {
    'I':   Code('2:1',  'MDC', 'Lead I'),
    'II':  Code('2:2',  'MDC', 'Lead II'),
    'III': Code('2:61', 'MDC', 'Lead III'),
    'aVR': Code('2:62', 'MDC', 'aVR, augmented voltage, right'),
    'aVL': Code('2:63', 'MDC', 'aVL, augmented voltage, left'),
    'aVF': Code('2:64', 'MDC', 'aVF, augmented voltage, foot'),
    'V1':  Code('2:3',  'MDC', 'Lead V1'),
    'V2':  Code('2:4',  'MDC', 'Lead V2'),
    'V3':  Code('2:5',  'MDC', 'Lead V3'),
    'V4':  Code('2:6',  'MDC', 'Lead V4'),
    'V5':  Code('2:7',  'MDC', 'Lead V5'),
    'V6':  Code('2:8',  'MDC', 'Lead V6'),
}
# Every code value of CID 3001 (DICOM PS3.16 2024b), for the conformance check.
CID_3001_CODE_VALUES = frozenset(
    ['2:%d' % n for n in range(0, 39)] + ['2:%d' % n for n in range(61, 79)]
    + ['2:%d' % n for n in range(86, 115)] + ['2:%d' % n for n in range(121, 135)]
    + ['2:%d' % n for n in range(147, 152)])

# CID 82 "Measurement Unit": the case-sensitive codes of UCUM.
UNIT_MICROVOLT = Code('uV', 'UCUM', 'microvolt')
UNIT_MILLIVOLT = Code('mV', 'UCUM', 'millivolt')
UNIT_MILLISECOND = Code('ms', 'UCUM', 'millisecond')
UNIT_DEGREE = Code('deg', 'UCUM', 'degree')
UNIT_BEATS_PER_MINUTE = Code('{H.B.}/min', 'UCUM', 'heart beats per minute')   # as in TID 3713

# TID 3401 "ECG Acquisition Context"
LEAD_SYSTEM = Code('10:11345', 'MDC', 'Lead System')                              # concept name
STANDARD_12_LEAD = Code('10:11265', 'MDC',
                        'Standard 12-lead positions, electrodes placed individually')  # CID 3263
PATIENT_STATE = Code('109054', 'DCM', 'Patient State')                            # concept name
RESTING_STATE = Code('128975004', 'SCT', 'Resting State')                          # CID 3262

# Global measurements: concept names from TID 3713 "ECG Global Measurements".
VENTRICULAR_RATE = Code('2:16016', 'MDC', 'Ventricular Heart Rate')   # TID 3713
ATRIAL_RATE = Code('2:16020', 'MDC', 'Atrial Heart Rate')             # TID 3713
PR_INTERVAL = Code('2:15872', 'MDC', 'PR interval global')            # TID 3713; CID 3228, CID 3689
QRS_DURATION = Code('2:16156', 'MDC', 'QRS duration global')          # TID 3713; CID 3228, CID 3689
QT_INTERVAL = Code('2:16160', 'MDC', 'QT interval global')            # TID 3713; CID 3689
QTC_INTERVAL = Code('2:15876', 'MDC', 'QTc interval global')          # TID 3713; CID 3227
P_AXIS = Code('2:16128', 'MDC', 'P Axis')                             # CID 3229 (TID 3713 row 12)
QRS_AXIS = Code('2:16132', 'MDC', 'QRS axis')                         # CID 3229
T_AXIS = Code('2:16136', 'MDC', 'T axis')                             # CID 3229
# Waveform component, for the P wave segment: CID 3335 "ECG Annotation".
P_WAVE = Code('10:256', 'MDC', 'P wave')                              # CID 3335

# (attribute, concept, unit, governing context group or template, source field)
CODED_VALUES = [
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['I'], None, 'CID 3001 ECG Lead (DCID, PS3.3 A.34.4.4.5)', 'lead I'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['II'], None, 'CID 3001', 'lead II'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['III'], None, 'CID 3001', 'lead III'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['aVR'], None, 'CID 3001', 'lead aVR'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['aVL'], None, 'CID 3001', 'lead aVL'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['aVF'], None, 'CID 3001', 'lead aVF'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['V1'], None, 'CID 3001', 'lead V1'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['V2'], None, 'CID 3001', 'lead V2'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['V3'], None, 'CID 3001', 'lead V3'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['V4'], None, 'CID 3001', 'lead V4'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['V5'], None, 'CID 3001', 'lead V5'),
    ('Channel Source Sequence (003A,0208)', CID_3001_ECG_LEAD['V6'], None, 'CID 3001', 'lead V6'),
    ('Channel Sensitivity Units Sequence (003A,0211)', UNIT_MICROVOLT, None, 'CID 82 Measurement Unit', 'amplitude units'),
    ('Acquisition Context, concept name', LEAD_SYSTEM, None, 'TID 3401', 'constant'),
    ('Acquisition Context, concept value', STANDARD_12_LEAD, None, 'CID 3263 Electrode Placement Values', 'constant'),
    ('Acquisition Context, concept name', PATIENT_STATE, None, 'TID 3401', 'constant'),
    ('Acquisition Context, concept value', RESTING_STATE, None, 'CID 3262 ECG Patient State Values', 'constant'),
    ('Waveform Annotation, concept name', VENTRICULAR_RATE, UNIT_BEATS_PER_MINUTE, 'TID 3713 ECG Global Measurements', 'ventricular rate'),
    ('Waveform Annotation, concept name', ATRIAL_RATE, UNIT_BEATS_PER_MINUTE, 'TID 3713', 'atrial rate'),
    ('Waveform Annotation, concept name', PR_INTERVAL, UNIT_MILLISECOND, 'TID 3713; CID 3689 ECG Global Waveform Duration', 'PR interval; segment P onset to QRS onset'),
    ('Waveform Annotation, concept name', QRS_DURATION, UNIT_MILLISECOND, 'TID 3713; CID 3689', 'QRS duration; segment QRS onset to QRS offset'),
    ('Waveform Annotation, concept name', QT_INTERVAL, UNIT_MILLISECOND, 'TID 3713; CID 3689', 'QT interval; segment QRS onset to T offset'),
    ('Waveform Annotation, concept name', QTC_INTERVAL, UNIT_MILLISECOND, 'TID 3713; CID 3227 QTc Measurements', 'corrected QT'),
    ('Waveform Annotation, concept name', P_AXIS, UNIT_DEGREE, 'CID 3229 ECG Axis Measurement (TID 3713 row 12)', 'P axis'),
    ('Waveform Annotation, concept name', QRS_AXIS, UNIT_DEGREE, 'CID 3229', 'QRS (R) axis'),
    ('Waveform Annotation, concept name', T_AXIS, UNIT_DEGREE, 'CID 3229', 'T axis'),
    ('Waveform Annotation, concept name', P_WAVE, None, 'CID 3335 ECG Annotation', 'segment P onset to P offset'),
    ('Waveform Annotation, measurement units', UNIT_BEATS_PER_MINUTE, None, 'CID 82', 'rates'),
    ('Waveform Annotation, measurement units', UNIT_MILLISECOND, None, 'CID 82', 'intervals'),
    ('Waveform Annotation, measurement units', UNIT_DEGREE, None, 'CID 82', 'axes'),
]
