"""Attribute coverage of the five WFDB datasets, counted over every header.

Supplementary Table 10 reports, per source, whether each DICOM attribute can be
populated. For WFDB the answer is fixed by what the header carries, so this
counts headers rather than writing 871,397 DICOM objects: a base date (or, for
PTB-XL, a recording_date in ptbxl_database.csv) is what Study Date, Content
Date and Acquisition DateTime come from; '#age'/'#sex' comment lines are what
Patient's Age and Patient's Sex come from. The same header reader and the same
comment parsing as adapters/wfdb.py are used, so the counts are what the
adapter would populate. Output is aggregate only.
"""
import argparse, csv, glob, json, os, sys
import multiprocessing as mp
from pathlib import Path

from ecg2dcm.adapters import wfdb  # noqa: E402


def one(hea):
    try:
        name, fs, nsamp, signals, comments, base_date, base_time = wfdb._read_header(hea)
    except Exception as e:
        return {'err': 1, 'errmsg': f'{type(e).__name__}: {str(e)[:60]}'}
    sex = age = False
    for c in comments:
        key, _, val = c.partition(':')
        key = key.strip().strip('<>').lower(); val = val.strip()
        if key == 'age' and val.replace('.', '', 1).isdigit():
            age = True
        elif key == 'sex' and val.upper() in ('M', 'MALE', 'F', 'FEMALE'):
            sex = True
    return {'err': 0, 'date': int(bool(base_date)), 'time': int(bool(base_time)),
            'sex': int(sex), 'age': int(age), 'name': name}


def chunk(heas):
    tot = {'n': 0, 'err': 0, 'date': 0, 'time': 0, 'sex': 0, 'age': 0, 'errs': {}}
    names = []
    for h in heas:
        r = one(h); tot['n'] += 1
        if r['err']:
            tot['err'] += 1; tot['errs'][r['errmsg']] = tot['errs'].get(r['errmsg'], 0) + 1
            continue
        for k in ('date', 'time', 'sex', 'age'):
            tot[k] += r[k]
        names.append(r['name'])
    tot['names'] = names
    return tot


def merge(a, b):
    out = dict(a)
    for k in ('n', 'err', 'date', 'time', 'sex', 'age'):
        out[k] = a[k] + b[k]
    out['errs'] = dict(a['errs'])
    for k, v in b['errs'].items():
        out['errs'][k] = out['errs'].get(k, 0) + v
    out['names'] = a['names'] + b['names']
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=os.path.expanduser('~/Projects/Data/ECG/physionet.org/files'))
    ap.add_argument('--mimic', default=os.path.expanduser('~/Projects/Data/MIMIC-IV-2.2/physionet.org/files/mimic-iv-ecg/1.0'))
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--out', default='wfdb_header_coverage.json')
    a = ap.parse_args()

    datasets = [
        ('PTB-XL', os.path.join(a.root, 'ptb-xl', '1.0.3', 'records500')),
        ('ECGDMMLD', os.path.join(a.root, 'ecgdmmld', '1.0.0', 'raw')),
        ('Chapman-Shaoxing and Ningbo', os.path.join(a.root, 'ecg-arrhythmia', '1.0.0')),
        ('LUDB', os.path.join(a.root, 'ludb', '1.0.1', 'data')),
        ('MIMIC-IV-ECG', os.path.join(a.mimic, 'files')),
    ]
    # PTB-XL keeps the acquisition instant in a sidecar table, not the header.
    ptb_dates = set()
    p = Path(a.root, 'ptb-xl', '1.0.3', 'ptbxl_database.csv')
    if p.exists():
        with open(p, newline='', encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                if (row.get('recording_date') or '').strip():
                    ptb_dates.add(os.path.basename(row['filename_hr']))

    results = []
    ctx = mp.get_context('spawn')
    for label, d in datasets:
        heas = sorted(glob.glob(os.path.join(d, '**', '*.hea'), recursive=True))
        if not heas:
            print(f'  {label}: no headers under {d}', file=sys.stderr); continue
        print(f'  {label}: {len(heas)} headers', file=sys.stderr)
        size = (len(heas) + a.workers - 1) // a.workers
        parts = [heas[i:i + size] for i in range(0, len(heas), size)]
        if a.workers > 1 and len(parts) > 1:
            with ctx.Pool(a.workers) as pool:
                tots = pool.map(chunk, parts)
        else:
            tots = [chunk(heas)]
        t = tots[0]
        for q in tots[1:]:
            t = merge(t, q)
        if label == 'PTB-XL':
            t['date_sidecar'] = sum(1 for n in t['names'] if n in ptb_dates)
        del t['names']
        t['dataset'] = label
        results.append(t)
        print(f'    n={t["n"]} header_err={t["err"]} date={t["date"]} time={t["time"]} '
              f'sex={t["sex"]} age={t["age"]}' + (f' date_sidecar={t.get("date_sidecar")}' if 'date_sidecar' in t else ''),
              file=sys.stderr)
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f'wrote {a.out}')


if __name__ == '__main__':
    main()
