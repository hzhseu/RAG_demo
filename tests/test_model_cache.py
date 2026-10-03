import threading
from test_build import Engines
from nordrag.builder import build
from nordrag.package import open_package
from nordrag.util import read_json


def test_parse_reused_but_generation_separated(deck,tmp_path):
    e=Engines();e.parse_signature='parser-same';e.signature='model-one'
    cache=tmp_path/'cache'
    build(deck.parent,'One',tmp_path/'one.ragkb',cache,e,threading.Event())
    e.signature='model-two'
    e.convert=lambda *args: (_ for _ in ()).throw(AssertionError('parse should be reused'))
    e.organize=lambda chunks,cancel: {'summary':'NEW MODEL [1]','category':'New','tags':[],'citations':chunks[:1]}
    result=build(deck.parent,'Two',tmp_path/'two.ragkb',cache,e,threading.Event())
    root,_=open_package(tmp_path/'two.ragkb',tmp_path/'work',e.embedding_id)
    assert read_json(root/'documents.json')[0]['summary']=='NEW MODEL [1]'
    assert result['status']=='complete'
