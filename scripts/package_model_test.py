"""Package the standalone tester; reuse the sibling NordRAG runtime assets."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    target = ROOT / 'dist' / 'ModelTester'
    if target.exists():
        raise SystemExit(f'Output already exists; preserve it before rebuilding: {target}')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
        '--name', 'ModelTester', '--paths', str(ROOT), '--collect-all', 'uvicorn',
        '--add-data', f'{ROOT / "nordrag/model_test_ui"};nordrag/model_test_ui',
        '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build/model-tester/work'),
        '--specpath', str(ROOT / 'build/model-tester'),
        str(ROOT / 'scripts/model_test_entry.py'),
    ], cwd=ROOT, check=True)
    shutil.copy2(ROOT / 'docs/MODEL_TESTER.md', target / 'README.md')
    shutil.copy2(ROOT / 'model-test-models.example.json', target / 'model-test-models.example.json')
    crt = ROOT / 'runtime/crt'
    if crt.is_dir():
        for dll in crt.glob('*.dll'):
            shutil.copy2(dll, target / '_internal' / dll.name)
    print(f'Built: {target / "ModelTester.exe"}', flush=True)


if __name__ == '__main__':
    main()
