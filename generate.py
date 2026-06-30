#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票日报生成器
每小时自动运行一次（GitHub Action），生成完整的 index.html
"""

import json, urllib.request, datetime, os, sys, traceback

CONFIG_FILE = 'config.json'
OUTPUT_FILE = 'index.html'


# ======================== HTTP 请求 ========================

def fetch_json(url, timeout=15):
    """获取JSON数据"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', errors='ignore')
            # 处理JSONP
            if raw.startswith('[') or raw.startswith('{'):
                return json.loads(raw)
            idx = raw.find('(')
            if idx > 0 and raw.endswith(')'):
                return json.loads(raw[idx+1:-1])
            return None
    except Exception as e:
        print(f"  [网络] {type(e).__name__}: {url[:40]}...")
        return None


# ======================== 数据获取 ========================

def get_date_info():
    """获取日期信息"""
    now = datetime.datetime.now()
    weekdays = ['星期一','星期二','星期三','星期四','星期五','星期六','星期日']
    # 确定交易日：非周末
    d = now
    for _ in range(7):
        if d.weekday() < 5:
            break
        d -= datetime.timedelta(days=1)
    latest = d
    return {
        'current': now.strftime('%Y-%m-%d'),
        'latest_trade': latest.strftime('%Y年%m月%d日') + ' ' + weekdays[latest.weekday()],
        'is_trade_time': now.weekday() < 5 and (
            (now.hour == 9 and now.minute >= 30) or
            10 <= now.hour <= 10 or
            (now.hour == 11 and now.minute <= 30) or
            13 <= now.hour < 15
        )
    }


def get_a_indices():
    """获取A股大盘指数"""
    secids = '1.000001,0.399001,0.399006'
    url = f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14'
    data = fetch_json(url)
    if not data or not data.get('data') or not data['data'].get('diff'):
        return []
    names = {'000001':'上证指数','399001':'深证成指','399006':'创业板指'}
    return [{
        'name': names.get(d.get('f12',''), d.get('f14','')),
        'price': d.get('f2', 0),
        'change_pct': d.get('f3', 0),
    } for d in data['data']['diff']]


def get_us_indices():
    """获取美股指数 (Yahoo Finance)"""
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
    return results


def get_hot_sectors():
    """获取热门板块（行业板块涨幅榜TOP5）"""
    url = ('http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1'
           '&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3'
           '&fs=m:90+t:2&fields=f12,f14,f2,f3,f4')
    data = fetch_json(url)
    if data and data.get('data') and data['data'].get('diff'):
        return [{'name': d.get('f14',''), 'change_pct': d.get('f3',0)}
                for d in data['data']['diff'][:5]]
    return []


def get_stock_quote(secid):
    """获取个股行情"""
    url = f'http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secid}&fields=f2,f3,f4,f12,f14,f15,f16,f17,f18'
    data = fetch_json(url)
    if data and data.get('data') and data['data'].get('diff'):
        for d in data['data']['diff']:
            if d.get('f12'):
                return {
                    'price': d.get('f2', 0),
                    'change_pct': d.get('f3', 0),
                    'change_amount': d.get('f4', 0),
                    'high': d.get('f15', 0),
                    'low': d.get('f16', 0),
                    'open': d.get('f17', 0),
                    'volume': d.get('f18', 0),
                    'name': d.get('f14', ''),
                    'code': d.get('f12', ''),
                }
    return None


def get_kline_data(secid, days=60):
    """获取K线数据（尝试两个API源）"""
    # 方案一：东方财富
    url1 = (f'http://push2.eastmoney.com/api/qt/stock/kline/get'
            f'?secid={secid}&ut=bd1d9ddb04089700cf9c27f6f7426281'
            f'&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56,f57'
            f'&klt=101&fqt=1&end=20500101&lmt={days}')
    data = fetch_json(url1)
    if data and data.get('data') and data['data'].get('klines'):
        klines = data['data']['klines']
        result = []
        for k in klines:
            p = k.split(',')
            if len(p) >= 6:
                result.append({'close': float(p[2]), 'volume': float(p[5])})
        if result:
            return result

    # 方案二：新浪财经
    market, code = secid.split('.')
    prefix = 'sh' if market == '1' else 'sz'
    url2 = (f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php'
            f'/CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={days}')
    data2 = fetch_json(url2)
    if data2 and isinstance(data2, list) and len(data2) > 0:
        result = []
        for item in data2:
            try:
                result.append({'close': float(item.get('c',0)), 'volume': float(item.get('v',0))})
            except:
                continue
        if result:
            return result

    print(f"  [警告] {code}: K线数据获取失败（两个API均无返回）")
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
    return round(dif[-1], 2) if dif else None, round(dea[-1], 2) if dea else None, round(hist[-1], 2) if hist else None


def generate_stock_analysis(quote, kline):
    """生成完整的个股分析"""
    if not quote:
        return None

    result = {
        'name': quote.get('name', ''),
        'code': quote.get('code', ''),
        'price': quote.get('price', 0),
        'change_pct': quote.get('change_pct', 0),
        'change_amount': quote.get('change_amount', 0),
        'high': quote.get('high', 0),
        'low': quote.get('low', 0),
        'open': quote.get('open', 0),
        'volume': quote.get('volume', 0),
    }

    # 如果没有K线数据，只返回基础信息
    if not kline or len(kline) < 20:
        result['has_analysis'] = False
        result['summary'] = '数据不足，仅显示基础行情'
        return result

    result['has_analysis'] = True
    closes = [k['close'] for k in kline]
    p = quote['price']

    # 均线
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)

    # RSI
    rsi = calc_rsi(closes, 14)

    # MACD
    dif, dea, hist = calc_macd(closes)

    # 支撑位 / 压力位（近20日低点/高点）
    recent = closes[-20:]
    support = min(recent)
    resistance = max(recent)

    result['ma5'] = round(ma5, 2) if ma5 else None
    result['ma10'] = round(ma10, 2) if ma10 else None
    result['ma20'] = round(ma20, 2) if ma20 else None
    result['ma60'] = round(ma60, 2) if ma60 else None
    result['rsi'] = rsi
    result['macd_dif'] = dif
    result['macd_dea'] = dea
    result['macd_hist'] = hist
    result['support'] = round(support, 2)
    result['resistance'] = round(resistance, 2)

    # ---- 综合打分（满分10分） ----
    score = 5  # 基础分

    reasons = []

    # RSI打分
    if rsi is not None:
        if rsi < 25:
            score += 2; reasons.append(f"RSI({rsi})严重超卖，反弹机会大")
        elif rsi < 35:
            score += 1.5; reasons.append(f"RSI({rsi})超卖区间，可关注")
        elif rsi < 45:
            score += 1; reasons.append(f"RSI({rsi})偏低，有空间")
        elif rsi > 75:
            score -= 2; reasons.append(f"RSI({rsi})严重超买，注意风险")
        elif rsi > 65:
            score -= 1; reasons.append(f"RSI({rsi})偏高，追涨需谨慎")
        elif rsi > 55:
            score -= 0.5; reasons.append(f"RSI({rsi})中性偏强")
        else:
            reasons.append(f"RSI({rsi})中性")

    # 均线排列打分
    if ma5 and ma10 and ma20:
        if p > ma5 > ma10 > ma20:
            score += 2; reasons.append("均线多头排列，上升趋势良好")
        elif p > ma10 and p > ma20:
            score += 1; reasons.append("价格站上中期均线，趋势偏多")
        elif p < ma5 < ma10 < ma20:
            score -= 2; reasons.append("均线空头排列，下降趋势明显")
        elif p < ma10 and p < ma20:
            score -= 1; reasons.append("跌破中期均线，趋势偏弱")
        else:
            reasons.append("均线交织，方向不明")

        # 价格与MA20的距离
        dist = (p - ma20) / ma20 * 100 if ma20 else 0
        if dist > 15:
            score -= 1; reasons.append(f"偏离MA20过远({dist:.1f}%)，有回调压力")
        elif dist < -10:
            score += 1; reasons.append(f"低于MA20({dist:.1f}%)，乖离过大可能反弹")

    # MACD打分
    if dif is not None and dea is not None and hist is not None:
        if dif > dea and hist > 0:
            score += 1.5; reasons.append("MACD金叉，动能偏多")
        elif dif > dea:
            score += 0.5; reasons.append("MACD DIF在DEA上方")
        elif dif < dea and hist < 0:
            score -= 1.5; reasons.append("MACD死叉，动能偏空")
        elif dif < dea:
            score -= 0.5; reasons.append("MACD DIF在DEA下方")

    # MA60中长期趋势
    if ma60:
        if p > ma60:
            score += 1; reasons.append(f"价格在MA60({ma60})之上，中长期趋势偏多")
        else:
            score -= 1; reasons.append(f"价格在MA60({ma60})之下，中长期趋势偏弱")

    # 今日涨跌
    if abs(quote.get('change_pct', 0)) < 0.5:
        pass  # 小涨小跌，不扣分
    elif quote.get('change_pct', 0) > 3:
        score -= 0.5; reasons.append("今日涨幅较大，短线可能回调")
    elif quote.get('change_pct', 0) < -3:
        score += 0.5; reasons.append("今日跌幅较大，短线可能有反弹")

    # 截取有效分数
    score = max(1, min(10, round(score, 1)))

    # ---- 操作建议 ----
    if score >= 8:
        action = '推荐买入'
    elif score >= 6.5:
        action = '可关注'
    elif score >= 4.5:
        action = '持有观望'
    elif score >= 3:
        action = '注意风险'
    else:
        action = '建议减仓'

    # 趋势判断
    if ma5 and ma10 and ma20:
        if p > ma5 > ma10 > ma20:
            trend = '强势上涨'
        elif p > ma5 and p > ma10:
            trend = '震荡偏强'
        elif ma5 < ma10 < ma20 and p < ma20:
            trend = '弱势调整'
        elif ma5 > ma10 and p > ma20:
            trend = '短期反弹'
        else:
            trend = '横盘震荡'
    else:
        trend = '数据不足'

    result['score'] = score
    result['action'] = action
    result['trend'] = trend
    result['summary'] = '；'.join(reasons[:5])  # 最多显示5条

    return result


def generate_market_summary(a_indices, us_indices, sectors):
    """生成大盘行情综述文字"""
    parts = []

    if a_indices:
        up = sum(1 for i in a_indices if i['change_pct'] > 0)
        down = sum(1 for i in a_indices if i['change_pct'] < 0)
        if up == len(a_indices):
            parts.append('A股三大指数集体收涨')
        elif down == len(a_indices):
            parts.append('A股三大指数集体收跌')
        else:
            parts.append('A股三大指数涨跌互现')
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
            if up == len(valid):
                parts.append('三大指数集体收涨')
            elif down == len(valid):
                parts.append('三大指数集体收跌')
            else:
                parts.append('三大指数涨跌不一')
            for i in valid:
                d = '上涨' if i['change_pct'] >= 0 else '下跌'
                parts.append(f"{i['name']}{d}{abs(i['change_pct']):.2f}%")

    return ' | '.join(parts)


# ======================== HTML 生成 ========================

def generate_html(data):
    """生成完整的HTML页面"""

    date_info = data['date_info']
    summary = data['summary']
    a_indices = data['a_indices']
    us_indices = data['us_indices']
    analysis_list = data['analysis_list']
    config = data['config']

    # 数据更新时间
    update_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # ---- 持仓HTML ----
    portfolio_rows = ''
    if analysis_list:
        has_analysis = any(s.get('has_analysis') for s in analysis_list)

        for s in analysis_list:
            cls = 'up' if s.get('change_pct', 0) > 0 else 'down' if s.get('change_pct', 0) < 0 else ''
            pct_str = f"{'+' if s['change_pct']>=0 else ''}{s['change_pct']:.2f}%" if s.get('change_pct') is not None else '--'

            if s.get('has_analysis'):
                score = s.get('score', 5)
                action = s.get('action', '持有观望')
                trend = s.get('trend', '')
                summary_text = s.get('summary', '')

                # 分数颜色
                if score >= 7:
                    score_cls = 'sc-g'
                elif score >= 5:
                    score_cls = 'sc-y'
                else:
                    score_cls = 'sc-r'

                action_cls = 'ab' if '买入' in action else 'aw' if '风险' in action or '减仓' in action else 'ah'

                portfolio_rows += f'''
                <tr>
                    <td class="sc"><span class="{score_cls}">{score}</span></td>
                    <td><strong>{s['name']}</strong><br><span class="cd">{s['code']}</span></td>
                    <td class="{cls}"><strong>{s['price']:.2f}</strong></td>
                    <td class="{cls}">{pct_str}</td>
                    <td><span class="at {action_cls}">{action}</span></td>
                    <td style="font-size:13px;color:#666;max-width:220px">{trend}<br><span class="rs">{summary_text}</span></td>
                </tr>'''
            else:
                portfolio_rows += f'''
                <tr>
                    <td class="sc">--</td>
                    <td><strong>{s['name']}</strong><br><span class="cd">{s['code']}</span></td>
                    <td class="{cls}"><strong>{s['price']:.2f}</strong></td>
                    <td class="{cls}">{pct_str}</td>
                    <td><span class="at ah">仅行情</span></td>
                    <td style="font-size:13px;color:#999">基础行情数据（技术分析数据暂缺）</td>
                </tr>'''
    else:
        portfolio_rows = '<tr><td colspan="6" style="text-align:center;padding:20px;color:#999">暂未配置持仓股票</td></tr>'

    # ---- 指数HTML ----
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
<table class="tbl">
<thead><tr><th style="width:40px">评分</th><th>股票</th><th>现价</th><th>涨跌幅</th><th>建议</th><th>分析</th></tr></thead>
<tbody>{portfolio_rows}</tbody>
</table>
</div>

<div class="ft">数据来源：东方财富 / Yahoo Finance · 仅供参考，不构成投资建议</div>
</div>
</body>
</html>'''

    return html


# ======================== 主流程 ========================

def main():
    print('='*40)
    print('  股票日报生成器 v2')
    print('='*40)

    # 读取配置
    if not os.path.exists(CONFIG_FILE):
        print(f'[错误] 找不到 {CONFIG_FILE}')
        sys.exit(1)

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)

    print(f'  标题: {config.get("title","股票日报")}')
    print(f'  持仓: {len(config.get("portfolio",[]))} 只股票')

    # 获取市场数据
    print('\n[获取] A股指数...')
    a_indices = get_a_indices()
    print(f'  → {len(a_indices)} 个指数')

    print('[获取] 美股指数...')
    us_indices = get_us_indices()
    print(f'  → {len(us_indices)} 个指数')

    print('[获取] 热门板块...')
    sectors = get_hot_sectors()
    print(f'  → {len(sectors)} 个板块')

    # 日期信息
    date_info = get_date_info()
    print(f'  日期: {date_info["latest_trade"]}')

    # 分析持仓
    print('\n[分析] 持仓股票...')
    analysis_list = []
    for stock in config.get('portfolio', []):
        secid = f"{stock['market']}.{stock['code']}"
        name = stock.get('name', stock['code'])
        print(f'  {name}({stock["code"]})...', end='')

        quote = get_stock_quote(secid)
        if not quote:
            print(' ❌ 获取行情失败')
            continue

        quote['name'] = name  # 用配置中的名称
        quote['code'] = stock['code']

        print(' ✓', end='')
        kline = get_kline_data(secid, 60)

        analysis = generate_stock_analysis(quote, kline)
        if analysis:
            analysis_list.append(analysis)
            if analysis.get('has_analysis'):
                print(f' 评分:{analysis["score"]} 建议:{analysis["action"]}')
            else:
                print(' 基础行情')
        else:
            print(' ❌ 分析失败')

    # 生成综述
    summary = generate_market_summary(a_indices, us_indices, sectors)

    # 生成HTML
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
    print(f'  ✓ 已生成 {OUTPUT_FILE} ({file_size/1024:.1f} KB)')
    print('\n完成！')


if __name__ == '__main__':
    main()