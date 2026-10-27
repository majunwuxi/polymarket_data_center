"""NBA 日历：只读展示本地采集数据库。"""
import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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


def handler(db_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api/calendar':
                body = json.dumps(read_data(db_path), ensure_ascii=False).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            elif self.path in ('/', '/index.html'):
                body = (ROOT / 'dashboard.html').read_bytes()
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
