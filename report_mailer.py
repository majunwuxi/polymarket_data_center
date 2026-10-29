"""Send a next-day NBA net-buy report from the local Polymarket database."""
import argparse
import html
import os
import smtplib
import sqlite3
from datetime import datetime, time, timedelta
from decimal import Decimal
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from zoneinfo import ZoneInfo

import dashboard

BEIJING = ZoneInfo('Asia/Shanghai')


def next_day_window(now=None):
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    tomorrow = now.date() + timedelta(days=1)
    start = datetime.combine(tomorrow, time.min, BEIJING)
    return tomorrow, int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def load_games(db_path, now=None):
    report_date, start, end = next_day_window(now)
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'数据库不存在：{path}')
    uri = path.as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        games = db.execute(
            'SELECT slug,tipoff,away,home,status,last_error,raw FROM schedule '
            'WHERE tipoff>=? AND tipoff<? ORDER BY tipoff,slug', (start, end)
        ).fetchall()
        schedule_status = db.execute(
            "SELECT last_success,last_error FROM system_status WHERE name='schedule'"
        ).fetchone()
    result = []
    for slug, tipoff, away, home, status, error, raw in games:
        summary = dashboard.read_summary(path, slug)
        if 'error' in summary:
            raise RuntimeError(f'{slug} 汇总失败：{summary["error"]}')
        result.append({
            'slug': slug, 'tipoff': tipoff, 'away': away, 'home': home,
            'status': status, 'schedule_error': error, 'raw': raw,
            'markets': summary['markets'],
        })
    status = {'last_success': schedule_status[0], 'last_error': schedule_status[1]} if schedule_status else {'last_success': None, 'last_error': None}
    return report_date, result, status


def outcome_label(name, teams, market_type):
    if market_type == 'totals':
        if name.lower() == 'over':
            return '大于（Over）'
        if name.lower() == 'under':
            return '小于（Under）'
    for team in teams.values():
        if name == team['en'] or team['en'].endswith(' ' + name):
            return team['zh']
    return name


def money(value):
    value = Decimal(value)
    sign = '-' if value < 0 else ''
    return f'{sign}${abs(value):,.2f}'


def market_title(market):
    line = market.get('line')
    question = market.get('question') or '未命名盘口'
    if line is not None and str(line).strip():
        return f'总分 {line}'
    return question


def result_rows(game, market_type, teams):
    groups = []
    for market in game['markets']:
        if market['type'] != market_type:
            continue
        outcomes = market.get('outcomes', [])
        valid = [o for o in outcomes if o['buy_count'] + o['sell_count'] > 0]
        values = [Decimal(o['net']) for o in valid]
        top = max(values) if values else None
        entries = []
        for outcome in outcomes:
            has_data = outcome['buy_count'] + outcome['sell_count'] > 0
            amount = Decimal(outcome['net'])
            entries.append({
                'name': outcome_label(outcome['name'], teams, market_type),
                'net': amount if has_data else None,
                'highlight': has_data and top is not None and amount == top,
            })
        groups.append({'title': market_title(market) if market_type == 'totals' else market.get('question') or '全场胜负', 'entries': entries,
                       'checkpoint': market.get('checkpoint'), 'error': market.get('error')})
    return groups


def render_report(report_date, games, schedule_status=None, generated_at=None):
    generated_at = (generated_at or datetime.now(BEIJING)).astimezone(BEIJING)
    style = '''
      body{margin:0;background:#f3f6fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Microsoft YaHei",sans-serif}
      .wrap{max-width:900px;margin:24px auto;padding:0 16px}.head{background:#15243b;color:#fff;padding:24px 28px;border-radius:16px}
      h1{font-size:24px;margin:0 0 8px}.muted{color:#9eacc1;font-size:13px}.game{background:#fff;border:1px solid #e4eaf2;border-radius:14px;padding:20px;margin-top:16px}
      h2{font-size:19px;margin:0 0 5px}.section{margin-top:20px}.section h3{font-size:14px;color:#607089;margin:0 0 9px}
      .market{border:1px solid #e7edf4;border-radius:10px;margin:8px 0;padding:12px}.market-title{font-size:13px;font-weight:700;margin-bottom:8px;color:#44536b}
      .outcomes{width:100%;border-collapse:separate;border-spacing:8px 0}.value{background:#f3f6fa;border-radius:8px;padding:10px 13px;min-width:130px;vertical-align:top}
      .name{font-size:12px;color:#66758b}.amount{font-size:17px;font-weight:600;margin-top:4px}.winner{background:#fff0bf;border:2px solid #e6ae23;padding:9px 12px}.winner .amount{font-size:23px;font-weight:800;color:#694700}
      .note{font-size:12px;color:#6b7789;line-height:1.6}.warn{color:#9a4b00}.empty{padding:12px;background:#f7f8fa;border-radius:8px;color:#6b7789}
      a{color:#2859a6;text-decoration:none}.footer{margin:18px 3px;font-size:12px;color:#6b7789;line-height:1.7}
    '''
    parts = [f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{style}</style></head><body><main class="wrap">',
             f'<header class="head"><h1>NBA 次日盘口净买入统计</h1><div>比赛日期：{report_date:%Y年%m月%d日}（北京时间）</div><div class="muted">生成时间：{generated_at:%Y-%m-%d %H:%M:%S} 北京时间</div>']
    plain = [f'NBA 次日盘口净买入统计｜{report_date:%Y-%m-%d}', f'生成时间：{generated_at:%Y-%m-%d %H:%M:%S} 北京时间']
    if schedule_status and schedule_status['last_success']:
        refreshed = datetime.fromtimestamp(schedule_status['last_success'], BEIJING).strftime('%Y-%m-%d %H:%M:%S')
        parts.append(f'<div class="muted">赛程最近成功刷新：{refreshed} 北京时间</div>')
        plain.append(f'赛程最近成功刷新：{refreshed} 北京时间')
    if schedule_status and schedule_status['last_error']:
        parts.append(f'<div class="muted warn">赛程刷新错误：{html.escape(schedule_status["last_error"])}</div>')
        plain.append('赛程刷新错误：' + schedule_status['last_error'])
    parts.append('</header>')
    plain.append('')
    if not games:
        parts.append('<section class="game"><div class="empty">未找到次日赛程。赛程可能尚未刷新。</div></section>')
        plain.append('未找到次日赛程。赛程可能尚未刷新。')
    for game in games:
        away = dashboard.team_name(game['away'], game['raw'], 'away')
        home = dashboard.team_name(game['home'], game['raw'], 'home')
        teams = {'away': away, 'home': home}
        title = f"{away['zh']} vs {home['zh']}"
        url = dashboard.event_url(game['slug'])
        parts.append(f'<section class="game"><h2>{html.escape(title)}</h2><div class="note">{datetime.fromtimestamp(game["tipoff"], BEIJING):%H:%M} 开赛 · {html.escape(game["status"])} · <a href="{html.escape(url or "#", quote=True)}">Polymarket 比赛页</a></div>')
        plain += [title, f"{datetime.fromtimestamp(game['tipoff'], BEIJING):%H:%M} 开赛 · {game['status']} · {url or ''}"]
        if game['schedule_error']:
            parts.append(f'<p class="note warn">赛程检查异常：{html.escape(game["schedule_error"])}</p>')
            plain.append('赛程检查异常：' + game['schedule_error'])
        for kind, heading in (('moneyline', '全场胜负 Moneyline'), ('totals', '全场总分 Totals')):
            groups = result_rows(game, kind, teams)
            parts.append(f'<div class="section"><h3>{heading}</h3>')
            plain.append(heading)
            if not groups:
                parts.append('<div class="empty">尚未发现对应盘口。</div>')
                plain.append('尚未发现对应盘口。')
            for group in groups:
                parts.append(f'<div class="market"><div class="market-title">{html.escape(group["title"])}</div><table role="presentation" class="outcomes"><tr>')
                plain.append(group['title'])
                if not group['entries']:
                    parts.append('<td colspan="2" class="empty" style="padding:12px;background:#f7f8fa;border-radius:8px;color:#6b7789">暂无有效成交数据。</td>')
                    plain.append('暂无有效成交数据。')
                for entry in group['entries']:
                    cls = 'value winner' if entry['highlight'] else 'value'
                    amount = money(entry['net']) if entry['net'] is not None else '暂无数据'
                    if entry['highlight']:
                        parts.append(f'<td class="{cls}" style="background:#fff0bf;border:2px solid #e6ae23;border-radius:8px;padding:9px 12px;vertical-align:top"><div style="font-size:12px;color:#66758b">{html.escape(entry["name"])}</div><strong style="display:block;font-size:23px;line-height:1.35;color:#694700">{amount}</strong></td>')
                    else:
                        parts.append(f'<td class="{cls}" style="background:#f3f6fa;border-radius:8px;padding:10px 13px;vertical-align:top"><div style="font-size:12px;color:#66758b">{html.escape(entry["name"])}</div><div style="font-size:17px;font-weight:600;margin-top:4px">{amount}</div></td>')
                    plain.append(f"  {entry['name']}: {amount}" + ('（最高）' if entry['highlight'] else ''))
                parts.append('</tr></table>')
                if group['checkpoint'] is not None:
                    checked = datetime.fromtimestamp(group['checkpoint'], BEIJING).strftime('%Y-%m-%d %H:%M:%S')
                    parts.append(f'<div class="note">该盘口检查点：{checked} 北京时间</div>')
                    plain.append(f'检查点：{checked} 北京时间')
                if group['error']:
                    parts.append(f'<div class="note warn">采集异常：{html.escape(group["error"])}</div>')
                    plain.append('采集异常：' + group['error'])
                parts.append('</div>')
            parts.append('</div>')
        parts.append('</section>')
        plain.append('')
    parts.append('<footer class="footer">净买入金额 = 已记录买入金额 − 已记录卖出金额，金额按成交价格 × 份数估算。该统计受数据采集覆盖和成交身份不确定性影响，不代表当前持仓或 Polymarket 官方成交额。</footer></main></body></html>')
    plain += ['', '净买入金额 = 已记录买入金额 − 已记录卖出金额，金额按成交价格 × 份数估算。该统计受采集覆盖和成交身份不确定性影响，不代表当前持仓或官方成交额。']
    return '\n'.join(parts), '\n'.join(plain)


def required_env(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError(f'缺少邮件配置环境变量 {name}')
    return value


def send_email(subject, html_body, text_body):
    host = required_env('SMTP_HOST')
    port = int(os.environ.get('SMTP_PORT', '587'))
    security = os.environ.get('SMTP_SECURITY', 'starttls').strip().lower()
    username = os.environ.get('SMTP_USERNAME', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '')
    sender = required_env('MAIL_FROM')
    sender_name = os.environ.get('MAIL_FROM_NAME', 'NBA 数据统计').strip()
    recipients = [item.strip() for item in required_env('MAIL_TO').split(',') if item.strip()]
    cc = [item.strip() for item in os.environ.get('MAIL_CC', '').split(',') if item.strip()]
    if not recipients:
        raise ValueError('MAIL_TO 至少需要一个收件人')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = formataddr((sender_name, sender))
    message['To'] = ', '.join(recipients)
    if cc:
        message['Cc'] = ', '.join(cc)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype='html')
    if security == 'ssl':
        client = smtplib.SMTP_SSL(host, port, timeout=30)
    elif security in ('starttls', 'none'):
        client = smtplib.SMTP(host, port, timeout=30)
    else:
        raise ValueError('SMTP_SECURITY 仅支持 starttls、ssl 或 none')
    with client:
        if security == 'starttls':
            client.starttls()
        if username:
            client.login(username, password)
        client.send_message(message, to_addrs=recipients + cc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='nba_trades.sqlite3')
    parser.add_argument('--slot', default='', help='计划时段标签，例如 20:00 或 21:00')
    parser.add_argument('--subject-prefix', default=os.environ.get('MAIL_SUBJECT_PREFIX', 'NBA 次日统计'))
    args = parser.parse_args()
    now = datetime.now(BEIJING)
    report_date, games, schedule_status = load_games(args.db, now)
    html_body, text_body = render_report(report_date, games, schedule_status, now)
    slot = args.slot or now.strftime('%H:%M')
    subject = f'{args.subject_prefix}｜{report_date:%Y-%m-%d}｜{slot} 北京时间'
    send_email(subject, html_body, text_body)
    print(f'邮件已发送：{subject}，比赛 {len(games)} 场')


if __name__ == '__main__':
    main()
