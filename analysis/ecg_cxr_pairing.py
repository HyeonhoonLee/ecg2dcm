# -*- coding: utf-8 -*-
"""How many ECG and chest radiograph studies can be paired once both are DICOM.

Counts, on MIMIC-IV-ECG 1.0 and MIMIC-CXR 2.0.0, how many chest radiograph
studies have an ECG within a given window of the same patient, and vice versa.
This quantifies what a shared Study/Series/SOP identifier hierarchy makes
retrievable in one query, using public data so that the figure is reproducible.

MIMIC shifts dates into the future per patient, and the same shift is applied
across MIMIC-IV modules, so within-patient time differences are preserved and
pairing on them is valid. Absolute dates are not.

Reads only the two metadata tables, never the waveforms or the images:
  MIMIC-IV-ECG 1.0   record_list.csv                  (subject_id, ecg_time)
  MIMIC-CXR 2.0.0    mimic-cxr-2.0.0-metadata.csv.gz  (subject_id, StudyDate/Time)

    uv run ecg_cxr_pairing.py
"""
import csv, gzip, os, bisect, collections
from datetime import datetime, timedelta

ECG = os.path.expanduser('~/Projects/Data/MIMIC-IV-2.2/physionet.org/files/mimic-iv-ecg/1.0/record_list.csv')
CXR = os.path.expanduser('~/Projects/Data/MIMIC-IV-2.2/mimic_iv_cxr/mimic-cxr-2.0.0-metadata.csv.gz')

ecg = collections.defaultdict(list)
n_ecg = 0
with open(ECG, newline='') as fh:
    for row in csv.DictReader(fh):
        t = row['ecg_time'].strip()
        if not t: continue
        ecg[row['subject_id']].append(datetime.strptime(t, '%Y-%m-%d %H:%M:%S'))
        n_ecg += 1
for k in ecg: ecg[k].sort()

cxr_studies = {}          # (subject, study_id) -> datetime
n_cxr_img = 0
with gzip.open(CXR, 'rt', newline='') as fh:
    for row in csv.DictReader(fh):
        n_cxr_img += 1
        d, t = row['StudyDate'].strip(), (row['StudyTime'] or '').strip()
        if not d: continue
        try:
            sec = t.split('.')[0].rjust(6, '0')[:6]
            dt = datetime.strptime(d + sec, '%Y%m%d%H%M%S')
        except ValueError:
            try: dt = datetime.strptime(d, '%Y%m%d')
            except ValueError: continue
        cxr_studies[(row['subject_id'], row['study_id'])] = dt

cxr = collections.defaultdict(list)
for (s, _st), dt in cxr_studies.items(): cxr[s].append(dt)
for k in cxr: cxr[k].sort()

print(f'  ECG 레코드 {n_ecg:,} / 환자 {len(ecg):,}')
print(f'  CXR 영상 {n_cxr_img:,} / 스터디 {len(cxr_studies):,} / 환자 {len(cxr):,}')
both = set(ecg) & set(cxr)
print(f'  두 modality 를 모두 가진 환자 {len(both):,}')
print()

def within(win):
    """윈도 안에서 짝지어지는 CXR 스터디 수, ECG 레코드 수, 쌍의 총수."""
    cxr_hit = ecg_hit = pairs = 0
    for s in both:
        es, cs = ecg[s], cxr[s]
        for c in cs:
            lo = bisect.bisect_left(es, c - win)
            hi = bisect.bisect_right(es, c + win)
            if hi > lo:
                cxr_hit += 1
                pairs += hi - lo
        for e in es:
            lo = bisect.bisect_left(cs, e - win)
            hi = bisect.bisect_right(cs, e + win)
            if hi > lo: ecg_hit += 1
    return cxr_hit, ecg_hit, pairs

print('  윈도별 페어링 (환자 내 시간 근접):')
print(f'    {"윈도":<10}{"CXR 스터디":>12}{"ECG 레코드":>12}{"쌍":>14}')
for label, win in [('±1시간', timedelta(hours=1)), ('±6시간', timedelta(hours=6)),
                   ('±24시간', timedelta(hours=24)), ('±7일', timedelta(days=7)),
                   ('±30일', timedelta(days=30))]:
    c, e, p = within(win)
    print(f'    {label:<10}{c:>12,}{e:>12,}{p:>14,}')
