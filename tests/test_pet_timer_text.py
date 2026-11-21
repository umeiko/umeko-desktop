import unittest
from app.pet_timer_text import extract,calendar_date,clock_time

class PetTimerTextTests(unittest.TestCase):
    def test_explicit_fields_skip_provided_details(self):
        fields,notice=extract('名称：构建检查；指令：检查构建；时间：2035-1-2 9:30；时区：Asia/Shanghai')
        self.assertEqual(fields,{'name':'构建检查','message':'检查构建','frequency':'once','first_date':'2035-01-02','local_time':'09:30','zone':'Asia/Shanghai'})
        self.assertFalse(notice)

    def test_absolute_and_interval(self):
        fields,_=extract('2035-1-2 9:30 检查构建')
        self.assertEqual(fields['local_time'],'09:30');self.assertEqual(fields['message'],'检查构建')
        fields,_=extract('每隔 2 小时检查构建')
        self.assertEqual(fields['interval_value'],'120');self.assertEqual(fields['frequency'],'interval')

    def test_daily_is_recognized_but_not_changed_to_interval(self):
        fields,notice=extract('每天 9 点检查构建')
        self.assertEqual(fields,{'local_time':'09:00','message':'检查构建'})
        self.assertIn('不会自动改成',notice)

    def test_invalid_or_ambiguous_dates_do_not_guess(self):
        fields,notice=extract('明天9点检查构建')
        self.assertNotIn('first_date',fields);self.assertNotIn('frequency',fields);self.assertTrue(notice)
        fields,notice=extract('2035-2-30 9:30 检查构建')
        self.assertNotIn('first_date',fields);self.assertNotIn('frequency',fields);self.assertTrue(notice)
        self.assertEqual(fields['message'],'2035-2-30 9:30 检查构建')

    def test_normalization_matches_schedule_iso_parser(self):
        from datetime import date,time
        self.assertEqual(date.fromisoformat(calendar_date('2035-1-2')).isoformat(),'2035-01-02')
        self.assertEqual(time.fromisoformat(clock_time('9:30')).hour,9)
        self.assertEqual(clock_time('9点半'),'09:30')
        with self.assertRaises(ValueError):clock_time('25:00')

    def test_constraints_are_not_dropped(self):
        fields,_=extract('指令：检查构建；但不要修改代码')
        self.assertEqual(fields['message'],'检查构建；但不要修改代码')

    def test_conflicts_remain_missing_and_never_take_last_value(self):
        for text,key in [('时间：09:00；时间：10:00；时间：11:00','local_time'),('日期：2035-01-02；时间：2036-01-02 10:00','first_date'),('时间：2035-01-02 09:00；每隔2小时检查','frequency')]:
            fields,notice=extract(text)
            self.assertNotIn(key,fields,text);self.assertIn('冲突',notice)

    def test_malformed_time_is_not_truncated(self):
        text='2035-01-02 09:300 检查'
        fields,notice=extract(text)
        self.assertNotIn('local_time',fields);self.assertEqual(fields['message'],text);self.assertTrue(notice)

    def test_compound_time_is_not_consumed_as_a_prefix(self):
        for text in ['每隔2小时30分钟检查','每隔2 小时 30分钟检查','每隔2天半检查','每天9点30秒检查','每天9点三十分检查']:
            fields,notice=extract(text)
            self.assertNotIn('frequency',fields,text)
            self.assertNotIn('local_time',fields,text)
            self.assertEqual(fields['message'],text);self.assertTrue(notice)

    def test_conflicting_zone_does_not_fall_back_to_system_default(self):
        fields,notice=extract('时区：Asia/Shanghai；时区：UTC')
        self.assertEqual(fields['zone'],'');self.assertTrue(notice)

    def test_clock_suffix_is_not_silently_discarded(self):
        for phrase in ['09:30+08:00', '09:30 -0500', '09:30 PM', '09:30am', '09:30 p.m.', '09:30Z', '09:30 UTC+8', '09:30 PST', '09:30 Asia/Shanghai', '09:30 (UTC+8)', '9点下午', '9点北京时间']:
            text='2035-01-02 '+phrase+' 检查'
            fields,notice=extract(text)
            self.assertNotIn('frequency',fields,text)
            self.assertNotIn('local_time',fields,text)
            self.assertEqual(fields['zone'],'',text)
            self.assertEqual(fields['message'],text)
            self.assertIn('24 小时',notice)

    def test_daily_and_labelled_suffixes_require_reentry(self):
        for text in ['每天9:30 PM 检查','名称：检查；时间：2035-01-02 09:30+08:00；指令：检查','时间：09:30 AM；指令：检查']:
            fields,notice=extract(text)
            self.assertNotIn('local_time',fields,text);self.assertEqual(fields['zone'],'',text)
            self.assertTrue(notice)
        with self.assertRaises(ValueError):clock_time('09:30 PM')

    def test_ranges_and_alternatives_are_not_fixed_to_first_value(self):
        for text in ['每隔2小时或3小时检查','每隔2小时至4小时检查','每隔2小时到4小时检查','每隔2小时左右检查','2035-01-02 09:30-10:30 检查','2035-01-02 09:30至10:30检查','每天9点或10点检查']:
            fields,notice=extract(text)
            self.assertNotIn('frequency',fields,text);self.assertNotIn('local_time',fields,text)
            self.assertNotIn('interval_value',fields,text)
            self.assertEqual(fields['message'],text);self.assertTrue(notice)

    def test_lowercase_english_instruction_is_not_a_zone(self):
        fields,notice=extract('2035-01-02 09:30 check build')
        self.assertEqual(fields['local_time'],'09:30');self.assertEqual(fields['message'],'check build');self.assertFalse(notice)

    def test_punctuation_cannot_hide_time_or_interval_modifiers(self):
        for text in ['2035-01-02 09:30，北京时间检查','2035-01-02 09:30, UTC 检查','2035-01-02 09:30；PM 检查','每天9点。PM检查','每隔2小时；或3小时检查','每隔2小时，至4小时检查','每隔2小时，3小时检查','09:30, UTC 检查','09:30；PM 检查']:
            fields,notice=extract(text)
            self.assertNotIn('frequency',fields,text);self.assertNotIn('local_time',fields,text)
            self.assertNotIn('interval_value',fields,text);self.assertTrue(notice)
            # Semicolon-separated free-text clauses are normalized, never dropped.
            self.assertIn('检查',fields['message'])

if __name__=='__main__':unittest.main()
