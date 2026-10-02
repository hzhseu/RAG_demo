"""Attach verified acceptance artifacts and refresh the final directory checksums."""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nordrag.util import digest, write_json

target = ROOT / 'dist/NordRAG'
assert (target / 'nord-chat.exe').is_file() and (target / 'kb-builder.exe').is_file()
shutil.copy2(ROOT / 'artifacts/real-packaged-chat.png', ROOT / 'docs/interface-preview.png')
reports = ROOT / 'docs/validation'
reports.mkdir(exist_ok=True)
for name in ('retrieval-report.json', 'real-smoke-report.json', 'packaged-build-report.json', 'packaged-ui-report.json', 'scale-report.json'):
    shutil.copy2(ROOT / 'artifacts' / name, reports / name)
shutil.copy2(ROOT / 'artifacts/scale-real-30-0/benchmark.json', reports / 'real-scale-benchmark.json')
shutil.copy2(ROOT / 'artifacts/font-test/report.json', reports / 'font-report.json')
shutil.copytree(ROOT / 'docs', target / 'docs', dirs_exist_ok=True)
shutil.copy2(ROOT / 'README.md', target / 'README.md')
assert digest(target / 'samples/demo.ragkb') == digest(ROOT / 'artifacts/delivery-demo.ragkb')
assert digest(target / 'runtime.json') == digest(ROOT / 'runtime.json')
for source in (ROOT / 'frontend/dist').rglob('*'):
    if source.is_file():
        assert digest(source) == digest(target / 'frontend/dist' / source.relative_to(ROOT / 'frontend/dist'))
files = {p.relative_to(target).as_posix(): digest(p) for p in target.rglob('*') if p.is_file() and p.name != 'checksums.json'}
write_json(target / 'checksums.json', files)
size = sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
print(f'Finalized {len(files)} checksums; {size / 1024**3:.2f} GiB; {target}')
