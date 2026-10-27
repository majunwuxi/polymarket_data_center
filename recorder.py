"""NBA 公开交易采集基础：采集身份和覆盖不能保证完整。"""
import collections
import argparse
import hashlib
import json
import logging
import sqlite3
import time
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

GAMMA = 'https://gamma-api.polymarket.com'
DATA = 'https://data-api.polymarket.com'
PAGE = 500
CAP = 10000
OVERLAP = 900
SCHEDULE_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
EASTERN = ZoneInfo('America/New_York')
BEIJING = ZoneInfo('Asia/Shanghai')
TEAM_CODES = {'NY': 'nyk', 'SA': 'sas', 'GS': 'gsw', 'NO': 'nop', 'WSH': 'was', 'UTAH': 'uta', 'PHO': 'phx'}
MARKET_TYPES = frozenset({'moneyline', 'spreads', 'totals'})


def get(url, params):
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError('接口没有返回列表')
    return data


def connect(path):
    db = sqlite3.connect(path)
    db.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, slug TEXT, title TEXT, raw TEXT NOT NULL, updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS markets(cid TEXT PRIMARY KEY, event_id TEXT NOT NULL, question TEXT, created_at INTEGER NOT NULL, raw TEXT NOT NULL, checkpoint INTEGER, last_error TEXT);
    CREATE TABLE IF NOT EXISTS trades(fingerprint TEXT NOT NULL, occurrence INTEGER NOT NULL, cid TEXT NOT NULL, timestamp INTEGER NOT NULL, first_seen INTEGER NOT NULL, wallet TEXT, side TEXT, outcome TEXT, asset TEXT, price TEXT, size TEXT, tx_hash TEXT, raw TEXT NOT NULL, identity_uncertain INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(fingerprint, occurrence));
    CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, cid TEXT, started_at INTEGER, range_start INTEGER, range_end INTEGER, status TEXT, error TEXT, record_count INTEGER);
    CREATE TABLE IF NOT EXISTS schedule(game_id TEXT PRIMARY KEY, slug TEXT NOT NULL, tipoff INTEGER NOT NULL, away TEXT NOT NULL, home TEXT NOT NULL, raw TEXT NOT NULL, status TEXT NOT NULL, last_checked INTEGER, last_error TEXT, updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS system_status(name TEXT PRIMARY KEY, last_success INTEGER, last_error TEXT);
    CREATE TABLE IF NOT EXISTS retired_events(slug TEXT PRIMARY KEY, retired_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS maintenance_reviews(slug TEXT PRIMARY KEY, checked_at INTEGER NOT NULL, result TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS trade_market_time ON trades(cid, timestamp);
    ''')
    return db


def parse_time(value):
    if not value:
        return 0
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())


def save_event(db, event, now):
    eid = str(event['id'])
    slug = event.get('slug', '')
    selected = [market for market in event.get('markets', []) if isinstance(market, dict) and market.get('sportsMarketType') in MARKET_TYPES]
    snapshot = dict(event, markets=selected)
    db.execute('INSERT INTO events VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET slug=excluded.slug,title=excluded.title,raw=excluded.raw,updated_at=excluded.updated_at', (eid, slug, event.get('title'), json.dumps(snapshot, ensure_ascii=False), now))
    for market in selected:
        cid = market.get('conditionId')
        if not cid:
            continue
        created = parse_time(market.get('createdAt') or event.get('createdAt'))
        db.execute('INSERT INTO markets(cid,event_id,question,created_at,raw) VALUES(?,?,?,?,?) ON CONFLICT(cid) DO UPDATE SET question=excluded.question,raw=excluded.raw', (cid, eid, market.get('question'), created, json.dumps(market, ensure_ascii=False)))


def tracked_market(raw):
    try:
        market = json.loads(raw)
        return isinstance(market, dict) and market.get('sportsMarketType') in MARKET_TYPES
    except (TypeError, ValueError):
        return False


def discover(db):
    offset = 0
    now = int(time.time())
    while True:
        events = get(GAMMA + '/events', {'tag_id': 745, 'active': 'true', 'closed': 'false', 'limit': 100, 'offset': offset})
        with db:
            for event in events:
                slug = event.get('slug', '')
                if not re.fullmatch(r'nba-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2}', slug):
                    continue
                if db.execute('SELECT 1 FROM retired_events WHERE slug=?', (slug,)).fetchone():
                    continue
                save_event(db, event, now)
        if len(events) < 100:
            return
        offset += 100


def schedule_game(event):
    """根据赛程生成候选地址；日期采用美国东部时间。"""
    tipoff = parse_time(event['date'])
    teams = {entry['homeAway']: entry['team']['abbreviation'] for entry in event['competitions'][0]['competitors']}
    away, home = teams['away'], teams['home']
    def code(value):
        if not re.fullmatch(r'[A-Z]{2,4}', value):
            raise ValueError('赛程球队缩写无效')
        return TEAM_CODES.get(value, value.lower())
    date = datetime.fromtimestamp(tipoff, EASTERN).strftime('%Y-%m-%d')
    return str(event['id']), f'nba-{code(away)}-{code(home)}-{date}', tipoff, away, home


def refresh_schedule(db, now=None):
    now = int(time.time()) if now is None else now
    today = datetime.fromtimestamp(now, EASTERN).date()
    games = []
    try:
        dates = {today + timedelta(days=day) for day in range(-2, 10)}
        # 离线多天后仍需核验以前保存的比赛，不能只查最近两天。
        dates.update(datetime.fromtimestamp(row[0], EASTERN).date() for row in db.execute('SELECT tipoff FROM schedule'))
        for scheduled_date in sorted(dates):
            date = scheduled_date.strftime('%Y%m%d')
            response = requests.get(SCHEDULE_URL, params={'dates': date, 'limit': 100}, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
                raise ValueError('赛程接口返回格式不正确')
            games.extend(payload['events'])
        with db:
            for event in games:
                game_id, slug, tipoff, away, home = schedule_game(event)
                if db.execute('SELECT 1 FROM retired_events WHERE slug=?', (slug,)).fetchone():
                    continue
                db.execute('''INSERT INTO schedule(game_id,slug,tipoff,away,home,raw,status,updated_at)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET
                    status=CASE WHEN schedule.slug != excluded.slug THEN 'pending' ELSE schedule.status END,
                    slug=excluded.slug,tipoff=excluded.tipoff,away=excluded.away,home=excluded.home,
                    raw=excluded.raw,updated_at=excluded.updated_at''',
                    (game_id, slug, tipoff, away, home, json.dumps(event, ensure_ascii=False), 'pending', now))
            db.execute("INSERT INTO system_status VALUES('schedule',?,NULL) ON CONFLICT(name) DO UPDATE SET last_success=excluded.last_success,last_error=NULL", (now,))
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        with db:
            db.execute("INSERT INTO system_status(name,last_error) VALUES('schedule',?) ON CONFLICT(name) DO UPDATE SET last_error=excluded.last_error", (str(exc),))
        raise


def check_scheduled(db, now=None):
    now = int(time.time()) if now is None else now
    candidates = db.execute('SELECT game_id,slug FROM schedule WHERE tipoff<=? AND tipoff>=?', (now + 8 * 86400, now - 2 * 86400)).fetchall()
    failures = 0
    for game_id, slug in candidates:
        try:
            events = get(GAMMA + '/events', {'slug': slug})
            matches = [event for event in events if event.get('slug') == slug]
            if len(matches) > 1:
                raise ValueError('候选地址返回多个事件')
            with db:
                if matches:
                    save_event(db, matches[0], now)
                db.execute('UPDATE schedule SET status=?,last_checked=?,last_error=NULL WHERE game_id=?', ('open' if matches else 'pending', now, game_id))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            failures += 1
            with db:
                db.execute('UPDATE schedule SET last_checked=?,last_error=? WHERE game_id=?', (now, str(exc), game_id))
    return failures


def maintenance_due(db, now):
    local = datetime.fromtimestamp(now, BEIJING)
    scheduled = local.replace(hour=15, minute=30, second=0, microsecond=0)
    if local < scheduled:
        scheduled -= timedelta(days=1)
    row = db.execute("SELECT last_success FROM system_status WHERE name='maintenance'").fetchone()
    return not row or row[0] is None or row[0] < int(scheduled.timestamp())


def settlement_check(db, slug):
    events = get(GAMMA + '/events', {'slug': slug})
    matching = [event for event in events if event.get('slug') == slug]
    if len(matching) != 1:
        return '无法确认唯一的 Polymarket 事件'
    event = matching[0]
    if event.get('closed') is not True:
        return 'Polymarket 事件未明确关闭'
    markets = event.get('markets')
    if not isinstance(markets, list) or not markets:
        return 'Polymarket 未返回市场列表'
    ids = [market.get('conditionId') for market in markets if isinstance(market, dict)]
    if len(ids) != len(markets) or not all(ids) or len(ids) != len(set(ids)):
        return 'Polymarket 市场标识缺失或重复'
    known = {row[0] for row in db.execute('SELECT m.cid FROM markets m JOIN events e ON m.event_id=e.id WHERE e.slug=?', (slug,))}
    if not known.issubset(ids):
        return 'Polymarket 返回的市场未覆盖本地已记录市场'
    if any(market.get('closed') is not True or market.get('umaResolutionStatus') != 'resolved' for market in markets):
        return '至少一个市场未明确结算'
    return None


def maintain(db, now=None):
    """先核验赛程，再删除到期数据，压缩成功后才记录完成。"""
    now = int(time.time()) if now is None else now
    try:
        refresh_schedule(db, now)
        due = db.execute('SELECT game_id,slug FROM schedule WHERE tipoff < ? AND updated_at = ?', (now - 86400, now)).fetchall()
        reviews = []
        for game_id, slug in due:
            if db.execute('SELECT COUNT(*) FROM schedule WHERE slug=?', (slug,)).fetchone()[0] != 1:
                reviews.append((game_id, slug, '多个赛程对应同一地址'))
                continue
            try:
                reason = settlement_check(db, slug)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                reason = f'结算查询失败: {exc}'
            reviews.append((game_id, slug, reason))
        removed = 0
        with db:
            for game_id, slug, reason in reviews:
                db.execute('INSERT INTO maintenance_reviews VALUES(?,?,?) ON CONFLICT(slug) DO UPDATE SET checked_at=excluded.checked_at,result=excluded.result', (slug, now, reason or '已确认结算并清理'))
                if reason:
                    continue
                db.execute('INSERT OR IGNORE INTO retired_events VALUES(?,?)', (slug, now))
                db.execute('DELETE FROM trades WHERE cid IN (SELECT m.cid FROM markets m JOIN events e ON m.event_id=e.id WHERE e.slug=?)', (slug,))
                db.execute('DELETE FROM checks WHERE cid IN (SELECT m.cid FROM markets m JOIN events e ON m.event_id=e.id WHERE e.slug=?)', (slug,))
                db.execute('DELETE FROM markets WHERE event_id IN (SELECT id FROM events WHERE slug=?)', (slug,))
                db.execute('DELETE FROM events WHERE slug=?', (slug,))
                db.execute('DELETE FROM schedule WHERE game_id=?', (game_id,))
                removed += 1
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.execute('VACUUM')
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        with db:
            db.execute("INSERT INTO system_status VALUES('maintenance',?,NULL) ON CONFLICT(name) DO UPDATE SET last_success=excluded.last_success,last_error=NULL", (now,))
        return removed
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as exc:
        with db:
            db.execute("INSERT INTO system_status(name,last_error) VALUES('maintenance',?) ON CONFLICT(name) DO UPDATE SET last_error=excluded.last_error", (str(exc),))
        raise


def fingerprint(row):
    keys = ('transactionHash', 'conditionId', 'asset', 'proxyWallet', 'timestamp', 'side', 'outcome', 'price', 'size')
    raw = json.dumps([row.get(k) for k in keys], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def fetch_window(cid, start, end):
    """闭区间，达到分页上限则拆分；单秒超限时报告失败。"""
    rows = []
    for offset in range(0, CAP, PAGE):
        page = get(DATA + '/trades', {'market': cid, 'limit': PAGE, 'offset': offset, 'takerOnly': 'false', 'start': start, 'end': end})
        rows.extend(page)
        if len(page) < PAGE:
            return rows
    if start >= end:
        raise RuntimeError(f'单秒成交达到分页上限: {start}')
    middle = (start + end) // 2
    return fetch_window(cid, start, middle) + fetch_window(cid, middle + 1, end)


def sync_market(db, cid, end=None, overlap=OVERLAP, full=False):
    now = int(time.time())
    end = now if end is None else end
    item = db.execute('SELECT created_at,checkpoint FROM markets WHERE cid=?', (cid,)).fetchone()
    if item is None:
        raise ValueError('未知市场')
    created, checkpoint = item
    start = created if full or checkpoint is None else max(created, checkpoint - overlap)
    if start <= 0:
        raise ValueError('缺少市场创建时间，不能安全确定历史起点')
    if end < start:
        return 0
    try:
        rows = fetch_window(cid, start, end)
        occurrences = collections.Counter()
        with db:
            for row in rows:
                if row.get('conditionId') != cid or not isinstance(row.get('timestamp'), int) or not start <= row['timestamp'] <= end:
                    raise ValueError('接口返回了范围外或格式不正确的成交')
                fp = fingerprint(row)
                occurrences[fp] += 1
                db.execute('INSERT OR IGNORE INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (fp, occurrences[fp], cid, row['timestamp'], now, row.get('proxyWallet'), row.get('side'), row.get('outcome'), row.get('asset'), str(row.get('price')), str(row.get('size')), row.get('transactionHash'), json.dumps(row, ensure_ascii=False, separators=(',', ':')), 1))
            db.execute('UPDATE markets SET checkpoint=MAX(COALESCE(checkpoint,0),?),last_error=NULL WHERE cid=?', (end, cid))
            db.execute('INSERT INTO checks(cid,started_at,range_start,range_end,status,record_count) VALUES(?,?,?,?,?,?)', (cid, now, start, end, 'success', len(rows)))
        return len(rows)
    except Exception as exc:
        with db:
            db.execute('UPDATE markets SET last_error=? WHERE cid=?', (str(exc), cid))
            db.execute('INSERT INTO checks(cid,started_at,range_start,range_end,status,error) VALUES(?,?,?,?,?,?)', (cid, now, start, end, 'failed', str(exc)))
        raise


def run_once(db, full=False):
    failures = 0
    last = db.execute("SELECT last_success FROM system_status WHERE name='schedule'").fetchone()
    if not last or not last[0] or time.time() - last[0] >= 6 * 3600:
        try:
            refresh_schedule(db)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            failures += 1
            logging.error('赛程刷新失败: %s', exc)
    failures += check_scheduled(db)
    try:
        discover(db)
    except (requests.RequestException, ValueError) as exc:
        failures += 1
        logging.error('标签发现失败: %s', exc)
    end = int(time.time())
    markets = db.execute('SELECT cid,raw FROM markets ORDER BY COALESCE(checkpoint,0)').fetchall()
    for cid, raw in markets:
        if not tracked_market(raw):
            continue
        if maintenance_due(db, int(time.time())):
            return None
        try:
            sync_market(db, cid, end=end, full=full)
        except (requests.RequestException, ValueError, RuntimeError, sqlite3.Error) as exc:
            failures += 1
            logging.error('%s: %s', cid, exc)
    return failures


def show_status(db):
    print('注意：检查成功不等于数据完整，成交身份仍有不确定性。')
    excluded = sum(not tracked_market(row[0]) for row in db.execute('SELECT raw FROM markets'))
    if excluded:
        print(f'旧数据库中有 {excluded} 个其他或类型不明的市场，已停止采集，原有数据仍保留。')
    maintenance = db.execute("SELECT last_success,last_error FROM system_status WHERE name='maintenance'").fetchone()
    print(f'维护最近成功时间戳/错误: {maintenance if maintenance else "尚未维护"}')
    for slug, checked, result in db.execute("SELECT slug,checked_at,result FROM maintenance_reviews WHERE result != '已确认结算并清理' ORDER BY checked_at DESC"):
        print(f'  清理暂缓 {slug}: {result}（检查时间戳 {checked}）')
    info = db.execute("SELECT last_success,last_error FROM system_status WHERE name='schedule'").fetchone()
    print(f'赛程最近成功刷新时间戳/错误: {info if info else "尚未刷新"}')
    for slug, tipoff, state, error in db.execute('SELECT slug,tipoff,status,last_error FROM schedule ORDER BY tipoff'):
        formatted = datetime.fromtimestamp(tipoff, EASTERN).strftime('%Y-%m-%d %H:%M %Z')
        print(f'  赛程 {slug} 开赛 {formatted} 状态 {state} 错误 {error or "无"}')
    for slug, title, markets, count, low, high, errors in db.execute('''SELECT e.slug,e.title,COUNT(DISTINCT m.cid),COUNT(t.occurrence),MIN(m.checkpoint),MAX(m.checkpoint),COUNT(DISTINCT CASE WHEN m.last_error IS NOT NULL THEN m.cid END) FROM events e JOIN markets m ON m.event_id=e.id LEFT JOIN trades t ON t.cid=m.cid GROUP BY e.id ORDER BY e.slug'''):
        print(f'{slug} {title}: 项目 {markets}, 成交记录 {count}, 最早/最晚检查点 {low}/{high}, 失败项目 {errors}')
    for cid, error in db.execute('SELECT cid,last_error FROM markets WHERE last_error IS NOT NULL'):
        print(f'  {cid}: {error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='nba_trades.sqlite3')
    parser.add_argument('--interval', type=int, default=180)
    parser.add_argument('--full-review-hours', type=float, default=24)
    parser.add_argument('command', choices=['run', 'once', 'status'])
    args = parser.parse_args()
    if args.interval <= 0 or args.full_review_hours <= 0:
        parser.error('时间间隔必须为正数')
    db = connect(args.db)
    if args.command == 'status':
        show_status(db)
        return
    if args.command == 'once':
        try:
            if maintenance_due(db, int(time.time())):
                maintain(db)
            result = run_once(db)
            raise SystemExit(1 if result is None or result else 0)
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as exc:
            logging.error('维护失败: %s', exc)
            raise SystemExit(1) from exc
    next_review = time.monotonic() + args.full_review_hours * 3600
    while True:
        begin = time.monotonic()
        try:
            if maintenance_due(db, int(time.time())):
                try:
                    count = maintain(db)
                    logging.info('维护完成，清理候选比赛 %s 场', count)
                except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as exc:
                    logging.error('维护失败，本轮不启动采集，稍后重试: %s', exc)
                    time.sleep(args.interval)
                    continue
            review = time.monotonic() >= next_review
            failures = run_once(db, full=review)
            if failures is None:
                continue
            if review and not failures:
                next_review = time.monotonic() + args.full_review_hours * 3600
        except (requests.RequestException, ValueError, sqlite3.Error) as exc:
            logging.error('本轮发现或采集失败: %s', exc)
        time.sleep(max(1, args.interval - (time.monotonic() - begin)))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        main()
    except KeyboardInterrupt:
        print('\n已停止。')
