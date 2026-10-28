from pathlib import Path
import unittest
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine


class LoadingTipsTests(unittest.TestCase):
    def test_random_tips_do_not_repeat_and_have_translations(self):
        app=QCoreApplication.instance() or QCoreApplication([])
        engine=QJSEngine()
        root=Path(__file__).resolve().parents[1]/'app/qml'
        script=(root/'loading-tips.js').read_text().replace('.pragma library','',1)
        result=engine.evaluate(script)
        self.assertFalse(result.isError())
        self.assertGreaterEqual(engine.evaluate('items.length').toInt(),18)
        self.assertTrue(engine.evaluate('items.some(t=>t.includes("Token")) && items.some(t=>t.includes("子代理"))').toBool())
        self.assertTrue(engine.evaluate('items.every((_,p)=>[0,0.3,0.999999,1].every(r=>{const n=choose(p,r);return n>=0&&n<items.length&&n!==p}))').toBool())
        engine.evaluate((root/'english.js').read_text().replace('.pragma library','',1))
        self.assertTrue(engine.evaluate('items.every(t=>typeof strings[t]==="string" && strings[t].length>0)').toBool())
