#!/usr/bin/env python3
"""Supplementary Table 9, part 2: conversion success and required attribute
completeness, stratified by acquisition device model and software version.

Run this on the institution's own GE MUSE XML export, after
supp_table9_device_profile.py has produced the device and software profile.

Every record is converted in memory and validated in memory; nothing is written
to disk except the aggregate tables below. A rhythm multiplex group alone is
about 120 kB, so writing a whole corpus out would need tens of gigabytes of
scratch space for no benefit.

Three outcomes are distinguished for each record.

  converted      the GE MUSE front end produced an intermediate representation
                 and the writer produced a DICOM dataset
  conformant     dicom-validator (IODValidator, same code the validate_iods
                 command runs) reported no error against the General ECG IOD
  complete       every unconditionally required attribute of the IOD, that is
                 every Type 1 and Type 2 attribute including those inside
                 required sequences, is present, and Type 1 attributes are
                 non-empty
  constrained    ecg2dcm.conformance.check_iod_constraints found no violation
                 of the IOD's content constraints (PS3.3 A.34.4.4), which the
                 attribute-level validator does not evaluate

Conditional attributes (Type 1C, 2C) are not counted in the completeness
denominator because whether they are required depends on other values in the
object; the validator evaluates those conditions and any violation surfaces as
a conformance error instead.

    uv run stratified_conversion.py --zip export.zip --since 2010-01 --until 2020-12 \
        --out supp_table9b --workers 8

Requires the ecg2dcm package (this repository) and dicom-validator.
"""
import argparse
import collections
import csv
import io
import json
import logging
import multiprocessing as mp
import os
import sys
import zipfile
from pathlib import Path

from ecg2dcm.codes import SOP_GENERAL_ECG as SOP

# Worker globals, set once per process by _init.
_G = {}


def required_attributes(json_path):
    """Return {path: (module, name, type)} for every Type 1 and Type 2 attribute
    declared in the modules of the General ECG IOD, recursing into sequences that
    are themselves unconditionally required.

    Only mandatory (use M) modules contribute; the Type 1 attributes of a User
    Optional or conditional module are required only when that module is present.
    Attributes reached only through a macro include (the 'include' key, e.g. the
    Code Sequence Macro inside Channel Source Sequence) are not counted, so that
    the denominator is a fixed, enumerable list that the output table prints in
    full. The conformance check is the stricter of the two: dicom-validator
    expands macros and evaluates conditional attributes as well."""
    iod = json.load(open(Path(json_path, 'iod_info.json')))
    mods = json.load(open(Path(json_path, 'module_info.json')))
    out = {}

    def walk(node, module, prefix):
        for tag, spec in node.items():
            if tag == 'include' or not isinstance(spec, dict):
                continue
            ty = spec.get('type')
            if ty not in ('1', '2'):
                continue
            out[prefix + tag] = (module, spec.get('name', tag), ty)
            if 'items' in spec:
                walk(spec['items'], module, prefix + tag + '/')

    for module, ref in iod[SOP]['modules'].items():
        # Only mandatory modules. A Type 1 attribute of a User Optional module
        # (Clinical Trial Subject, Patient Study, Synchronization) or of a
        # conditional one (Waveform Annotation) is required only when that module
        # is present, so counting it as missing would be wrong.
        if ref.get('use') != 'M':
            continue
        walk(mods[ref['ref']], module, '')
    return out


def _tag_of(s):
    """'(0008,0016)' -> (0x0008, 0x0016)"""
    return int(s[1:5], 16), int(s[6:10], 16)


def completeness(ds, required):
    """Return the list of required tags that are absent, or present but empty
    where Type 1 demands a value."""
    missing = []
    for path, (_module, _name, ty) in required.items():
        parts = path.split('/')
        # Only the top level and one sequence level occur in this IOD's
        # required set; deeper paths are walked item by item.
        node, ok = ds, True
        for i, p in enumerate(parts):
            t = _tag_of(p)
            if t not in node:
                ok = False
                break
            el = node[t]
            if i < len(parts) - 1:
                if not el.value:
                    ok = False
                    break
                node = el.value[0]      # first item stands for the sequence
        if not ok:
            missing.append(path)
            continue
        el = node[_tag_of(parts[-1])]
        if ty == '1' and (el.value is None or el.value == '' or el.value == []):
            missing.append(path)
    return missing


def _init(zip_path, json_path, since, until):
    from ecg2dcm.adapters import muse                     # noqa: E402
    from ecg2dcm import writer, check_iod_constraints     # noqa: E402
    from dicom_validator.spec_reader.edition_reader import EditionReader   # noqa: E402
    from dicom_validator.validator.iod_validator import IODValidator       # noqa: E402
    logging.disable(logging.CRITICAL)                     # the validator logs every finding
    _G.update(zip=zip_path, muse=muse, writer=writer, IODValidator=IODValidator,
              check=check_iod_constraints,
              info=EditionReader.load_dicom_info(Path(json_path)),
              required=required_attributes(json_path), since=since, until=until)


def _classify(exc):
    """Collapse an exception into a short, stable reason."""
    m = str(exc)
    if isinstance(exc, SyntaxError) or 'mismatched tag' in m or 'not well-formed' in m:
        return 'XML parse error'
    for probe, reason in (('not GE MUSE', 'not a GE MUSE RestingECG document'),
                          ('no waveform data', 'no waveform data in source'),
                          ('has no leads', 'waveform group with no leads'),
                          ('unparsable acquisition date', 'unusable acquisition date')):
        if probe in m:
            return reason
    return f'{type(exc).__name__}: {m[:60]}'


def _work(chunk):
    """Process a list of zip entry names in one process; return aggregates."""
    muse, writer, IODValidator = _G['muse'], _G['writer'], _G['IODValidator']
    check, info, required = _G['check'], _G['info'], _G['required']
    since, until = _G['since'], _G['until']

    dev = collections.Counter()        # (device, field) -> n
    sw = collections.Counter()         # (acq, ana, field) -> n
    fail = collections.Counter()       # (device, reason) -> n
    errs = collections.Counter()       # validator message -> n
    miss = collections.Counter()       # required attribute path -> n missing
    cviol = collections.Counter()      # IOD content constraint violation -> n
    seen = 0
    skipped = 0

    z = _G.get('zf')
    if z is None:
        # One handle per worker process. The central directory of a 27 GB,
        # 680k-entry archive takes tens of seconds to parse, so reopening it
        # per chunk would dominate the run.
        z = _G['zf'] = zipfile.ZipFile(_G['zip'])
    for name in chunk:
        try:
            blob = z.read(name)
        except Exception:
            fail[('(unreadable entry)', 'zip read error')] += 1
            continue

        # Identify the stratum from the source, independently of conversion,
        # so that a record that fails to convert is still attributed.
        head = blob[:32768].decode('utf-8', 'replace')
        def field(tag, t=head):
            a = t.find('<' + tag + '>')
            if a < 0:
                return None
            b = t.find('</' + tag + '>', a)
            v = t[a + len(tag) + 2:b].strip() if b > 0 else ''
            return v or None
        d = field('AcquisitionDevice') or '(element absent)'
        acq_sw = field('AcquisitionSoftwareVersion') or '(absent)'
        ana_sw = field('AnalysisSoftwareVersion') or '(absent)'

        try:
            rec = muse.parse(io.BytesIO(blob))
        except Exception as e:
            # A record the adapter cannot read is still a record. Window it on
            # the raw AcquisitionDate so that it is reported as a failure in its
            # own stratum rather than dropped from the denominator.
            if since or until:
                parts = (field('AcquisitionDate') or '').split('-')
                ym = (f'{parts[2]}{parts[0]}'
                      if len(parts) == 3 and all(x.isdigit() for x in parts) else '')
                if len(ym) != 6 or (since and ym < since) or (until and ym > until):
                    skipped += 1
                    continue
            seen += 1
            dev[(d, 'records')] += 1
            sw[(acq_sw, ana_sw, 'records')] += 1
            fail[(d, _classify(e))] += 1
            continue

        if since or until:
            ym = (rec.acquisition_date or '')[:6]
            if len(ym) != 6 or (since and ym < since) or (until and ym > until):
                skipped += 1
                continue

        seen += 1
        dev[(d, 'records')] += 1
        sw[(acq_sw, ana_sw, 'records')] += 1

        try:
            ds = writer.build(rec, index=1)
        except Exception as e:
            fail[(d, _classify(e))] += 1
            continue
        dev[(d, 'converted')] += 1
        sw[(acq_sw, ana_sw, 'converted')] += 1

        result = IODValidator(ds, info, logging.CRITICAL).validate()
        n_err = 0
        for module, findings in result.items():
            if module == 'fatal':
                errs['fatal: ' + str(findings)[:80]] += 1
                n_err += 1
                continue
            for message, tags in findings.items():
                errs[message] += len(tags) or 1
                n_err += len(tags) or 1
        if n_err == 0:
            dev[(d, 'conformant')] += 1
            sw[(acq_sw, ana_sw, 'conformant')] += 1

        gaps = completeness(ds, required)
        for g in gaps:
            miss[g] += 1
        if not gaps:
            dev[(d, 'complete')] += 1
            sw[(acq_sw, ana_sw, 'complete')] += 1

        viol = check(ds)
        for v in viol:
            cviol[v[:100]] += 1
        if not viol:
            dev[(d, 'constrained')] += 1
            sw[(acq_sw, ana_sw, 'constrained')] += 1

    return dev, sw, fail, errs, miss, cviol, seen, skipped


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--zip', dest='zip_path', required=True,
                    help='zip archive of MUSE XML files, read without extracting')
    ap.add_argument('--out', default='supp_table9b', help='output prefix')
    ap.add_argument('--since', metavar='YYYY-MM', help='keep records acquired in or after this month')
    ap.add_argument('--until', metavar='YYYY-MM', help='keep records acquired in or before this month')
    ap.add_argument('--limit', type=int, default=None, help='process only the first N entries')
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--chunk', type=int, default=500, help='entries per task')
    ap.add_argument('--standard', default=str(Path.home() / 'dicom-validator' / '2024b' / 'json'),
                    help='dicom-validator JSON specification directory')
    a = ap.parse_args()

    since = a.since.replace('-', '') if a.since else None
    until = a.until.replace('-', '') if a.until else None

    with zipfile.ZipFile(a.zip_path) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith('.xml'))
    if a.limit:
        names = names[:a.limit]
    print(f'{len(names)} entries, {a.workers} workers', file=sys.stderr)

    tasks = list(chunks(names, a.chunk))
    dev = collections.Counter(); sw = collections.Counter()
    fail = collections.Counter(); errs = collections.Counter(); miss = collections.Counter()
    cviol = collections.Counter()
    seen = skipped = 0

    init_args = (a.zip_path, a.standard, since, until)
    if a.workers == 1:
        _init(*init_args)
        results = (_work(t) for t in tasks)
        for i, r in enumerate(results):
            d, s, f, e, m, c, n, k = r
            dev += d; sw += s; fail += f; errs += e; miss += m; cviol += c; seen += n; skipped += k
            if (i + 1) % 20 == 0:
                print(f'  ... {(i+1)*a.chunk} entries', file=sys.stderr)
    else:
        # 'spawn' rather than 'fork': numpy and pydicom start threads at import
        # time, and forking a threaded parent deadlocks on macOS. Every worker
        # therefore receives its arguments explicitly through initargs.
        ctx = mp.get_context('spawn')
        with ctx.Pool(a.workers, initializer=_init, initargs=init_args) as pool:
            for i, (d, s, f, e, m, c, n, k) in enumerate(pool.imap_unordered(_work, tasks)):
                dev += d; sw += s; fail += f; errs += e; miss += m; cviol += c; seen += n; skipped += k
                if (i + 1) % 40 == 0:
                    print(f'  ... {seen + skipped} entries', file=sys.stderr)

    required = required_attributes(a.standard)

    def pct(x, n):
        return f'{x / n * 100:.2f}' if n else ''

    devices = sorted({k[0] for k in dev}, key=lambda d: -dev[(d, 'records')])
    with open(f'{a.out}_by_device.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['AcquisitionDevice', 'Records', 'Converted', 'Converted%',
                    'Conformant', 'Conformant%', 'AttributeComplete', 'AttributeComplete%',
                    'ConstraintsOK', 'ConstraintsOK%'])
        for d in devices:
            n = dev[(d, 'records')]
            w.writerow([d, n, dev[(d, 'converted')], pct(dev[(d, 'converted')], n),
                        dev[(d, 'conformant')], pct(dev[(d, 'conformant')], n),
                        dev[(d, 'complete')], pct(dev[(d, 'complete')], n),
                        dev[(d, 'constrained')], pct(dev[(d, 'constrained')], n)])

    pairs = sorted({(k[0], k[1]) for k in sw}, key=lambda p: -sw[(p[0], p[1], 'records')])
    with open(f'{a.out}_by_software.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['AcquisitionSoftwareVersion', 'AnalysisSoftwareVersion', 'Records',
                    'Converted', 'Converted%', 'Conformant', 'Conformant%',
                    'AttributeComplete', 'AttributeComplete%', 'ConstraintsOK', 'ConstraintsOK%'])
        for x, y in pairs:
            n = sw[(x, y, 'records')]
            w.writerow([x, y, n, sw[(x, y, 'converted')], pct(sw[(x, y, 'converted')], n),
                        sw[(x, y, 'conformant')], pct(sw[(x, y, 'conformant')], n),
                        sw[(x, y, 'complete')], pct(sw[(x, y, 'complete')], n),
                        sw[(x, y, 'constrained')], pct(sw[(x, y, 'constrained')], n)])

    with open(f'{a.out}_constraint_violations.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['Violation', 'Records'])
        for v, c in sorted(cviol.items(), key=lambda kv: -kv[1]):
            w.writerow([v, c])

    with open(f'{a.out}_failures.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['AcquisitionDevice', 'Reason', 'Records'])
        for (d, reason), c in sorted(fail.items(), key=lambda kv: (-kv[1], str(kv[0]))):
            w.writerow([d, reason, c])

    with open(f'{a.out}_attributes.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['Tag', 'Module', 'Name', 'Type', 'Populated', 'Missing', 'Populated%'])
        n_conv = sum(dev[(d, 'converted')] for d in devices)
        for path, (module, name, ty) in sorted(required.items()):
            gone = miss[path]
            w.writerow([path, module, name, ty, n_conv - gone, gone, pct(n_conv - gone, n_conv)])

    with open(f'{a.out}_summary.txt', 'w', encoding='utf-8') as fh:
        n_conv = sum(dev[(d, 'converted')] for d in devices)
        n_conf = sum(dev[(d, 'conformant')] for d in devices)
        n_comp = sum(dev[(d, 'complete')] for d in devices)
        fh.write(f'Entries in archive: {len(names)}\n')
        if since or until:
            fh.write(f'Acquisition window: {a.since or "(open)"} to {a.until or "(open)"}\n')
            fh.write(f'  excluded, outside window or undatable: {skipped}\n')
        fh.write(f'Records tabulated: {seen}\n')
        fh.write(f'Converted: {n_conv} ({pct(n_conv, seen)}%)\n')
        fh.write(f'Conformant (dicom-validator, 0 errors): {n_conf} ({pct(n_conf, seen)}%)\n')
        fh.write(f'All required attributes populated: {n_comp} ({pct(n_comp, seen)}%)\n')
        fh.write(f'Required attributes checked per object: {len(required)} '
                 f'(Type 1 and Type 2 of the 12-Lead ECG IOD)\n\n')
        fh.write(f'Device models: {len([d for d in devices if d != "(element absent)"])} named\n')
        fh.write(f'Software version pairs: {len(pairs)}\n\n')
        if fail:
            fh.write('Conversion failures by reason:\n')
            agg = collections.Counter()
            for (d, reason), c in fail.items():
                agg[reason] += c
            for reason, c in agg.most_common():
                fh.write(f'  {reason}: {c}\n')
            fh.write('\n')
        else:
            fh.write('Conversion failures: none\n\n')
        if errs:
            fh.write('Validator findings by message:\n')
            for message, c in errs.most_common(40):
                fh.write(f'  {c:>8}  {message}\n')
        else:
            fh.write('Validator findings: none\n')
        gaps = {k: v for k, v in miss.items() if v}
        fh.write('\n')
        if gaps:
            fh.write('Required attributes not populated in every converted object:\n')
            for path, c in sorted(gaps.items(), key=lambda kv: -kv[1]):
                module, name, ty = required[path]
                fh.write(f'  {path} {name} (Type {ty}, {module}): missing in {c}\n')
        else:
            fh.write('Every required attribute was populated in every converted object.\n')

    for suffix in ('by_device', 'by_software', 'failures', 'attributes', 'summary'):
        ext = 'txt' if suffix == 'summary' else 'csv'
        print(f'  wrote {a.out}_{suffix}.{ext}')
    print(f'\nTabulated {seen}; converted {sum(dev[(d, "converted")] for d in devices)}; '
          f'conformant {sum(dev[(d, "conformant")] for d in devices)}.')


if __name__ == '__main__':
    main()
