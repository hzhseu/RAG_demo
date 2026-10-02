"""Set bundled LibreOffice defaults to offline before its first execution."""
from pathlib import Path
from lxml import etree
ROOT=Path(__file__).resolve().parent.parent/'runtime/LibreOffice-25.8.2.2'
ns={'oor':'http://openoffice.org/2001/registry'}
p=ROOT/'share/registry/main.xcd'
tree=etree.parse(str(p))
nodes=tree.xpath('//*[local-name()="component-schema" and @oor:name="Update"]//*[@oor:name="Enabled"]/*[local-name()="value"]',namespaces=ns)
assert nodes, 'Update settings schema missing'
for node in nodes:node.text='false'
tree.write(str(p),encoding='UTF-8',xml_declaration=True)
p=ROOT/'share/registry/onlineupdate.xcd';tree=etree.parse(str(p))
for node in tree.xpath('//*[@oor:name="AutoCheckEnabled" or @oor:name="AutoDownloadEnabled"]/*[local-name()="value"]',namespaces=ns):node.text='false'
tree.write(str(p),encoding='UTF-8',xml_declaration=True)
print('Bundled LibreOffice automatic updates disabled')
