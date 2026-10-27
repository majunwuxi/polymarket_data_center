import sqlite3
import unittest
from unittest.mock import patch

import recorder


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.db = recorder.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO markets(cid,event_id,created_at,raw) VALUES('c','e',100,'{}')")
        self.db.commit()
        self.row = {'conditionId': 'c', 'timestamp': 110, 'price': 0.5, 'size': 2, 'proxyWallet': 'w'}

    def test_duplicate_rows_and_repeated_query(self):
        with patch.object(recorder, 'fetch_window', return_value=[self.row, self.row]):
            recorder.sync_market(self.db, 'c', end=120)
            recorder.sync_market(self.db, 'c', end=130)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT checkpoint FROM markets').fetchone()[0], 130)

    def test_failure_keeps_checkpoint(self):
        self.db.execute('UPDATE markets SET checkpoint=200')
        self.db.commit()
        with patch.object(recorder, 'fetch_window', side_effect=RuntimeError('failed')) as query:
            with self.assertRaises(RuntimeError):
                recorder.sync_market(self.db, 'c', end=300)
        self.assertEqual(query.call_args.args[1], 100)
        self.assertEqual(self.db.execute('SELECT checkpoint FROM markets').fetchone()[0], 200)
        self.assertEqual(self.db.execute('SELECT status FROM checks').fetchone()[0], 'failed')

    def test_full_page_splits_window(self):
        def fake(url, params):
            if params['start'] == 100 and params['end'] == 101:
                return [self.row] * recorder.PAGE
            return []
        with patch.object(recorder, 'CAP', 500), patch.object(recorder, 'get', side_effect=fake):
            self.assertEqual(recorder.fetch_window('c', 100, 101), [])

    def test_slug_uses_eastern_date_and_polymarket_codes(self):
        event = {'id': '123', 'date': '2026-10-28T00:00Z', 'competitions': [{'competitors': [
            {'homeAway': 'home', 'team': {'abbreviation': 'NY'}},
            {'homeAway': 'away', 'team': {'abbreviation': 'DET'}}]}]}
        game_id, slug, _, _, _ = recorder.schedule_game(event)
        self.assertEqual((game_id, slug), ('123', 'nba-det-nyk-2026-10-27'))

    def test_schedule_waits_and_imports_market(self):
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g','nba-det-nyk-2026-10-27',1000,'DET','NY','{}','pending',0)")
        self.db.commit()
        with patch.object(recorder, 'get', return_value=[]):
            recorder.check_scheduled(self.db, now=999)
        self.assertEqual(self.db.execute("SELECT status FROM schedule").fetchone()[0], 'pending')
        event = {'id': '10', 'slug': 'nba-det-nyk-2026-10-27', 'title': 'Pistons vs Knicks', 'createdAt': '2026-10-20T00:00:00Z', 'markets': [{'conditionId': 'new', 'question': 'Win?', 'sportsMarketType': 'moneyline'}]}
        with patch.object(recorder, 'get', return_value=[event]):
            recorder.check_scheduled(self.db, now=1000)
        self.assertEqual(self.db.execute('SELECT status FROM schedule').fetchone()[0], 'open')
        self.assertIsNotNone(self.db.execute("SELECT cid FROM markets WHERE cid='new'").fetchone())

    def test_only_full_game_markets_and_all_lines_saved(self):
        event = {'id': '10', 'slug': 'nba-det-nyk-2026-10-27', 'createdAt': '2026-10-20T00:00:00Z', 'markets': [
            {'conditionId': 'win', 'sportsMarketType': 'moneyline'},
            {'conditionId': 'spread1', 'sportsMarketType': 'spreads', 'line': -4.5},
            {'conditionId': 'spread2', 'sportsMarketType': 'spreads', 'line': -5.5},
            {'conditionId': 'total', 'sportsMarketType': 'totals', 'line': 221.5},
            {'conditionId': 'half', 'sportsMarketType': 'first_half_spreads'},
            {'conditionId': 'player', 'sportsMarketType': 'basketball_player_points'},
            {'conditionId': 'unknown'}]}
        recorder.save_event(self.db, event, 1)
        selected = {r[0] for r in self.db.execute("SELECT cid FROM markets WHERE event_id='10'")}
        self.assertEqual(selected, {'win', 'spread1', 'spread2', 'total'})
        snapshot = __import__('json').loads(self.db.execute("SELECT raw FROM events WHERE id='10'").fetchone()[0])
        self.assertEqual(len(snapshot['markets']), 4)
        self.assertFalse(recorder.tracked_market('{}'))

    def test_old_other_market_not_fetched(self):
        self.db.execute("UPDATE markets SET raw=? WHERE cid='c'", ('{"sportsMarketType":"first_half_spreads"}',))
        self.db.execute("INSERT INTO markets(cid,event_id,created_at,raw) VALUES('selected','e',100,?)", ('{"sportsMarketType":"totals"}',))
        self.db.execute("INSERT INTO system_status VALUES('schedule',?,NULL)", (int(recorder.time.time()),))
        self.db.execute("INSERT INTO system_status VALUES('maintenance',?,NULL)", (int(recorder.time.time()),))
        self.db.commit()
        with patch.object(recorder, 'discover'), patch.object(recorder, 'check_scheduled', return_value=0), patch.object(recorder, 'sync_market') as sync:
            recorder.run_once(self.db)
        self.assertEqual([call.args[1] for call in sync.call_args_list], ['selected'])
        self.assertIsNotNone(self.db.execute("SELECT cid FROM markets WHERE cid='c'").fetchone())

    def test_waits_until_eight_days_before_tipoff(self):
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g','nba-det-nyk-2026-10-27',1000000,'DET','NY','{}','pending',0)")
        self.db.commit()
        with patch.object(recorder, 'get', return_value=[]) as query:
            recorder.check_scheduled(self.db, now=1000000 - 8 * 86400 - 1)
            query.assert_not_called()
            recorder.check_scheduled(self.db, now=1000000 - 8 * 86400)
            query.assert_called_once()

    def test_network_error_preserves_schedule(self):
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g','nba-det-nyk-2026-10-27',1000,'DET','NY','{}','pending',0)")
        self.db.commit()
        with patch.object(recorder, 'get', side_effect=recorder.requests.ConnectionError('offline')):
            self.assertEqual(recorder.check_scheduled(self.db, now=999), 1)
        state, error = self.db.execute('SELECT status,last_error FROM schedule').fetchone()
        self.assertEqual(state, 'pending')
        self.assertIn('offline', error)

    def test_postponement_changes_candidate_without_deleting_old_market(self):
        event = {'id': 'g', 'date': '2026-10-28T00:00Z', 'competitions': [{'competitors': [
            {'homeAway': 'home', 'team': {'abbreviation': 'NY'}},
            {'homeAway': 'away', 'team': {'abbreviation': 'DET'}}]}]}
        response = unittest.mock.Mock()
        response.json.return_value = {'events': [event]}
        with patch.object(recorder.requests, 'get', return_value=response):
            recorder.refresh_schedule(self.db, now=1793000000)
            self.db.execute("UPDATE schedule SET status='open' WHERE game_id='g'")
            self.db.commit()
            event['date'] = '2026-10-29T00:00Z'
            recorder.refresh_schedule(self.db, now=1793000100)
        slug, state = self.db.execute("SELECT slug,status FROM schedule WHERE game_id='g'").fetchone()
        self.assertEqual((slug, state), ('nba-det-nyk-2026-10-28', 'pending'))
        self.assertIsNotNone(self.db.execute("SELECT cid FROM markets WHERE cid='c'").fetchone())

    def test_maintenance_removes_only_confirmed_expired_and_prevents_reimport(self):
        now = 2000000
        self.db.execute("INSERT INTO events VALUES('e','nba-det-nyk-2026-10-27','test','{}',0)")
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g','nba-det-nyk-2026-10-27',?,'DET','NY','{}','open',?)", (now - 86401, now))
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('new','nba-a-b-2026-10-28',?,'A','B','{}','pending',?)", (now - 86400, now))
        self.db.commit()
        event = {'slug': 'nba-det-nyk-2026-10-27', 'closed': True, 'markets': [{'conditionId': 'c', 'closed': True, 'umaResolutionStatus': 'resolved'}]}
        with patch.object(recorder, 'refresh_schedule'), patch.object(recorder, 'get', return_value=[event]):
            recorder.maintain(self.db, now)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM markets').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT game_id FROM schedule').fetchone()[0], 'new')
        self.assertEqual(self.db.execute('SELECT slug FROM retired_events').fetchone()[0], 'nba-det-nyk-2026-10-27')
        old_event = {'id': 'e', 'slug': 'nba-det-nyk-2026-10-27', 'title': 'old', 'markets': []}
        with patch.object(recorder, 'get', return_value=[old_event]):
            recorder.discover(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    def test_maintenance_preserves_unsettled_missing_and_failed(self):
        now = 2000000
        slug = 'nba-det-nyk-2026-10-27'
        self.db.execute("INSERT INTO events VALUES('e',?,'test','{}',0)", (slug,))
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g',?,?,'DET','NY','{}','open',?)", (slug, now - 86401, now))
        self.db.commit()
        samples = [
            [{'slug': slug, 'closed': True, 'markets': [{'conditionId': 'c', 'closed': True, 'umaResolutionStatus': 'proposed'}]}],
            [{'slug': slug, 'closed': True, 'markets': [{'conditionId': 'other', 'closed': True, 'umaResolutionStatus': 'resolved'}]}],
            recorder.requests.ConnectionError('offline'),
        ]
        for sample in samples:
            kwargs = {'side_effect': sample} if isinstance(sample, Exception) else {'return_value': sample}
            with patch.object(recorder, 'refresh_schedule'), patch.object(recorder, 'get', **kwargs):
                self.assertEqual(recorder.maintain(self.db, now), 0)
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM markets').fetchone()[0], 1)
            self.assertNotEqual(self.db.execute('SELECT result FROM maintenance_reviews').fetchone()[0], '已确认结算并清理')

    def test_failed_refresh_never_deletes_or_marks_success(self):
        self.db.execute("INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at) VALUES('g','nba-a-b-2026-10-27',100,'A','B','{}','pending',100)")
        self.db.commit()
        with patch.object(recorder, 'refresh_schedule', side_effect=recorder.requests.ConnectionError('offline')):
            with self.assertRaises(recorder.requests.ConnectionError):
                recorder.maintain(self.db, 2000000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM schedule').fetchone()[0], 1)
        self.assertIsNone(self.db.execute("SELECT last_success FROM system_status WHERE name='maintenance'").fetchone()[0])

    def test_maintenance_boundary_beijing_time(self):
        from datetime import datetime
        before = int(datetime(2026, 10, 27, 15, 29, tzinfo=recorder.BEIJING).timestamp())
        after = before + 60
        self.db.execute("INSERT INTO system_status VALUES('maintenance',?,NULL)", (before,))
        self.db.commit()
        self.assertFalse(recorder.maintenance_due(self.db, before))
        self.assertTrue(recorder.maintenance_due(self.db, after))


if __name__ == '__main__':
    unittest.main()
