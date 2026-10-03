"""Create a ZIP64 portable release and verify every archived file against its manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = ROOT / 'dist/NordRAG'
    output = args.output.resolve()
    partial = output.with_suffix('.zip.partial')
    if output.exists() or partial.exists():
        raise SystemExit('Existing release preserved; select another output filename')
    output.parent.mkdir(parents=True, exist_ok=True)
    checksums = json.loads((source / 'checksums.json').read_text(encoding='utf-8'))
    files = sorted(p for p in source.rglob('*') if p.is_file())
    assert {p.relative_to(source).as_posix() for p in files} == set(checksums) | {'checksums.json'}
    try:
        with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for number, file in enumerate(files, 1):
                archive.write(file, 'NordRAG/' + file.relative_to(source).as_posix())
                if number % 5000 == 0:
                    print(f'Archived {number}/{len(files)} files', flush=True)
        print('Verifying archived SHA256 checksums...', flush=True)
        with zipfile.ZipFile(partial) as archive:
            assert len(archive.namelist()) == len(files)
            assert json.loads(archive.read('NordRAG/checksums.json')) == checksums
            for name, expected in checksums.items():
                h = hashlib.sha256()
                with archive.open('NordRAG/' + name) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(block)
                if h.hexdigest() != expected:
                    raise ValueError(f'Archive checksum mismatch: {name}')
        partial.rename(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    h = hashlib.sha256()
    with output.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    output.with_suffix('.zip.sha256.txt').write_text(f'{h.hexdigest()}  {output.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(output), 'bytes': output.stat().st_size, 'sha256': h.hexdigest(), 'verified_files': len(checksums)}, indent=2), flush=True)


if __name__ == '__main__':
    main()
