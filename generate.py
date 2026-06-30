#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票日报生成器 v2
- 改用腾讯API获取A股数据（海外可访问）
- 雅虎财经获取美股数据
- 更长的超时时间和错误容忍
"""

import json, urllib.request, datetime, os, sys, re

CONFIG_FILE = 'config.json'
OUTPUT_FILE = 'index.html'


# ======================== HTTP 请求 ========================

def fetch_json(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', errors='ignore')
            if raw.startswith('[') or raw.startswith('{'):
                return json.loads(raw)
            idx = raw.find('(')
            if idx > 0 and raw.endswith(')'):
                return json.loads(raw[idx+1:-1])
            return None
    except Exception as e:
        print(f"  [网络] {type(e).__name__}")
        return None


def fetch_text(url, timeout=20):
    """获取纯文本响应"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('gbk', errors='ignore')
    except Exception as e:
        print(f"  [网络] {type(e).__name__}")
        return None


# ======================== 腾讯股票API (海外可访问) ========================

def get_from_tencent(codes):
    """从腾讯API获取股票行情 (支持多个)
    codes: ['sh600519', 'sh000001', 'sz399001']
    返回: {code: {fields}}
    """
    qs = ','.join(codes)
    url = f'http://qt.gtimg.cn/q={qs}'
    text = fetch_text(url)
    if not text:
        return {}

    result = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if '="' not in line:
            continue
        parts = line.split('="')
        if len(parts) < 2:
            continue
        values = parts[1].rstrip('";').split('~')
        if len(values) < 5:
            continue
        code = values[1]
        try:
            current = float(values[3]) if values[3] else 0
            prev_close = float(values[4]) if values[4] else 0
            change_pct = round(((current - prev_close) / prev_close) * 100, 2) if prev_close else 0
            result[code] = {
                'name': values[2],
                'code': code,
                'price': current,
                'change_pct': change_pct,
                'open': float(values[5]) if values[5] else 0,
                'volume': int(float(values[6])) if values[6] else 0,
                'high': float(values[9]) if len(values) > 9 and values[9] else 0,
                'low': float(values[10]) if len(values) > 10 and values[10] else 0,
            }
        except (ValueError, IndexError):
            continue
    return result


# ======================== 数据获取 ========================

def get_date_info():
    now = datetime.datetime.now()
    weekdays = ['星期一','星期二','星期三','星期四','星期五','星期六','星期日']
    d = now
    for _ in range(7):
        if d.weekday() < 5:
            break
        d -= datetime.timedelta(days=1)
    return {
        'current': now.strftime('%Y-%m-%d'),
        'latest_trade': d.strftime('%Y年%m月%d日') + ' ' + weekdays[d.weekday()],
        'is_trade_time': now.weekday() < 5 and (
            (now.hour == 9 and now.minute >= 30) or
            10 <= now.hour <= 10 or
            (now.hour == 11 and now.minute <= 30) or
            13 <= now.hour < 15
        )
    }


def get_a_indices():
    """获取A股大盘指数（腾讯API）"""
    codes = ['sh000001', 'sz399001', 'sz399006']
    name_map = {'000001': '上证指数', '399001': '深证成指', '399006': '创业板指'}
    data = get_from_tencent(codes)
    result = []
    for code_prefix in codes:
        code = code_prefix[2:]  # sh000001 -> 000001
        if code in data:
            result.append({
                'name': name_map.get(code, data[code]['name']),
                'price': data[code]['price'],
                'change_pct': data[code]['change_pct'],
            })
        else:
            result.append({'name': name_map.get(code, ''), 'price': 0, 'change_pct': 0})
    print(f"  A股指数: {len(result)} 个")
    return result


def get_us_indices():
    symbols = [
        ('S&P 500', '%5EGSPC'),
        ('纳斯达克', '%5EIXIC'),
        ('道琼斯', '%5EDJI'),
    ]
    results = []
    for name, sym in symbols:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d'
        data = fetch_json(url)
        if data and data.get('chart',{}).get('result'):
            r = data['chart']['result'][0]
            meta = r.get('meta',{})
            if meta.get('regularMarketPrice'):
                p = meta['regularMarketPrice']
                pv = meta.get('previousClose', 0)
                results.append({
                    'name': name,
                    'price': round(p, 2),
                    'change_pct': round(((p-pv)/pv)*100, 2) if pv else 0
                })
            else:
                results.append({'name': name, 'price': 0, 'change_pct': 0})
        else:
            results.append({'name': name, 'price': 0, 'change_pct': 0})
    print(f"  美股指数: {len(results)} 个")
    return results


def get_hot_sectors():
    """获取热门板块（东方财富，超时较长）"""
    url = ('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1'
           '&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3'
           '&fs=m:90+t:2&fields=f12,f14,f2,f3,f4')
    data = fetch_json(url, timeout=30)
    if data and data.get('data') and data['data'].get('diff'):
        sectors = [{'name': d.get('f14',''), 'change_pct': d.get('f3',0)}
                   for d in data['data']['diff'][:5]]
        print(f"  板块: {len(sectors)} 个")
        return sectors
    print("  板块: 获取失败（跳过）")
    return []


def get_stock_quote(code, market):
    """获取个股行情（腾讯API）"""
    prefix = 'sh' if market == '1' else 'sz'
    data = get_from_tencent([f'{prefix}{code}'])
    if code in data:
        return data[code]
    return None


def get_kline_data(code, market, days=60):
    """获取K线数据（尝试两个API源，失败则跳过）"""
    prefix = 'sh' if market == '1' else 'sz'
    # 方案一：新浪财经
    url1 = (f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php'
            f'/CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={days}')
    data = fetch_json(url1)
    if data and isinstance(data, list) and len(data) > 0:
        result = []
        for item in data:
            try:
                result.append({'close': float(item.get('c',0)), 'volume': float(item.get('v',0))})
            except:
                continue
        if result:
            print(f"  K线({code}): {len(result)}条(新浪)")
            return result

    # 方案二：东方财富
    secid = f"{market}.{code}"
    url2 = (f'http://push2.eastmoney.com/api/qt/stock/kline/get'
            f'?secid={secid}&ut=bd1d9ddb04089700cf9c27f6f7426281'
            f'&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57'
            f'&klt=101&fqt=1&end=20500101&lmt={days}')
    data2 = fetch_json(url2, timeout=30)
    if data2 and data2.get('data') and data2['data'].get('klines'):
        klines = data2['data']['klines']
        result = []
        for k in klines:
            p = k.split(',')
            if len(p) >= 6:
                result.append({'close': float(p[2]), 'volume': float(p[5])})
        if result:
            print(f"  K线({code}): {len(result)}条(东方财富)")
            return result

    print(f"  K线({code}): 无数据（继续使用基础行情）")
    return []


# ======================== 技术分析 ========================

def calc_ma(prices, n):
    if len(prices) < n: return None
    return sum(prices[-n:]) / n


def calc_rsi(prices, n=14):
    if len(prices) < n + 1: return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [max(d,0) for d in deltas]
    losses = [max(-d,0) for d in deltas]
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0: return 100 if ag > 0 else 50
    return round(100 - 100/(1+ag/al), 1)


def calc_macd(prices):
    if len(prices) < 26: return None, None, None
    def ema(data, n):
        m = 2/(n+1); r = [data[0]]
        for i in range(1, len(data)):
            r.append((data[i]-r[-1])*m + r[-1])
        return r
    e12 = ema(prices, 12); e26 = ema(prices, 26)
    dif = [e12[i]-e26[i] for i in range(len(e26))]
    dea = ema(dif, 9)
    hist = [2*(dif[i]-dea[i]) for i in range(len(dea))]
    return (round(dif[-1],2) if dif else None,
            round(dea[-1],2) if dea else None,
            round(hist[-1],2) if hist else None)


def generate_stock_analysis(quote, kline):
    if not quote:
        return None

    result = {
        'name': quote.get('name', ''),
        'code': quote.get('code', ''),
        'price': quote.get('price', 0),
        'change_pct': quote.get('change_pct', 0),
        'high': quote.get('high', 0),
        'low': quote.get('low', 0),
        'open': quote.get('open', 0),
        'volume': quote.get('volume', 0),
    }

    if not kline or len(kline) < 20:
        result['has_analysis'] = False
        result['summary'] = '仅显示基础行情'
        return result

    result['has_analysis'] = True
    closes = [k['close'] for k in kline]
    p = quote['price']

    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    rsi = calc_rsi(closes, 14)
    dif, dea, hist = calc_macd(closes)
    recent = closes[-20:]
    support = min(recent)
    resistance = max(recent)

    result['ma5'] = round(ma5,2) if ma5 else None
    result['ma10'] = round(ma10,2) if ma10 else None
    result['ma20'] = round(ma20,2) if ma20 else None
    result['ma60'] = round(ma60,2) if ma60 else None
    result['rsi'] = rsi
    result['support'] = round(support,2)
    result['resistance'] = round(resistance,2)

    # 打分系统
    score = 5
    reasons = []

    if rsi is not None:
        if rsi < 25: score += 2; reasons.append(f"RSI({rsi})严重超卖")
        elif rsi < 35: score += 1.5; reasons.append(f"RSI({rsi})超卖区间")
        elif rsi < 45: score += 1; reasons.append(f"RSI({rsi})偏低")
        elif rsi > 75: score -= 2; reasons.append(f"RSI({rsi})严重超买")
        elif rsi > 65: score -= 1; reasons.append(f"RSI({rsi})偏高")
        elif rsi > 55: score -= 0.5
        else: reasons.append(f"RSI({rsi})中性")

    if ma5 and ma10 and ma20:
        if p > ma5 > ma10 > ma20:
            score += 2; reasons.append("均线多头排列")
        elif p > ma10 and p > ma20:
            score += 1; reasons.append("站上中期均线")
        elif p < ma5 < ma10 < ma20:
            score -= 2; reasons.append("均线空头排列")
        elif p < ma10 and p < ma20:
            score -= 1; reasons.append("跌破中期均线")
        else:
            reasons.append("均线方向不明")

        dist = (p - ma20) / ma20 * 100 if ma20 else 0
        if dist > 12: score -= 1; reasons.append(f"偏离MA20过远({dist:.1f}%)")
        elif dist < -8: score += 1; reasons.append(f"低于MA20乖离大({dist:.1f}%)")

    if dif is not None and dea is not None and hist is not None:
        if dif > dea and hist > 0: score += 1.5; reasons.append("MACD金叉偏多")
        elif dif > dea: score += 0.5
        elif dif < dea and hist < 0: score -= 1.5; reasons.append("MACD死叉偏空")
        elif dif < dea: score -= 0.5

    if ma60:
        if p > ma60: score += 1; reasons.append(f">MA60({ma60})中长期偏多")
        else: score -= 1; reasons.append(f"<MA60({ma60})中长期偏弱")

    if abs(quote.get('change_pct',0)) > 3:
        if quote['change_pct'] > 0: score -= 0.5; reasons.append("今日涨幅偏大")
        else: score += 0.5; reasons.append("今日跌幅较大")

    score = max(1, min(10, round(score, 1)))

    if score >= 8: action = '推荐买入'
    elif score >= 6.5: action = '可关注'
    elif score >= 4.5: action = '持有观望'
    elif score >= 3: action = '注意风险'
    else: action = '建议减仓'

    if ma5 and ma10 and ma20:
        if p > ma5 > ma10 > ma20: trend = '强势上涨'
        elif p > ma5 and p > ma10: trend = '震荡偏强'
        elif ma5 < ma10 < ma20 and p < ma20: trend = '弱势调整'
        elif ma5 > ma10 and p > ma20: trend = '短期反弹'
        else: trend = '横盘震荡'
    else: trend = '数据不足'

    result['score'] = score
    result['action'] = action
    result['trend'] = trend
    result['summary'] = '；'.join(reasons[:5])
    return result


def generate_market_summary(a_indices, us_indices, sectors):
    parts = []
    if a_indices:
        up = sum(1 for i in a_indices if i['change_pct'] > 0)
        down = sum(1 for i in a_indices if i['change_pct'] < 0)
        parts.append('A股三大指数' + ('集体收涨' if up==3 else '集体收跌' if down==3 else '涨跌互现'))
        for i in a_indices:
            d = '上涨' if i['change_pct'] >= 0 else '下跌'
            parts.append(f"{i['name']}{d}{abs(i['change_pct']):.2f}%收于{i['price']:.2f}点")

    if sectors:
        parts.append('')
        parts.append('【热门板块】')
        up_s = [s for s in sectors if s['change_pct'] > 0]
        down_s = [s for s in sectors if s['change_pct'] < 0]
        if up_s:
            names = '、'.join([f"{s['name']}(+{s['change_pct']:.2f}%)" for s in up_s[:3]])
            parts.append(f"领涨：{names}")
        if down_s:
            names = '、'.join([f"{s['name']}({s['change_pct']:.2f}%)" for s in down_s[:2]])
            parts.append(f"领跌：{names}")

    if us_indices:
        valid = [i for i in us_indices if i['price'] > 0]
        if valid:
            parts.append('')
            parts.append('【美股市场】')
            up = sum(1 for i in valid if i['change_pct'] > 0)
            down = sum(1 for i in valid if i['change_pct'] < 0)
            parts.append('三大指数' + ('集体收涨' if up==len(valid) else '集体收跌' if down==len(valid) else '涨跌不一'))
            for i in valid:
                d = '上涨' if i['change_pct'] >= 0 else '下跌'
                parts.append(f"{i['name']}{d}{abs(i['change_pct']):.2f}%")

    return ' | '.join(parts)


# ======================== HTML 生成 ========================

def generate_html(data):
    date_info = data['date_info']
    summary = data['summary']
    a_indices = data['a_indices']
    us_indices = data['us_indices']
    analysis_list = data['analysis_list']
    config = data['config']
    update_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    portfolio_rows = ''
    if analysis_list:
        for s in analysis_list:
            cls = 'up' if s.get('change_pct',0) > 0 else 'down' if s.get('change_pct',0) < 0 else ''
            pct_str = f"{'+' if s['change_pct']>=0 else ''}{s['change_pct']:.2f}%" if s.get('change_pct') is not None else '--'

            if s.get('has_analysis'):
                score = s.get('score',5)
                action = s.get('action','持有观望')
                trend = s.get('trend','')
                summary_text = s.get('summary','')
                score_cls = 'sc-g' if score >= 7 else 'sc-y' if score >= 5 else 'sc-r'
                action_cls = 'ab' if '买入' in action else 'aw' if '风险' in action or '减仓' in action else 'ah'
                portfolio_rows += f'''
                <tr><td class="sc"><span class="{score_cls}">{score}</span></td><td><strong>{s['name']}</strong><br><span class="cd">{s['code']}</span></td><td class="{cls}"><strong>{s['price']:.2f}</strong></td><td class="{cls}">{pct_str}</td><td><span class="at {action_cls}">{action}</span></td><td style="font-size:13px;color:#666;max-width:220px">{trend}<br><span class="rs">{summary_text}</span></td></tr>'''
            else:
                portfolio_rows += f'''
                <tr><td class="sc">--</td><td><strong>{s['name']}</strong><br><span class="cd">{s['code']}</span></td><td class="{cls}"><strong>{s['price']:.2f}</strong></td><td class="{cls}">{pct_str}</td><td><span class="at ah">仅行情</span></td><td style="font-size:13px;color:#999">基础行情数据</td></tr>'''
    else:
        portfolio_rows = '<tr><td colspan="6" style="text-align:center;padding:20px;color:#999">暂未配置持仓股票</td></tr>'

    a_idx_html = ''
    for i in a_indices:
        c = 'up' if i['change_pct'] > 0 else 'down' if i['change_pct'] < 0 else ''
        s = '▲' if i['change_pct'] > 0 else '▼' if i['change_pct'] < 0 else '―'
        pct = f"{s} {abs(i['change_pct']):.2f}%" if i['change_pct'] else '0.00%'
        pr = f"{i['price']:.2f}" if i['price'] else '--'
        a_idx_html += f'<div class="card"><div class="nm">{i["name"]}</div><div class="pr {c}">{pr}</div><div class="ch {c}">{pct}</div></div>'

    us_idx_html = ''
    for i in us_indices:
        c = 'up' if i['change_pct'] > 0 else 'down' if i['change_pct'] < 0 else ''
        s = '▲' if i['change_pct'] > 0 else '▼' if i['change_pct'] < 0 else '―'
        pct = f"{s} {abs(i['change_pct']):.2f}%" if i['change_pct'] else '待盘'
        pr = f"{i['price']:.2f}" if i['price'] else '--'
        us_idx_html += f'<div class="card"><div class="nm">{i["name"]}</div><div class="pr {c}">{pr}</div><div class="ch {c}">{pct}</div></div>'

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{config.get('title','股票日报')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"Microsoft YaHei","PingFang SC",sans-serif;background:#f0f2f5;color:#333;font-size:15px}}
.container{{max-width:1000px;margin:0 auto;padding:16px}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:20px 24px 16px;border-radius:12px;margin-bottom:16px}}
.header h1{{font-size:22px}}
.header .sub{{font-size:13px;opacity:.7;margin-top:4px}}
.header .dt{{font-size:13px;opacity:.7;margin-top:2px}}
.summary{{background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:16px;box-shadow:0 1px 6px rgba(0,0,0,.06);font-size:13px;line-height:1.7;color:#555}}
.stitle{{font-size:17px;font-weight:bold;margin:18px 0 10px;padding-left:10px;border-left:3px solid #e74c3c}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:14px}}
.card{{background:#fff;border-radius:8px;padding:14px;box-shadow:0 1px 6px rgba(0,0,0,.06)}}
.card .nm{{font-size:13px;color:#666}}
.card .pr{{font-size:24px;font-weight:bold;margin:3px 0}}
.card .ch{{font-size:14px;font-weight:bold}}
.up{{color:#e74c3c}}.down{{color:#27ae60}}
.sec{{background:#fff;border-radius:10px;padding:16px;margin-bottom:14px;box-shadow:0 1px 6px rgba(0,0,0,.06)}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px}}
.tbl th{{text-align:left;padding:8px 6px;border-bottom:2px solid #eee;color:#666;font-weight:normal;white-space:nowrap}}
.tbl td{{padding:8px 6px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
.cd{{font-size:11px;color:#999}}
.sc{{text-align:center;width:40px}}
.sc-g{{display:inline-block;width:32px;height:32px;line-height:32px;border-radius:50%;background:#e74c3c;color:#fff;font-weight:bold;font-size:14px;text-align:center}}
.sc-y{{display:inline-block;width:32px;height:32px;line-height:32px;border-radius:50%;background:#f39c12;color:#fff;font-weight:bold;font-size:14px;text-align:center}}
.sc-r{{display:inline-block;width:32px;height:32px;line-height:32px;border-radius:50%;background:#27ae60;color:#fff;font-weight:bold;font-size:14px;text-align:center}}
.at{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:bold;white-space:nowrap}}
.ab{{background:#ffe0e0;color:#e74c3c}}
.as{{background:#d4edda;color:#27ae60}}
.ah{{background:#fff3cd;color:#856404}}
.aw{{background:#f8d7da;color:#721c24}}
.rs{{font-size:12px;color:#888;line-height:1.4;display:block;margin-top:3px}}
.empty{{text-align:center;color:#999;padding:30px;font-size:14px}}
.ft{{text-align:center;padding:16px;color:#bbb;font-size:11px}}
@media(max-width:600px){{
.container{{padding:10px}}.grid{{grid-template-columns:repeat(2,1fr)}}.card .pr{{font-size:20px}}
.tbl{{font-size:12px}}.tbl td,.tbl th{{padding:6px 4px}}
}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1>{config.get('title','股票日报')}</h1>
<div class="sub">{config.get('slogan','')}</div>
<div class="dt">{date_info['latest_trade']} · 更新于 {update_time}</div>
</div>
<div class="summary">{summary}</div>
<div class="stitle">A股指数</div>
<div class="grid">{a_idx_html}</div>
<div class="stitle">美股指数</div>
<div class="grid">{us_idx_html}</div>
<div class="stitle">我的持仓</div>
<div class="sec">
<table class="tbl"><thead><tr><th style="width:40px">评分</th><th>股票</th><th>现价</th><th>涨跌幅</th><th>建议</th><th>分析</th></tr></thead>
<tbody>{portfolio_rows}</tbody></table>
</div>
<div class="ft">数据来源：腾讯财经 / Yahoo Finance · 仅供参考，不构成投资建议</div>
</div>
</body>
</html>'''
    return html


# ======================== 主流程 ========================

def main():
    print('='*40)
    print('  股票日报生成器 v2')
    print('='*40)

    if not os.path.exists(CONFIG_FILE):
        print(f'[错误] 找不到 {CONFIG_FILE}')
        sys.exit(1)

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)

    print(f'  标题: {config.get("title","股票日报")}')
    print(f'  持仓: {len(config.get("portfolio",[]))} 只股票')

    print('\n[获取] A股指数...')
    a_indices = get_a_indices()

    print('[获取] 美股指数...')
    us_indices = get_us_indices()

    print('[获取] 热门板块...')
    sectors = get_hot_sectors()

    date_info = get_date_info()
    print(f'  日期: {date_info["latest_trade"]}')

    print('\n[分析] 持仓股票...')
    analysis_list = []
    for stock in config.get('portfolio', []):
        code = stock['code']
        market = stock['market']
        name = stock.get('name', code)
        print(f'  {name}({code})...', end='')

        quote = get_stock_quote(code, market)
        if not quote:
            print(' ❌ 获取行情失败')
            continue
        quote['name'] = name
        print(' ✓', end='')

        kline = get_kline_data(code, market, 60)
        analysis = generate_stock_analysis(quote, kline)
        if analysis:
            analysis_list.append(analysis)
            if analysis.get('has_analysis'):
                print(f' 评分:{analysis["score"]} 建议:{analysis["action"]}')
            else:
                print(' 基础行情')
        else:
            print(' ❌ 分析失败')

    summary = generate_market_summary(a_indices, us_indices, sectors)

    print('\n[生成] HTML页面...')
    html = generate_html({
        'date_info': date_info,
        'summary': summary,
        'a_indices': a_indices,
        'us_indices': us_indices,
        'analysis_list': analysis_list,
        'config': config,
    })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)

    file_size = os.path.getsize(OUTPUT_FILE)
    print(f'  ✓ {OUTPUT_FILE} ({file_size/1024:.1f} KB)')
    print('\n完成！')

if __name__ == '__main__':
    main()