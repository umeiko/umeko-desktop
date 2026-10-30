"""Source/render switches use real Markdown and a real static HTML WebView."""
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('UMEKO_LANGUAGE','zh')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from main import create_application
from app.storage import Store

with tempfile.TemporaryDirectory(prefix='umeko-document-modes-ui-') as temporary:
    base=Path(temporary)
    os.environ['UMEKO_DATA_DIR']=str(base/'profile')
    (base/'style.css').write_text('h1{color:rgb(12,34,56)}body{font:18px sans-serif;padding:28px;background:#fcfcfa}')
    html=base/'index.html'
    html.write_text('<!doctype html><meta charset="utf-8"><title>Loading</title><link rel="stylesheet" href="style.css"><h1>静态 HTML 预览</h1><p>同一份产物，可以查看源码，也可以直接验收网页。</p><script>window.onload=()=>{document.title=getComputedStyle(document.querySelector("h1")).color==="rgb(12, 34, 56)"?"Static HTML Ready":"CSS failed"}</script>')
    html2=base/'other.html'; html2.write_text('<h1>Another HTML file</h1>')
    markdown=base/'Readme.md';markdown.write_text('# 产物预览\n\n**Markdown 渲染与源码**\n\n- 独立记忆 Markdown 的选择\n- 独立记忆 HTML 的选择\n')
    markdown2=base/'Other.md';markdown2.write_text('# Other Markdown\n')
    app,engine,backend=create_application();window=engine.rootObjects()[0]
    warnings=[];engine.warnings.connect(lambda errors:warnings.extend(error.toString() for error in errors))
    assert backend.webviewAvailable, 'Install the existing pinned WebView component for this integration test'
    def find(name):
        pending=[window.contentItem()]
        while pending:
            item=pending.pop()
            if item.objectName()==name:return item
            # The Qt WebView plugin's private native items have no PySide
            # wrappers. Inspect its public WebView properties, not that tree.
            if item.objectName() not in ('htmlPreviewBrowser','webSurfaceLoader'):
                pending.extend(item.childItems())
        raise AssertionError(name)
    def wait(predicate,label):
        for _ in range(700):
            QTest.qWait(20)
            if predicate():return
        raise AssertionError(label+'\n'+'\n'.join(warnings))
    def click(name):
        item=find(name);QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(item.boundingRect().center()).toPoint())
    def submit(file,kind):
        backend._handle_pi_event(backend._view,{'type':'tool','id':'mode-'+file.name,'name':'submit_to_chatbox','args':{},'state':'done','media':[{'kind':kind,'path':str(file),'title':file.name}]})
        wait(lambda:not backend.documentPreview.state.get('busy') and not find('webPane').property('moving'),'Preview did not settle')
    try:
        QTest.qWait(250)
        submit(markdown,'markdown')
        assert backend.documentPreview.state['mode']=='rendered'
        assert find('documentPreviewText').property('text').startswith('<!DOCTYPE')
        click('documentMode_source');QTest.qWait(50)
        assert find('documentPreviewText').property('text')==markdown.read_text(), (backend.documentPreview.state['mode'],repr(find('documentPreviewText').property('text')),repr(markdown.read_text()))
        print('MARKDOWN_SOURCE_OK',flush=True)
        submit(markdown2,'markdown')
        assert backend.documentPreview.state['mode']=='source'
        submit(html,'code')
        assert backend.documentPreview.state['fileType']=='html'
        wait(lambda:find('htmlPreviewBrowser').property('item') is not None,'No HTML browser')
        view=find('htmlPreviewBrowser').property('item')
        wait(lambda:view.property('title')=='Static HTML Ready' and not view.property('loading'),'Static HTML and relative CSS did not render')
        print('HTML_RENDER_OK',flush=True)
        output=ROOT/'artifacts/screenshots';output.mkdir(parents=True,exist_ok=True)
        assert window.grabWindow().save(str(output/'document-html-rendered.png'))
        click('documentMode_source');QTest.qWait(80)
        assert find('htmlPreviewBrowser').property('item') is None
        print('HTML_SOURCE_OK',flush=True)
        assert '<h1>静态 HTML 预览</h1>' in find('documentPreviewText').property('text')
        submit(html2,'code')
        assert backend.documentPreview.state['mode']=='source'
        assert backend.store.data['ui']['documentPreviewModes']=={'markdown':'source','html':'source'}
        assert Store().data['ui']['documentPreviewModes']=={'markdown':'source','html':'source'}
        submit(markdown,'markdown');click('documentMode_rendered');QTest.qWait(70)
        assert backend.documentPreview.state['mode']=='rendered'
        assert backend.store.data['ui']['documentPreviewModes']['html']=='source'
        assert window.grabWindow().save(str(output/'document-markdown-modes.png'))
        assert not warnings, '\n'.join(warnings)
        print('DOCUMENT_MODES_UI_OK: real HTML, relative CSS/JS, Markdown source/render, unloading browser, global per-type preference and saved settings reload')
    finally:
        backend.close()
        import shiboken6
        shiboken6.delete(engine)
