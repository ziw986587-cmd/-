import copy
import sys
import unittest
from pathlib import Path
from datetime import timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'room-engine'))
from beijing_display import present, format_time, BEIJING


class BeijingDisplayTests(unittest.TestCase):
    def test_utc_conversion_with_midnight_month_and_year_rollover(self):
        self.assertEqual(format_time('2026-10-01 07:21:14', timezone.utc), '2026-10-01 15:21:14')
        self.assertEqual(format_time('2026-09-30 20:00:00', timezone.utc), '2026-10-01 04:00:00')
        self.assertEqual(format_time('2026-12-31 20:00:00', timezone.utc), '2027-01-01 04:00:00')

    def test_beijing_local_and_explicit_offsets_do_not_double_convert(self):
        self.assertEqual(format_time('2026-10-01 15:21:14', BEIJING), '2026-10-01 15:21:14')
        self.assertEqual(format_time('2026-10-01T15:21:14+08:00', timezone.utc), '2026-10-01 15:21:14')
        self.assertEqual(format_time('2026-10-01T07:21:14Z', BEIJING), '2026-10-01 15:21:14')
        self.assertEqual(format_time('not a date', timezone.utc), 'not a date')

    def test_all_portal_timestamps_without_mutating_data_or_deadlines(self):
        s={field:[dict(id='one',time='2026-10-01 07:21:14',content='2026-10-01 07:21:14')]
           for field in ('chat','history','orders','ledger','requests')}
        s.update(feedStatus='读取成功 2026-10-01 07:21:14',serverTime=1800000000,
                 round=dict(endAt=1800000210),balance=1000)
        original=copy.deepcopy(s)
        out=present(s,timezone.utc)
        self.assertEqual(s,original)
        for field in ('chat','history','orders','ledger','requests'):
            self.assertEqual(out[field][0]['time'],'2026-10-01 15:21:14')
            self.assertEqual(out[field][0]['content'],s[field][0]['content'])
        self.assertEqual(out['feedStatus'],'读取成功 2026-10-01 15:21:14')
        for field in ('round','serverTime','balance'):self.assertEqual(out[field],s[field])
        self.assertEqual(present(out,timezone.utc),out)

    def test_imported_desktop_records_keep_beijing_timestamp(self):
        s={'orders':[dict(time='2026-09-29 12:00:00',legacy=True)],
           'requests':[dict(id='legacy-123',time='2026-09-29 12:00:00')]}
        out=present(s,timezone.utc)
        self.assertEqual(out['orders'][0]['time'],s['orders'][0]['time'])
        self.assertEqual(out['requests'][0]['time'],s['requests'][0]['time'])


if __name__=='__main__':unittest.main()
