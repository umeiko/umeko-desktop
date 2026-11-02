import unittest
from app.pi_capabilities import CORE,MINIMAL,normalize,effective,plugin_enabled,tool_enabled,catalog,change,merge_resources,from_legacy

class PiCapabilitiesTests(unittest.TestCase):
    def test_cloud_tool_visibility_migrates_without_overriding_new_presets(self):
        migrated=from_legacy({},['write'])
        self.assertEqual(migrated['preset'],'custom')
        self.assertFalse(tool_enabled(migrated,{'name':'write','owner':'native'}))
        self.assertTrue(tool_enabled(migrated,{'name':'read','owner':'native'}))
        self.assertEqual(from_legacy({'preset':'full'},['write']),{'preset':'full'})
        self.assertEqual(from_legacy({},[]),{})

    def test_presets_have_exact_native_tool_sets_and_no_desktop_extensions(self):
        for preset,names in [('full',CORE),('standard',CORE),('minimal',MINIMAL)]:
            actual={t for t in CORE if tool_enabled({'preset':preset},{'name':t,'owner':'native'})}
            self.assertEqual(actual,set(names))
            self.assertEqual(plugin_enabled({'preset':preset},'builtin:umeko-control'),preset=='full')

    def test_editing_a_preset_creates_custom_and_switching_preserves_last_custom(self):
        resources={'toolCatalog':[{'name':'custom_one','owner':'plugin'}]}
        value=change({'preset':'minimal'},'pi.tool',{'name':'grep','enabled':True},[],resources)
        self.assertEqual(value['preset'],'custom');self.assertEqual(value['custom']['base'],'minimal')
        self.assertTrue(tool_enabled(value,{'name':'grep','owner':'native'}))
        restored=change(change(value,'pi.preset',{'preset':'full'},[],resources),'pi.preset',{'preset':'custom'},[],resources)
        self.assertEqual(restored,value)

    def test_plugin_switch_wins_over_child_tool_and_native_settings_fallback(self):
        rows=[{'id':'one','path':'plugin'}];value=change({},'pi.plugin',{'id':'one','enabled':False},rows,{})
        value=change(value,'pi.tool',{'name':'custom_one','enabled':True},rows,{'toolCatalog':[{'name':'custom_one','owner':'plugin'}]})
        self.assertFalse(tool_enabled(value,{'name':'custom_one','owner':'plugin'}))
        self.assertFalse(plugin_enabled({},'plugin',False))

    def test_current_inventory_is_required_and_invalid_inputs_are_not_silently_applied(self):
        for action,args in [('pi.preset',{'preset':'unknown'}),('pi.tool',{'name':'*','enabled':True}),('pi.tool',{'name':'missing','enabled':True}),('pi.plugin',{'id':'missing','enabled':True}),('pi.tool',{'name':'read','enabled':1})]:
            with self.subTest(action=action,args=args),self.assertRaises(ValueError):change({},action,args,[],{})
        self.assertEqual(normalize({'custom':{'tools':{'read':1}}})['custom']['tools'],{})

    def test_only_disabled_plugin_definitions_are_cached_and_live_catalog_wins(self):
        old={'toolCatalog':[{'name':'off_tool','owner':'plugin'},{'name':'removed_live_tool','owner':'live'}]}
        new={'tools':['read'],'toolCatalog':[{'name':'read','owner':'native'}]}
        value={'preset':'custom','custom':{'base':'full','plugins':{'plugin':False}}}
        merged=merge_resources(old,new,value)
        self.assertEqual({t['name'] for t in merged['toolCatalog']},{'off_tool','read'})
        self.assertEqual(merged['tools'],['read'])
        self.assertIn('grep',{t['name'] for t in catalog({'allTools':[]})})

if __name__=='__main__':unittest.main()
