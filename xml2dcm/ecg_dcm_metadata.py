from datetime import datetime
from dataclasses import dataclass, field
from pydicom.uid import generate_uid
from enum import Enum


ANONYMOUS = 'Anonymized'


@dataclass
class PreFix:
    DCM_UID: str = '1.2.840.10008.1.2.1'
    TWELVE_LEAD_ECG_SOP_CLASS_UID: str = '1.2.840.10008.5.1.4.1.1.9.1.1'
    Manufacturer: str = 'GE Healthcare'
    StudyDescription: str = '12-Lead ECG'
    Modality: str = 'ECG'
    specific_character_set: str = "ISO_IR 100"


@dataclass
class ECGData:
    sampling_frequency: int = 500 # SampleBase
    sequence_length_in_seconds: int = 10
    num_waveform_samples: int = 0
    num_waveform_channels: int = 0
    waveform_channel_count: int = 0
    expected_leads: list = field(default_factory=lambda: ['I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6'])
    derived_leads: list = field(default_factory=lambda: ['III', 'aVR', 'aVL', 'aVF'])
    lowpass_filter: str = 20.0 # LowPassFilter
    highpass_filter: str = 8.0 # HighPassFilter
    lead_time_offset: int = 0
    amp_units_per_bit: float = 4.88


# FIX: DICOM PS3.16 CID 3001 "ECG Lead" (ISO/IEEE 11073-10101, designator MDC)
CID_3001_ECG_LEAD = {
    'I':   ('2:1',  'Lead I'),
    'II':  ('2:2',  'Lead II'),
    'III': ('2:61', 'Lead III'),
    'aVR': ('2:62', 'aVR, augmented voltage, right'),
    'aVL': ('2:63', 'aVL, augmented voltage, left'),
    'aVF': ('2:64', 'aVF, augmented voltage, foot'),
    'V1':  ('2:3',  'Lead V1'),
    'V2':  ('2:4',  'Lead V2'),
    'V3':  ('2:5',  'Lead V3'),
    'V4':  ('2:6',  'Lead V4'),
    'V5':  ('2:7',  'Lead V5'),
    'V6':  ('2:8',  'Lead V6'),
}


@dataclass
class ChannelSourceSequence:
    code_value: str = '2:1'
    scheme_designator: str = 'MDC'
    code_meaning: str = 'Lead I'


@dataclass
class ChannelSensitivityUnitsSequence:
    code_value: str = 'uV'
    code_meaning: str = 'microvolt'
    scheme_designator: str = 'UCUM'


@dataclass
class ChannelDefinitionSequence:
    source_sequence: ChannelSourceSequence = field(default_factory=ChannelSourceSequence)
    sensitivity_units_sequence: ChannelSensitivityUnitsSequence = field(default_factory=ChannelSensitivityUnitsSequence)

    sensitivity: int = 1
    skew: str = "0"
    bits_stored: int = 16
    sensitivity_correction_factor: int = 4.88
    lowpass_filter: str = 20.0  # LowPassFilter
    highpass_filter: str = 8.0  # HighPassFilter
    notch_filter: str = None  # FIX: ACFilter -> (003A,0222) Notch Filter Frequency
    channel_baseline = "0.0"


@dataclass
class WaveformSequence:
    originality: str = 'ORIGINAL'
    num_channels: int = 12
    num_samples: int = 5000
    sampling_frequency: int = 500
    bits_allocated: int = 16
    sample_interpretation: str = 'SS'
    multiplex_group_label: str = 'whole'


@dataclass
class MeasurementUnitsCodeSequence:
    # (0040,08EA)
    code_value: str or None = None
    code_meaning: str or None = None
    scheme_designator: str or None = None


@dataclass
class ConceptNameCodeSequence:
    # (0040,A043)
    code_value: str or None = None
    code_meaning: str or None = None
    scheme_designator: str or None = None


@dataclass
class WaveformAnnotationSequence:
    measurement_units_code_sequence: MeasurementUnitsCodeSequence = field(default_factory=MeasurementUnitsCodeSequence)
    concept_name_code_sequence: ConceptNameCodeSequence = field(default_factory=ConceptNameCodeSequence)
    numeric_value: str = None
    referenced_waveform_channels = [1, 0]


@dataclass
class UID:
    # The UID root under which this pipeline issues Study, Series and SOP Instance UIDs.
    # It must belong to the organisation running the conversion. Version 1.1.10 issued
    # them under 1.2.840.113619, which is GE HealthCare's registered OID, so the objects
    # claimed an origin that was not theirs and could collide with UIDs GE itself issued.
    # The value below is pydicom's default root, used here as a neutral placeholder:
    # replace it with your institution's own registered OID before production use.
    uid_root: str = '1.2.826.0.1.3680043.8.498'
    twelve_lead_ecg_sop_class: str = '1.2.840.10008.5.1.4.1.1.9.1.1'

    current_date = datetime.now().strftime('%Y%m%d')

    study_class_uid = uid_root + '.' + current_date + '.'
    series_class_uid = study_class_uid + '1.'
    instance_class_uid = series_class_uid + '1.'

    study_instance = generate_uid(study_class_uid)
    series_instance = generate_uid(series_class_uid)
    instance_instance = generate_uid(instance_class_uid)


@dataclass
class PatientData:
    id: str = 'Anonymized'
    name: str = 'Anonymized'
    age: str = '000Y'
    sex: str = 'M'
    birth_date: str = '' # Type 2: if not provided, empty string
    race: str = 'Anonymized'


@dataclass
class TestData:
    datatype: str = 'RESTING'
    site: str = 'UNKNOWN'
    acquisition_date: str = '00000000'
    acquisition_time: str = '000000'
    study_date: str = '00000000'
    study_time: str = '000000'
    study_id: str = '0000000000000000'

    # Tag: 	(0008,0050)
    accession_number: str = '' # Type 2: if not provided, empty string

    content_date: str = '00000000'
    content_time: str = '000000'
    # Tag: (0008, 1090)
    manufacture_model_name: str = 'UNKNOWN'
    # Tag: (0018, 1020)
    software_version: str = 'UNKNOWN'
    # Tag: (0008, 0080)
    institution_name: str = 'UNKNOWN'
    # Tag: (0008, 1010)
    station_name: str = 'UNKNOWN'
    # Tag: 	(0008, 1040)
    institutional_department_name: str = 'UNKNOWN'

    # Tag: (0008, 1070)
    operator_name: str = 'UNKNOWN'
    # Tag: (0008, 1060)
    physician_name: str = 'UNKNOWN'
    # Tag: (0008, 0090)
    referring_physician_name: str = 'UNKNOWN'


@dataclass
class DiagnosisData:
    diagnosis: str = ''


@dataclass
class DeIdentification:
    name: str = 'Anonymized'
    place: str = 'Anonymized'
    date: str = '000000'
    time: str = '000000'


class Measurement(Enum):
    # (code value, code_meaning, scheme_designator)
    VentricularRate = ('2:16016', 'Ventricular Heart Rate', 'MDC')
    AtrialRate = ('2:16020', 'Atrial Heart Rate', 'MDC')
    PRInterval = ('2:15872', 'PR interval global', 'MDC')
    QRSDuration = ('2:16156', 'QRS duration global', 'MDC')
    QTInterval = ('2:16160', 'QT interval global', 'MDC')
    QTCorrected = ('2:15876', 'QTc interval global', 'MDC')

    PAxis = ('8626-4', 'P wave axis', 'LN')
    RAxis = ('9997-8', 'R wave axis', 'LN')
    TAxis = ('8638-9', 'T wave axis', 'LN')

    POnset = ('18511-6', 'P wave onset', 'LN')
    POffset = ('18512-4', 'P wave offset', 'LN')
    TOffset = ('18515-7', 'T wave offset', 'LN')

    # QTcFrederica = ('QTcFrederica', 'milliseconds', 'ms', 'UCUM')
    # QRSCount = ('QRSCount', None, None, None)
    # QOnset = ('QOnset', None, None, None)
    # QOffset = ('QOffset', None, None, None)


class MeasurementUnit(Enum):
    # (xml attribute name, code value, code_meaning, scheme_designator)
    # FIX: UCUM code value must be the case-sensitive UCUM symbol; the human-readable
    # form belongs in code meaning. The two were previously swapped.
    VentricularRate = ('VentricularRate', '/min', 'beats per minute', 'UCUM')
    AtrialRate = ('AtrialRate', '/min', 'beats per minute', 'UCUM')
    PRInterval = ('PRInterval', 'ms', 'milliseconds', 'UCUM')
    QRSDuration = ('QRSDuration', 'ms', 'milliseconds', 'UCUM')
    QTInterval = ('QTInterval', 'ms', 'milliseconds', 'UCUM')
    QTCorrected = ('QTCorrected', 'ms', 'milliseconds', 'UCUM')

    PAxis = ('PAxis', 'deg', 'degrees', 'UCUM')
    RAxis = ('RAxis', 'deg', 'degrees', 'UCUM')
    TAxis = ('TAxis', 'deg', 'degrees', 'UCUM')

    POnset = ('POnset', 'ms', 'milliseconds', 'UCUM')
    POffset = ('POffset', 'ms', 'milliseconds', 'UCUM')
    TOffset = ('TOffset', 'ms', 'milliseconds', 'UCUM')

    # QTcFrederica = ('QTcFrederica', 'milliseconds', 'ms', 'UCUM')
    # QRSCount = ('QRSCount', None, None, None)
    # QOnset = ('QOnset', None, None, None)
    # QOffset = ('QOffset', None, None, None)