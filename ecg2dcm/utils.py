"""File helpers for the batch command-line tool."""
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


def get_all_files_recursive(path, ext=None, exclude=None):
    """All files under ``path`` (recursively) whose name ends with ``ext``, sorted."""
    out = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if exclude is not None and exclude in f:
                continue
            if ext is None or f.lower().endswith(ext.lower()):
                out.append(os.path.join(root, f))
    return sorted(out)


def set_dcm_save_path(source_path, target_path, pattern=None, pattern_values=None, extension='dcm'):
    """Output path for one file: ``pattern`` formatted with ``pattern_values``, else the source stem."""
    if pattern is not None:
        assert pattern_values is not None, 'pattern_values must be provided if pattern is specified'
        if 'seq' in pattern_values:
            pattern_values['seq'] = str(pattern_values['seq']).zfill(5)
        name = f'{pattern.format(**pattern_values)}.{extension}'
    else:
        name = f'{os.path.splitext(os.path.basename(source_path))[0]}.{extension}'
    return os.path.join(target_path, name)


def save_mrn_map_table(target_dict, target_path=None):
    """Write the surrogate-ID table of a run. Never commit it: it links surrogates to source IDs."""
    target_path = target_path or os.getcwd()
    name = os.path.join(target_path, 'mrn_mapping_table.json')
    if os.path.exists(name):
        name = os.path.join(target_path, f'mrn_mapping_table_{datetime.today().strftime("%Y%m%d_%H%M%S")}.json')
    with open(name, 'w', encoding='utf-8') as fh:
        json.dump(target_dict, fh, ensure_ascii=False, indent=1)
    print(f'MRN mapping table saved to {name}')
    return name


@contextmanager
def fresh_output_directory(target_path):
    """Reserve an empty output directory for exactly one conversion run.

    Patient surrogates and date offsets belong to one run. Reusing an output
    directory would mix unrelated mapping namespaces, so refuse before writing
    any objects. Exclusive creation of the marker also prevents two commands
    from both accepting the same empty directory.
    """
    target = Path(target_path)
    target.mkdir(parents=True, exist_ok=True)
    marker = target / '.ecg2dcm-run.lock'
    message = 'Output directory is occupied or in use; choose a new empty output directory.'
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise FileExistsError(message) from None
    try:
        if any(entry.name != marker.name for entry in target.iterdir()):
            raise FileExistsError(message)
        yield target
    finally:
        os.close(fd)
        marker.unlink()
