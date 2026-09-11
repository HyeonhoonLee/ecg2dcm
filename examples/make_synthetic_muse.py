#!/usr/bin/env python3
"""Write a synthetic GE MUSE RestingECG XML file for testing and demonstration.

The document follows the element layout of a MUSE XML export (patient and test
demographics, resting measurements with fiducial points in samples, a rhythm
and a median waveform block with base64 int16 samples), but every value is
invented: the waveform is a sum of Gaussian P, QRS and T deflections at 72
beats per minute, and the demographics are placeholders. Nothing in it comes
from a patient.

    python make_synthetic_muse.py synthetic_muse.xml
"""
import base64
import sys

import numpy as np

FS = 500
RHYTHM_SAMPLES = 5000        # 10 s
MEDIAN_SAMPLES = 600         # 1.2 s
UPB = 4.88                   # microvolts per LSB, as MUSE writes it
BPM = 72

# beat template: (centre in ms from beat start, width in ms, amplitude in microvolts) per lead
_LEADS = ['I', 'II', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6']
_AMP = {  # P, Q, R, S, T amplitudes in microvolts
    'I':  (80,  -40, 700, -120, 250), 'II': (120, -60, 1200, -200, 350),
    'V1': (40,  0,   300, -900, -100), 'V2': (60,  0,   800, -1400, 400),
    'V3': (60,  -30, 1200, -900, 500), 'V4': (70,  -60, 1600, -500, 450),
    'V5': (70,  -80, 1400, -300, 400), 'V6': (60,  -70, 1000, -200, 300),
}
_POS = (80, 190, 210, 232, 400)       # centres in ms: P, Q, R, S, T
_WID = (25, 6, 8, 8, 40)              # widths in ms
P_ON, P_OFF, Q_ON, Q_OFF, T_OFF = 147, 188, 219, 262, 420   # fiducials in samples of the median


def beat(lead, n, fs=FS, offset_ms=0.0):
    t = np.arange(n) * 1000.0 / fs - offset_ms
    y = np.zeros(n)
    for a, c, w in zip(_AMP[lead], _POS, _WID):
        y += a * np.exp(-0.5 * ((t - c) / w) ** 2)
    return y


def rhythm(lead):
    period = 60000.0 / BPM
    y = np.zeros(RHYTHM_SAMPLES)
    t0 = -100.0
    while t0 < RHYTHM_SAMPLES * 1000.0 / FS:
        y += beat(lead, RHYTHM_SAMPLES, offset_ms=t0)
        t0 += period
    y += 15 * np.sin(2 * np.pi * 0.2 * np.arange(RHYTHM_SAMPLES) / FS)     # slow baseline wander
    return y


def b64(y_uv):
    return base64.b64encode(np.round(y_uv / UPB).astype('<i2').tobytes()).decode('ascii')


def lead_block(lead, samples):
    return f'''    <LeadData>
      <LeadByteCountTotal>{2 * len(samples)}</LeadByteCountTotal>
      <LeadTimeOffset>0</LeadTimeOffset>
      <LeadSampleCountTotal>{len(samples)}</LeadSampleCountTotal>
      <LeadAmplitudeUnitsPerBit>{UPB}</LeadAmplitudeUnitsPerBit>
      <LeadAmplitudeUnits>MICROVOLTS</LeadAmplitudeUnits>
      <LeadHighLimit>32767</LeadHighLimit>
      <LeadLowLimit>-32768</LeadLowLimit>
      <LeadID>{lead}</LeadID>
      <LeadOffsetFirstSample>0</LeadOffsetFirstSample>
      <FirstSampleBaseline>0</FirstSampleBaseline>
      <LeadSampleSize>2</LeadSampleSize>
      <LeadOff>FALSE</LeadOff>
      <BaselineSway>FALSE</BaselineSway>
      <LeadDataCRC32>0</LeadDataCRC32>
      <WaveFormData>{b64(samples)}</WaveFormData>
    </LeadData>
'''


def waveform_block(kind, n):
    make = rhythm if kind == 'Rhythm' else (lambda lead: beat(lead, n))
    body = ''.join(lead_block(lead, make(lead)) for lead in _LEADS)
    return f'''  <Waveform>
    <WaveformType>{kind}</WaveformType>
    <WaveformStartTime>0</WaveformStartTime>
    <NumberofLeads>{len(_LEADS)}</NumberofLeads>
    <SampleType>CONTINUOUS_SAMPLES</SampleType>
    <SampleBase>{FS}</SampleBase>
    <SampleExponent>0</SampleExponent>
    <HighPassFilter>56</HighPassFilter>
    <LowPassFilter>150</LowPassFilter>
    <ACFilter>60</ACFilter>
{body}  </Waveform>
'''


def document():
    pr = round((Q_ON - P_ON) * 1000 / FS)
    qrs = round((Q_OFF - Q_ON) * 1000 / FS)
    qt = round((T_OFF - Q_ON) * 1000 / FS)
    rr = 60000 / BPM
    qtc = round(qt / (rr / 1000) ** 0.5)
    return f'''<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE RestingECG SYSTEM "restecg.dtd">
<RestingECG>
  <MuseInfo>
    <MuseVersion>9.0.10.18530</MuseVersion>
  </MuseInfo>
  <PatientDemographics>
    <PatientID>SYNTH0001</PatientID>
    <PatientAge>45</PatientAge>
    <AgeUnits>YEARS</AgeUnits>
    <DateofBirth>01-01-1980</DateofBirth>
    <Gender>MALE</Gender>
    <Race>UNKNOWN</Race>
    <PatientLastName>Synthetic</PatientLastName>
    <PatientFirstName>Example</PatientFirstName>
  </PatientDemographics>
  <TestDemographics>
    <DataType>RESTING</DataType>
    <Site>1</Site>
    <SiteName>EXAMPLE HOSPITAL</SiteName>
    <AcquisitionDevice>MAC55</AcquisitionDevice>
    <Status>CONFIRMED</Status>
    <EditListStatus>NONE</EditListStatus>
    <Priority>NORMAL</Priority>
    <Location>1</Location>
    <LocationName>EXAMPLE ECG ROOM</LocationName>
    <RoomID>ROOM1</RoomID>
    <AcquisitionTime>09:15:11</AcquisitionTime>
    <AcquisitionDate>08-17-2025</AcquisitionDate>
    <CartNumber>1</CartNumber>
    <AcquisitionSoftwareVersion>1.02 SP05</AcquisitionSoftwareVersion>
    <AnalysisSoftwareVersion>243</AnalysisSoftwareVersion>
    <EditDate>08-17-2025</EditDate>
    <EditTime>09:34:21</EditTime>
    <OverreaderLastName>Reader</OverreaderLastName>
    <OverreaderFirstName>Example</OverreaderFirstName>
    <AcquisitionTechLastName>Tech</AcquisitionTechLastName>
    <AcquisitionTechFirstName>Example</AcquisitionTechFirstName>
    <XMLSourceVersion>MUSE_9.0.10.18530</XMLSourceVersion>
  </TestDemographics>
  <RestingECGMeasurements>
    <VentricularRate>{BPM}</VentricularRate>
    <AtrialRate>{BPM}</AtrialRate>
    <PRInterval>{pr}</PRInterval>
    <QRSDuration>{qrs}</QRSDuration>
    <QTInterval>{qt}</QTInterval>
    <QTCorrected>{qtc}</QTCorrected>
    <PAxis>60</PAxis>
    <RAxis>45</RAxis>
    <TAxis>40</TAxis>
    <QRSCount>12</QRSCount>
    <QOnset>{Q_ON}</QOnset>
    <QOffset>{Q_OFF}</QOffset>
    <POnset>{P_ON}</POnset>
    <POffset>{P_OFF}</POffset>
    <TOffset>{T_OFF}</TOffset>
    <ECGSampleBase>{FS}</ECGSampleBase>
    <ECGSampleExponent>0</ECGSampleExponent>
  </RestingECGMeasurements>
  <Diagnosis>
    <Modality>RESTING</Modality>
    <DiagnosisStatement>
      <StmtFlag>ENDSLINE</StmtFlag>
      <StmtText>Sinus rhythm (synthetic example)</StmtText>
    </DiagnosisStatement>
  </Diagnosis>
{waveform_block('Median', MEDIAN_SAMPLES)}{waveform_block('Rhythm', RHYTHM_SAMPLES)}</RestingECG>
'''


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'synthetic_muse.xml'
    with open(out, 'w', encoding='iso-8859-1') as fh:
        fh.write(document())
    print(f'wrote {out}')
