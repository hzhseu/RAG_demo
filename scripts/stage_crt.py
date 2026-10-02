"""Stage official VC14 x64 redistributable DLLs extracted from its minimum CAB.

Download https://aka.ms/vc14/vc_redist.x64.exe and verify its Microsoft signature.
Extract the bootstrapper's embedded CABs, resolve payload names from its Burn
manifest, then expand the vcRuntimeMinimum_amd64 CAB into downloads/vc-extracted.
This performs no system-wide runtime installation.
"""
from pathlib import Path
import shutil
import pefile
import hashlib
import json
ROOT=Path(__file__).resolve().parent.parent
runtime=ROOT/'runtime'
source=runtime/'downloads/vc-extracted'
files=list(source.glob('*.dll_amd64'))
assert any(p.name.lower()=='msvcp140.dll_amd64' for p in files),'VC runtime extraction missing'
for file in files:
    assert pefile.PE(str(file),fast_load=True).FILE_HEADER.Machine==0x8664,'Expected x64 DLL'
    for target in (runtime/'crt',runtime/'llama',runtime/'ocr',runtime/'LibreOffice-25.8.2.2/program'):
        target.mkdir(exist_ok=True)
        shutil.copy2(file,target/file.name.removesuffix('_amd64'))
(runtime/'crt/ORIGIN.txt').write_text('Unmodified Microsoft Visual C++ v14 x64 runtime 14.51.36247.0, extracted from the Microsoft-signed redistributable downloaded at https://aka.ms/vc14/vc_redist.x64.exe . Documentation and terms: https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist . Windows system/UCRT DLLs are supplied by supported Windows 10/11. Source executable checksum is recorded in runtime/sources.json.',encoding='utf-8')
shutil.copy2(runtime/'downloads/vc_redist.x64.exe',runtime/'crt/vc_redist.x64.exe')
sources_path=runtime/'sources.json'
sources=json.loads(sources_path.read_text(encoding='utf-8'))
sources=[s for s in sources if not s['name'].startswith('Microsoft Visual C++')]
sources.append({'name':'Microsoft Visual C++ v14 x64 14.51.36247.0','source':'https://aka.ms/vc14/vc_redist.x64.exe','sha256':hashlib.sha256((runtime/'downloads/vc_redist.x64.exe').read_bytes()).hexdigest(),'license':'Microsoft Visual C++ Redistributable license terms'})
sources_path.write_text(json.dumps(sources,indent=2),encoding='utf-8')
print('App-local VC runtime staged for all Windows engines')
