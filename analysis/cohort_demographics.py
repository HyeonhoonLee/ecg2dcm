#!/usr/bin/env python3
"""Supplementary Table 7: demographics of the analyzed cohort, from the export archive.

Reads only the header of each XML entry (the demographics sit before the
waveform payload), windows on the acquisition month, and prints aggregate
counts. Sex and race are counted per patient (first record seen decides), age
is summarized per record and per patient, location per record. No identifier
is written anywhere.

    uv run cohort_demographics.py --zip export.zip --since 2010-01 --until 2020-12
"""
import argparse, collections, json, statistics, sys, zipfile


def field(head, tag):
    a = head.find('<' + tag + '>')
    if a < 0:
        return None
    b = head.find('</' + tag + '>', a)
    v = head[a + len(tag) + 2:b].strip() if b > 0 else ''
    return v or None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--zip', dest='zip_path', required=True)
    ap.add_argument('--since', metavar='YYYY-MM'); ap.add_argument('--until', metavar='YYYY-MM')
    ap.add_argument('--head-bytes', type=int, default=16384)
    ap.add_argument('--out', default='cohort_demographics.json')
    a = ap.parse_args()
    since = a.since.replace('-', '') if a.since else None
    until = a.until.replace('-', '') if a.until else None

    n = 0; skipped = 0
    sex_by_patient = {}; race_by_patient = {}; age_by_patient = {}
    ages = []; loc = collections.Counter(); sex_rec = collections.Counter()
    with zipfile.ZipFile(a.zip_path) as z:
        names = [x for x in z.namelist() if x.lower().endswith('.xml')]
        for i, name in enumerate(names):
            with z.open(name) as fh:
                head = fh.read(a.head_bytes).decode('utf-8', 'replace')
            d = field(head, 'AcquisitionDate') or ''
            p = d.split('-')
            ym = f'{p[2]}{p[0]}' if len(p) == 3 and all(x.isdigit() for x in p) else ''
            if len(ym) != 6 or (since and ym < since) or (until and ym > until):
                skipped += 1
                continue
            n += 1
            pid = field(head, 'PatientID') or f'(none){i}'
            sex = (field(head, 'Gender') or 'Unknown').upper()
            race = field(head, 'Race') or 'Unknown'
            age = field(head, 'PatientAge'); units = (field(head, 'AgeUnits') or 'YEARS').upper()
            try:
                age_y = float(age) / ({'YEARS': 1, 'MONTHS': 12, 'WEEKS': 52.18, 'DAYS': 365.25}[units])
            except (TypeError, ValueError, KeyError):
                age_y = None
            sex_rec[sex] += 1
            sex_by_patient.setdefault(pid, sex); race_by_patient.setdefault(pid, race)
            if age_y is not None:
                ages.append(age_y); age_by_patient.setdefault(pid, age_y)
            loc[field(head, 'LocationName') or '(none)'] += 1
            if (i + 1) % 100000 == 0:
                print(f'  ... {i+1}', file=sys.stderr)
    pat = len(sex_by_patient)
    out = {
        'records': n, 'skipped_outside_window': skipped, 'patients': pat,
        'sex_per_patient': dict(collections.Counter(sex_by_patient.values())),
        'sex_per_record': dict(sex_rec),
        'race_per_patient': dict(collections.Counter(race_by_patient.values())),
        'age_per_record': {'n': len(ages), 'mean': statistics.fmean(ages), 'sd': statistics.pstdev(ages)} if ages else None,
        'age_per_patient': {'n': len(age_by_patient), 'mean': statistics.fmean(age_by_patient.values()), 'sd': statistics.pstdev(list(age_by_patient.values()))} if age_by_patient else None,
        'location_per_record': dict(loc.most_common()),
    }
    json.dump(out, open(a.out, 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in out.items() if k != 'location_per_record'}, indent=1, ensure_ascii=False))
    print('top locations:', loc.most_common(8))


if __name__ == '__main__':
    main()
