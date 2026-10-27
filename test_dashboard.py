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

    def test_game_details_filter_pagination_and_decimal_amount(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.sqlite3'
            db = recorder.connect(path)
            slug = 'nba-det-nyk-2026-10-27'
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)', ('e', slug, 'game', '{}', 0))
            db.execute('INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES(?,?,?,?,?,?,?,?)', ('g', slug, 1793145600, 'DET', 'NY', '{}', 'open', 0))
            for cid, kind in [('win', 'moneyline'), ('tot', 'totals'), ('half', 'first_half_totals')]:
                db.execute('INSERT INTO markets(cid,event_id,question,created_at,raw) VALUES(?,?,?,?,?)', (cid, 'e', cid, 1, json.dumps({'sportsMarketType': kind})))
                db.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (cid, 1, cid, 10, 20, 'wallet', 'BUY', 'Yes', 'asset', '0.1', '0.2', 'tx', '{}', 1))
            db.commit()
            db.close()
            result = dashboard.read_game(path, slug, limit=1)
            self.assertEqual(result['total'], 2)
            self.assertEqual(len(result['trades']), 1)
            self.assertEqual(result['trades'][0]['amount'], '0.02')
            self.assertEqual(len(dashboard.read_game(path, slug, offset=1, limit=1)['trades']), 1)
            self.assertEqual(dashboard.read_game(path, slug, kind='totals')['total'], 1)
            self.assertEqual(dashboard.read_game(path, slug, kind='spreads')['total'], 0)
            self.assertIn('error', dashboard.read_game(path, 'invalid'))
            self.assertIn('error', dashboard.read_game(path, slug, offset=-1))

    def test_game_details_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn('error', dashboard.read_game(Path(tmp) / 'absent.sqlite3', 'nba-det-nyk-2026-10-27'))

    def test_market_summary_is_separate_and_excludes_invalid_amounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.sqlite3'
            db = recorder.connect(path)
            slug = 'nba-det-nyk-2026-10-27'
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)', ('e', slug, 'game', '{}', 0))
            db.execute('INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES(?,?,?,?,?,?,?,?)', ('g', slug, 1793145600, 'DET', 'NY', '{}', 'open', 0))
            for cid, kind in [('win', 'moneyline'), ('tot', 'totals'), ('half', 'first_half_totals')]:
                db.execute('INSERT INTO markets(cid,event_id,question,created_at,raw) VALUES(?,?,?,?,?)', (cid, 'e', cid, 1, json.dumps({'sportsMarketType': kind})))
            samples = [('a','win','0xABC','BUY','Pistons','0.1','0.2'),('b','win','0xabc','SELL','Pistons','0.4','2'),('c','win','0xdef','BUY','Knicks','bad','2'),('d','tot','0xdef','BUY','Over','0.5','10'),('e','half','0xdef','BUY','Over','0.5','10')]
            for fp,cid,wallet,side,outcome,price,size in samples:
                db.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (fp,1,cid,10,20,wallet,side,outcome,'asset',price,size,'tx','{}',1))
            db.commit()
            db.close()
            result = dashboard.read_summary(path, slug)
            markets = {m['cid']:m for m in result['markets']}
            self.assertEqual(set(markets), {'win','tot'})
            self.assertEqual((markets['win']['records'],markets['win']['wallet_count'],markets['win']['invalid']), (3,2,1))
            pistons = next(o for o in markets['win']['outcomes'] if o['name']=='Pistons')
            self.assertEqual((pistons['buy'],pistons['sell']), ('0.02','0.8'))
            self.assertEqual([m['cid'] for m in dashboard.read_summary(path, slug, 'totals')['markets']], ['tot'])


if __name__ == '__main__':
    unittest.main()
