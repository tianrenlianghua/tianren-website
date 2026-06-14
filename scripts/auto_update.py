#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天刃量化官网 - 每日自动更新脚本
GitHub Actions 每日收盘后自动执行：
1. 拉取持仓股票最新价格
2. 更新 data.json（价格、盈亏、净值）
3. 同步更新 index.html 中的 INLINE_DATA
4. 由 GitHub Actions 自动 commit + push，Vercel 自动部署
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, date
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_FILE = REPO_ROOT / "data.json"
HTML_FILE = REPO_ROOT / "index.html"


def fetch_price_tencent(codes):
    result = {}
    for code in codes:
        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        try:
            req = urllib.request.Request(url)
            req.add_header("Referer", "https://gu.qq.com")
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("gbk", errors="ignore")
        except Exception as e:
            print(f"[腾讯] {code} 请求失败: {e}")
            continue
        match = re.search(r'="([^"]*)"', text)
        if not match:
            continue
        fields = match.group(1).split("~")
        if len(fields) < 5:
            continue
        try:
            current = float(fields[3])
        except (ValueError, IndexError):
            continue
        name = fields[1]
        result[code] = {"name": name, "current_price": round(current, 2)}
    return result


def fetch_price_sina(codes):
    prefix_map = {}
    for code in codes:
        prefix_map[code] = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    query = ",".join(prefix_map.values())
    url = f"https://hq.sinajs.cn/list={query}"
    req = urllib.request.Request(url)
    req.add_header("Referer", "https://finance.sina.com.cn")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk", errors="ignore")
    except Exception as e:
        print(f"[新浪] 请求失败: {e}")
        return {}
    result = {}
    for line in text.strip().split("\n"):
        if "=" not in line:
            continue
        var_part, data_part = line.split("=", 1)
        match = re.search(r'(sh|sz)(\d+)', var_part)
        if not match:
            continue
        code = match.group(2)
        fields = data_part.strip().strip('";').split(",")
        if len(fields) < 4:
            continue
        name = fields[0]
        try:
            current = float(fields[3]) if float(fields[3]) > 0 else float(fields[2])
        except (ValueError, IndexError):
            continue
        result[code] = {"name": name, "current_price": round(current, 2)}
    return result


def fetch_prices(codes):
    if not codes:
        return {}
    print(f"[行情] 获取 {len(codes)} 只股票最新价格...")
    prices = fetch_price_tencent(codes)
    missing = [c for c in codes if c not in prices]
    if missing:
        print(f"[新浪] 补充获取 {len(missing)} 只...")
        prices.update(fetch_price_sina(missing))
    print(f"[行情] 最终成功 {len(prices)}/{len(codes)}")
    return prices


def load_data():
    if not DATA_FILE.exists():
        print(f"[错误] 找不到 {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    data["meta"]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[完成] data.json 已更新")


def update_inline_data(data):
    if not HTML_FILE.exists():
        print(f"[警告] 找不到 {HTML_FILE}，跳过INLINE_DATA更新")
        return
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    inline_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    new_inline = f"const INLINE_DATA={inline_json};"
    pattern = r'const INLINE_DATA=\{.*?\};'
    if re.search(pattern, html):
        html = re.sub(pattern, new_inline, html, count=1)
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[完成] index.html INLINE_DATA 已更新")
    else:
        print(f"[警告] 未找到 INLINE_DATA 标记，跳过更新")


def update_positions(data, prices):
    positions = data.get("open_positions", [])
    if not positions:
        print("[提示] 当前无持仓，跳过价格更新")
        return
    total_market_value = 0
    total_cost = 0
    for pos in positions:
        code = pos["code"]
        if code in prices:
            old_price = pos.get("current_price", 0)
            new_price = prices[code]["current_price"]
            pos["current_price"] = new_price
            buy_price = pos.get("buy_price", 0)
            if buy_price > 0:
                pos["pct"] = round((new_price - buy_price) / buy_price * 100, 2)
            shares = pos.get("shares", 0)
            total_market_value += new_price * shares
            total_cost += buy_price * shares
            print(f"  {pos['name']}({code}): {old_price} -> {new_price} ({pos['pct']:+.2f}%)")
        else:
            print(f"  {pos['name']}({code}): 未获取到价格，保持不变")
    initial_capital = data["meta"].get("initial_capital", 10000)
    cash = initial_capital - total_cost
    current_capital = round(cash + total_market_value, 2)
    data["meta"]["current_capital"] = current_capital
    new_equity = round(current_capital / initial_capital, 4)
    today = date.today().strftime("%Y-%m-%d")
    equity_list = data.get("equity", [])
    last_equity = equity_list[-1] if equity_list else None
    if last_equity and last_equity.get("date", "").startswith(today):
        last_equity["equity"] = new_equity
    else:
        equity_list.append({"date": today, "equity": new_equity})
    data["equity"] = equity_list
    print(f"\n[总资产] {current_capital} 元 | 净值 {new_equity:.4f} | 总盈亏 {(current_capital/initial_capital-1)*100:+.2f}%")


def main():
    print("=" * 50)
    print(f"天刃量化官网 - 每日自动更新")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    data = load_data()
    codes = [pos["code"] for pos in data.get("open_positions", [])]
    if not codes:
        print("[提示] 当前无持仓，仅更新时间戳")
        data["meta"]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_data(data)
        update_inline_data(data)
        return
    prices = fetch_prices(codes)
    if prices:
        update_positions(data, prices)
    save_data(data)
    update_inline_data(data)
    print("\n[完成] 所有更新已完成")


if __name__ == "__main__":
    main()
