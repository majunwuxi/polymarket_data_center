import json
import tempfile
import unittest
from pathlib import Path

import dashboard
import recorder


class DashboardTests(unittest.TestCase):
    def test_missing_database_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'missing.sqlite3'
            self.assertEqual(dashboard.read_data(path)['games'], [])
            self.assertFalse(path.exists())

    def test_beijing_date_and_market_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.sqlite3'
            db = recorder.connect(path)
            db.execute("INSERT INTO events VALUES('e','nba-det-nyk-2026-10-27','game','{}',0)")
            db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g','nba-det-nyk-2026-10-27',1793145600,'DET','NY','{}','open',0)")
            for cid, kind in [('a','moneyline'), ('b','totals'), ('c','first_half_spreads')]:
                db.execute('INSERT INTO markets(cid,event_id,created_at,raw) VALUES(?,?,?,?)', (cid,'e',1,json.dumps({'sportsMarketType':kind})))
            db.commit()
            db.close()
            game = dashboard.read_data(path)['games'][0]
            self.assertEqual((game['date'], game['time']), ('2026-10-28','08:00'))
            self.assertEqual(game['market_counts'], {'moneyline':1,'spreads':0,'totals':1})
            self.assertEqual(game['away'], {'en': 'Detroit Pistons', 'zh': '底特律活塞'})
            self.assertEqual(game['home'], {'en': 'New York Knicks', 'zh': '纽约尼克斯'})
            self.assertEqual(game['url'], 'https://polymarket.com/zh/sports/nba/nba-det-nyk-2026-10-27')

    def test_team_mapping_and_unknown(self):
        self.assertEqual(len(dashboard.TEAMS), 30)
        self.assertTrue(all(en and zh for en, zh in dashboard.TEAMS.values()))
        self.assertEqual(dashboard.team_name('GSW', '{}', 'away')['en'], 'Golden State Warriors')
        raw = json.dumps({'competitions': [{'competitors': [{'homeAway': 'away', 'team': {'displayName': 'Example Team'}}]}]})
        self.assertEqual(dashboard.team_name('NEW', raw, 'away'), {'en': 'Example Team', 'zh': '中文名称待确认'})
        self.assertIsNone(dashboard.event_url('https://example.com'))


if __name__ == '__main__':
    unittest.main()
