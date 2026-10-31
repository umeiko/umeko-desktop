"""Address-label geometry across languages, font scales and compact windows."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
temporary=tempfile.TemporaryDirectory(prefix='umeko-proxy-layout-')
os.environ.update(UMEKO_DATA_DIR=str(Path(temporary.name)/'profile'),PI_CODING_AGENT_DIR=str(Path(temporary.name)/'agent'),UMEKO_LANGUAGE='zh',QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from main import create_application

app,engine,backend=create_application()
window=engine.rootObjects()[0]
warnings=[]
engine.warnings.connect(lambda values:warnings.extend(value.toString() for value in values))
out=ROOT/'build/api-proxy-layout';out.mkdir(parents=True,exist_ok=True)

def find(name):
    stack=[window.contentItem()]
    while stack:
        item=stack.pop()
        if item.objectName()==name:return item
        stack.extend(item.childItems())
    raise AssertionError('Missing control: '+name)

try:
    window.setProperty('page','settings');window.setProperty('settingsTab',1)
    QTest.qWait(150)
    rows=[]
    stacked=False
    for language in ('zh','en'):
        backend.setLanguage(language)
        for scale in (.5,1,1.5,2):
            backend.setFontScale(scale)
            for width in (1440,1060):
                window.resize(width,900);QTest.qWait(80)
                window.grabWindow()  # Complete layout polish before geometry assertions.
                for protocol,suffix in (('Openai','/v1'),('Anthropic','')):
                    row=find('proxy'+protocol+'AddressRow')
                    label=find('proxy'+protocol+'AddressLabel')
                    field=find('proxy'+protocol+'BaseUrl')
                    copy=find('copyProxy'+protocol+'BaseUrl')
                    origin=label.mapToItem(row,QPointF(0,0))
                    input_origin=field.mapToItem(row,QPointF(0,0))
                    copy_origin=copy.mapToItem(row,QPointF(0,0))
                    assert label.width()+1>=label.property('paintedWidth'),(language,scale,width,protocol,'truncated label')
                    same_line=min(origin.y()+label.height(),input_origin.y()+field.height())>max(origin.y(),input_origin.y())
                    if same_line:
                        assert input_origin.x()>=origin.x()+label.width()+10,(language,scale,width,protocol,'overlapping label')
                    else:
                        stacked=True
                        assert input_origin.y()>=origin.y()+label.height()+6,(language,scale,width,protocol,'overlapping stacked row')
                    assert input_origin.x()>=0 and field.width()>80
                    assert copy_origin.x()+copy.width()<=row.width()+1,(language,scale,width,protocol,'copy outside row')
                    assert field.property('text')=='http://127.0.0.1:8787'+suffix
                    rows.append({'language':language,'fontScale':scale,'windowWidth':width,'protocol':protocol,'stacked':not same_line})
                if language=='zh' and scale in (1,2) and width==1060:
                    flick=find('settingsScroll').property('contentItem')
                    card=find('proxyAddressesCard')
                    point=card.mapToItem(flick,QPointF(0,0))
                    flick.setProperty('contentY',max(0,min(point.y(),flick.property('contentHeight')-flick.height())))
                    QTest.qWait(50)
                    window.grabWindow().save(str(out/f'addresses-{scale:g}x.png'))
    assert stacked,'The compact, large-font case never exercised stacked addresses'
    assert not warnings,'\n'.join(warnings)
    (out/'result.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print('API_PROXY_LAYOUT_OK: complete labels, no overlap, responsive addresses, zh/en, 50–200% fonts')
finally:
    backend.close()
    import shiboken6
    shiboken6.delete(engine)
    app.processEvents();temporary.cleanup()
