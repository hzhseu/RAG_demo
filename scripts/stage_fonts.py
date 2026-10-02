"""Install application-private fonts into LibreOffice's Windows font search path."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
runtime = ROOT / 'runtime'
office = runtime / 'LibreOffice-25.8.2.2'
target = office / 'share/fonts/truetype'
target.mkdir(parents=True, exist_ok=True)
shutil.copytree(office / 'Fonts', target, dirs_exist_ok=True)
font = runtime / 'downloads/NotoSansCJKsc-Regular.otf'
shutil.copy2(font, target / font.name)
webfonts = ROOT / 'frontend/public/fonts'
webfonts.mkdir(parents=True, exist_ok=True)
shutil.copy2(font, webfonts / font.name)
shutil.copy2(runtime / 'licenses/Noto-CJK-OFL.txt', webfonts / 'LICENSE.txt')
path = runtime / 'sources.json'
sources = json.loads(path.read_text(encoding='utf-8'))
sources = [s for s in sources if s['name'] != 'Noto Sans CJK SC 2.004']
sources.append({'name': 'Noto Sans CJK SC 2.004', 'source': 'https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf', 'sha256': hashlib.sha256(font.read_bytes()).hexdigest(), 'license': 'SIL Open Font License 1.1; runtime/licenses/Noto-CJK-OFL.txt'})
path.write_text(json.dumps(sources, indent=2), encoding='utf-8')
print('LibreOffice bundled fonts and Noto CJK installed privately; no system font changes')
