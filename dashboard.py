"""NBA 日历：只读展示本地采集数据库。"""
import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BEIJING = ZoneInfo('Asia/Shanghai')
TYPES = {'moneyline': '胜负', 'spreads': '让分', 'totals': '总分'}
TEAMS = {
    'ATL': ('Atlanta Hawks', '亚特兰大老鹰'), 'BOS': ('Boston Celtics', '波士顿凯尔特人'),
    'BKN': ('Brooklyn Nets', '布鲁克林篮网'), 'CHA': ('Charlotte Hornets', '夏洛特黄蜂'),
    'CHI': ('Chicago Bulls', '芝加哥公牛'), 'CLE': ('Cleveland Cavaliers', '克利夫兰骑士'),
    'DAL': ('Dallas Mavericks', '达拉斯独行侠'), 'DEN': ('Denver Nuggets', '丹佛掘金'),
    'DET': ('Detroit Pistons', '底特律活塞'), 'GS': ('Golden State Warriors', '金州勇士'),
    'HOU': ('Houston Rockets', '休斯敦火箭'), 'IND': ('Indiana Pacers', '印第安纳步行者'),
    'LAC': ('LA Clippers', '洛杉矶快船'), 'LAL': ('Los Angeles Lakers', '洛杉矶湖人'),
    'MEM': ('Memphis Grizzlies', '孟菲斯灰熊'), 'MIA': ('Miami Heat', '迈阿密热火'),
    'MIL': ('Milwaukee Bucks', '密尔沃基雄鹿'), 'MIN': ('Minnesota Timberwolves', '明尼苏达森林狼'),
    'NO': ('New Orleans Pelicans', '新奥尔良鹈鹕'), 'NY': ('New York Knicks', '纽约尼克斯'),
    'OKC': ('Oklahoma City Thunder', '俄克拉荷马城雷霆'), 'ORL': ('Orlando Magic', '奥兰多魔术'),
    'PHI': ('Philadelphia 76ers', '费城76人'), 'PHX': ('Phoenix Suns', '菲尼克斯太阳'),
    'POR': ('Portland Trail Blazers', '波特兰开拓者'), 'SAC': ('Sacramento Kings', '萨克拉门托国王'),
    'SA': ('San Antonio Spurs', '圣安东尼奥马刺'), 'TOR': ('Toronto Raptors', '多伦多猛龙'),
    'UTAH': ('Utah Jazz', '犹他爵士'), 'WSH': ('Washington Wizards', '华盛顿奇才'),
}
ALIASES = {'GSW': 'GS', 'NOP': 'NO', 'NYK': 'NY', 'SAS': 'SA', 'UTA': 'UTAH', 'WAS': 'WSH', 'PHO': 'PHX'}


def team_name(code, raw, side):
    canonical = ALIASES.get(code, code)
    if canonical in TEAMS:
        english, chinese = TEAMS[canonical]
        return {'en': english, 'zh': chinese}
    try:
        competitors = json.loads(raw)['competitions'][0]['competitors']
        english = next(item['team']['displayName'] for item in competitors if item['homeAway'] == side)
    except (ValueError, TypeError, KeyError, IndexError, StopIteration):
        english = code or 'Unknown team'
    return {'en': english, 'zh': '中文名称待确认'}


def event_url(slug):
    if not isinstance(slug, str) or not re.fullmatch(r'nba-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2}', slug):
        return None
    return 'https://polymarket.com/zh/sports/nba/' + slug


def read_data(path):
    path = Path(path).resolve()
    if not path.is_file():
        return {'games': [], 'message': '尚未找到数据库，请先运行采集程序。', 'schedule_updated': None}
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            schedules = db.execute('SELECT slug,tipoff,away,home,status,last_error,raw FROM schedule ORDER BY tipoff').fetchall()
            markets = db.execute('SELECT e.slug,m.raw,m.checkpoint,m.last_error FROM markets m JOIN events e ON e.id=m.event_id').fetchall()
            status = db.execute("SELECT last_success,last_error FROM system_status WHERE name='schedule'").fetchone()
        by_slug = {}
        for slug, raw, checkpoint, error in markets:
            try:
                kind = json.loads(raw).get('sportsMarketType')
            except (ValueError, TypeError, AttributeError):
                continue
            if kind not in TYPES:
                continue
            data = by_slug.setdefault(slug, {'counts': {key: 0 for key in TYPES}, 'checked': [], 'errors': 0})
            data['counts'][kind] += 1
            if checkpoint is not None:
                data['checked'].append(checkpoint)
            if error:
                data['errors'] += 1
        games = []
        for slug, tipoff, away, home, state, error, raw in schedules:
            when = datetime.fromtimestamp(tipoff, BEIJING)
            data = by_slug.get(slug, {'counts': {key: 0 for key in TYPES}, 'checked': [], 'errors': 0})
            games.append({'slug': slug, 'date': when.strftime('%Y-%m-%d'), 'time': when.strftime('%H:%M'), 'away': team_name(away, raw, 'away'), 'home': team_name(home, raw, 'home'), 'url': event_url(slug), 'status': state, 'error': error, 'market_counts': data['counts'], 'last_checked': min(data['checked']) if data['checked'] else None, 'market_errors': data['errors']})
        return {'games': games, 'message': status[1] if status and status[1] else None, 'schedule_updated': status[0] if status else None}
    except (sqlite3.Error, OSError, ValueError, OverflowError) as exc:
        return {'games': [], 'message': '数据库读取失败：' + str(exc), 'schedule_updated': None}


def read_game(path, slug, kind='all', offset=0, limit=50):
    if not event_url(slug) or kind not in ('all', *TYPES) or offset < 0 or not 1 <= limit <= 100:
        return {'error': '比赛地址或查询参数无效。'}
    data = read_data(path)
    game = next((item for item in data['games'] if item['slug'] == slug), None)
    if not game:
        return {'error': data['message'] or '找不到该比赛；赛程可能尚未保存或比赛数据已清理。'}
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT m.cid,m.question,m.raw,m.checkpoint,m.last_error FROM markets m JOIN events e ON e.id=m.event_id WHERE e.slug=? ORDER BY m.question,m.cid', (slug,)).fetchall()
            markets = []
            for cid, question, raw, checkpoint, error in rows:
                try:
                    m = json.loads(raw)
                    market_type = m.get('sportsMarketType')
                except (ValueError, TypeError, AttributeError):
                    continue
                if market_type not in TYPES:
                    continue
                markets.append({'cid': cid, 'question': question or '未命名盘口', 'type': market_type, 'line': m.get('line'), 'checkpoint': checkpoint, 'error': error})
            selected = [m['cid'] for m in markets if kind == 'all' or m['type'] == kind]
            trades = []
            total = 0
            if selected:
                placeholders = ','.join('?' for _ in selected)
                where = 'cid IN (' + placeholders + ')'
                total = db.execute('SELECT COUNT(*) FROM trades WHERE ' + where, selected).fetchone()[0]
                q = 'SELECT cid,timestamp,first_seen,wallet,side,outcome,price,size,tx_hash FROM trades WHERE ' + where + ' ORDER BY timestamp DESC, fingerprint, occurrence LIMIT ? OFFSET ?'
                for cid, ts, seen, wallet, side, outcome, price, size, tx in db.execute(q, [*selected, limit, offset]):
                    try:
                        amount = str(Decimal(price) * Decimal(size))
                    except (InvalidOperation, TypeError, ValueError):
                        amount = None
                    trades.append({'cid': cid, 'timestamp': ts, 'first_seen': seen, 'wallet': wallet, 'side': side, 'outcome': outcome, 'price': price, 'size': size, 'amount': amount, 'tx_hash': tx})
        return {'game': game, 'markets': markets, 'trades': trades, 'total': total, 'offset': offset, 'limit': limit}
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {'error': '读取比赛数据失败：' + str(exc)}


def read_summary(path, slug, kind='all'):
    result = read_game(path, slug, kind=kind, limit=1)
    if 'error' in result:
        return result
    markets = [m for m in result['markets'] if kind == 'all' or m['type'] == kind]
    stats = {m['cid']: {'records': 0, 'wallets': set(), 'invalid': 0, 'unknown_side': 0, 'outcomes': {}, 'latest': None} for m in markets}
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT t.cid,t.wallet,t.side,t.outcome,t.price,t.size,t.timestamp FROM trades t JOIN markets m ON t.cid=m.cid JOIN events e ON m.event_id=e.id WHERE e.slug=?', (slug,))
            for cid, wallet, side, outcome, price, size, ts in rows:
                if cid not in stats:
                    continue
                item = stats[cid]
                item['records'] += 1
                if wallet:
                    item['wallets'].add(wallet.lower())
                if ts is not None and (item['latest'] is None or ts > item['latest']):
                    item['latest'] = ts
                label = outcome or '结果未知'
                group = item['outcomes'].setdefault(label, {'buy': Decimal(0), 'sell': Decimal(0), 'buy_count': 0, 'sell_count': 0, 'invalid': 0})
                if side not in ('BUY', 'SELL'):
                    item['unknown_side'] += 1
                    continue
                try:
                    p, n = Decimal(price), Decimal(size)
                    if not p.is_finite() or not n.is_finite() or p < 0 or n < 0:
                        raise ValueError('无效金额')
                    amount = p * n
                except (InvalidOperation, TypeError, ValueError):
                    item['invalid'] += 1
                    group['invalid'] += 1
                    continue
                key = 'buy' if side == 'BUY' else 'sell'
                group[key] += amount
                group[key + '_count'] += 1
        for market in markets:
            item = stats[market['cid']]
            market['records'] = item['records']
            market['wallet_count'] = len(item['wallets'])
            market['invalid'] = item['invalid']
            market['unknown_side'] = item['unknown_side']
            market['latest'] = item['latest']
            market['outcomes'] = [{'name': name, 'buy': str(group['buy']), 'sell': str(group['sell']), 'net': str(group['buy'] - group['sell']), 'buy_count': group['buy_count'], 'sell_count': group['sell_count'], 'invalid': group['invalid']} for name, group in sorted(item['outcomes'].items())]
        return {'game': result['game'], 'markets': markets}
    except (sqlite3.Error, OSError, ValueError) as exc:
        return {'error': '读取盘口汇总失败：' + str(exc)}


def handler(db_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parts = urlsplit(self.path)
            if parts.path.startswith('/api/summary/'):
                query = parse_qs(parts.query)
                result = read_summary(db_path, parts.path[len('/api/summary/'):], query.get('type', ['all'])[0])
                body = json.dumps(result, ensure_ascii=False).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            elif parts.path.startswith('/api/game/'):
                query = parse_qs(parts.query)
                try:
                    result = read_game(db_path, parts.path[len('/api/game/'):], query.get('type', ['all'])[0], int(query.get('offset', ['0'])[0]))
                except ValueError:
                    result = {'error': '查询参数无效。'}
                body = json.dumps(result, ensure_ascii=False).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            elif parts.path == '/api/calendar':
                body = json.dumps(read_data(db_path), ensure_ascii=False).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            elif parts.path in ('/', '/index.html'):
                body = (ROOT / 'dashboard.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            elif parts.path == '/game':
                body = (ROOT / 'game.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='nba_trades.sqlite3')
    parser.add_argument('--port', type=int, default=8068)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(args.db))
    print(f'日历地址：http://127.0.0.1:{args.port}  按 Ctrl+C 停止。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
