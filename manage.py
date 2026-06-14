#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天刃量化官网 - 数据管理脚本
用法：
  python manage.py pool          # 更新股票池（从东方财富API抓取主力建仓TOP30）
  python manage.py trade add --code 000001 --name 平安银行 --buy 10.50 --strategy ambush
  python manage.py trade close --code 000001 --sell 11.20
  python manage.py portrait add --code 000001 --name 平安银行 --signal 10.50 --limit 11.55 --tags 5阴超跌,主力被套
  python manage.py equity        # 重算净值曲线
  python manage.py monthly       # 更新月度统计
  python manage.py all           # 一键全更新
"""

import json
import sys
import os
import argparse
from datetime import datetime, date
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data.json"

# ============================================================
# 数据读写
# ============================================================
def load_data():
    if not DATA_FILE.exists():
        print(f"[错误] 找不到数据文件: {DATA_FILE}")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    data["meta"]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[完成] 数据已更新 → {DATA_FILE}")

# ============================================================
# 股票池更新
# ============================================================
def update_pool(data):
    """从东方财富主力建仓接口抓取TOP30"""
    print("[执行] 正在获取主力建仓数据...")
    try:
        from coze_workload_identity import requests
    except ImportError:
        import requests

    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_DMSK_TS_STOCKNEW",
        "columns": "ALL",
        "pageSize": 30,
        "sortTypes": -1,
        "sortColumns": "PRIME_INFLOW",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            print(f"[警告] 东方财富接口返回错误: {result.get('message', '未知')}")
            return

        rows = result.get("result", {}).get("data", [])
        if not rows:
            print("[警告] 未获取到主力建仓数据")
            return

        pool = []
        for row in rows:
            code = row.get("SECURITY_CODE", "")
            name = row.get("SECURITY_NAME_ABBR", "")
            close = row.get("CLOSE_PRICE", 0) or 0
            change = row.get("CHANGE_RATE", 0) or 0
            prime_inflow = row.get("PRIME_INFLOW", 0) or 0
            prime_cost = row.get("PRIME_COST", 0) or 0
            org_part = row.get("ORG_PARTICIPATE", 0) or 0
            total_score = row.get("TOTALSCORE", 0) or 0

            # 判断是否主力被套（收盘价 < 主力成本）
            trapped = close < prime_cost if prime_cost > 0 else False

            pool.append({
                "code": code,
                "name": name,
                "close": round(close, 2),
                "change_rate": round(change, 2),
                "prime_inflow": round(prime_inflow / 1e8, 2),  # 转亿
                "prime_cost": round(prime_cost, 2),
                "trapped": trapped,
                "org_participate": round(org_part, 2),
                "total_score": round(total_score, 1),
                "date": date.today().strftime("%Y-%m-%d")
            })

        data["pool"] = pool
        print(f"[完成] 股票池已更新，共 {len(pool)} 只")

    except Exception as e:
        print(f"[错误] 获取股票池失败: {e}")


# ============================================================
# 交易记录
# ============================================================
def add_trade(data, code, name, buy_price, strategy, trade_date=None):
    """新增一笔开仓交易"""
    trade_date = trade_date or date.today().strftime("%Y-%m-%d")
    position = {
        "code": code,
        "name": name,
        "buy_price": round(buy_price, 2),
        "buy_date": trade_date,
        "strategy": strategy,  # ambush=埋伏, steady=稳胜
        "amount": 0  # 股数，后续可扩展
    }
    data["open_positions"].append(position)
    print(f"[完成] 新增开仓: {code} {name} 买入价 {buy_price} 策略={strategy}")


def close_trade(data, code, sell_price, sell_date=None):
    """平仓一笔交易"""
    sell_date = sell_date or date.today().strftime("%Y-%m-%d")

    # 找到对应的持仓
    pos = None
    for i, p in enumerate(data["open_positions"]):
        if p["code"] == code:
            pos = data["open_positions"].pop(i)
            break

    if pos is None:
        print(f"[错误] 未找到 {code} 的持仓记录")
        return

    buy_price = pos["buy_price"]
    pct = round((sell_price - buy_price) / buy_price * 100, 2)
    days = (datetime.strptime(sell_date, "%Y-%m-%d") -
            datetime.strptime(pos["buy_date"], "%Y-%m-%d")).days

    trade = {
        "code": pos["code"],
        "name": pos["name"],
        "buy_price": buy_price,
        "buy_date": pos["buy_date"],
        "sell_price": round(sell_price, 2),
        "sell_date": sell_date,
        "strategy": pos["strategy"],
        "pct": pct,
        "days": max(days, 0),
        "date": sell_date
    }

    data["trades"].append(trade)
    print(f"[完成] 平仓: {code} {pos['name']} 收益 {pct:+.2f}% 持有 {days} 天")


# ============================================================
# 净值曲线
# ============================================================
def update_equity(data):
    """根据交易记录重算净值曲线"""
    trades = data["trades"]
    if not trades:
        print("[提示] 暂无已平仓交易，跳过净值计算")
        return

    initial = data["meta"]["initial_capital"]
    equity_val = initial

    # 按卖出日期排序
    sorted_trades = sorted(trades, key=lambda t: t.get("sell_date", ""))

    curve = [{"date": data["meta"]["start_date"], "equity": round(equity_val / initial, 4)}]

    for t in sorted_trades:
        # 简单模型：每笔交易影响净值
        pct_change = t["pct"] / 100
        # 按单笔仓位10%估算（后续可扩展为实际仓位）
        equity_val = equity_val * (1 + pct_change * 0.1)
        curve.append({
            "date": t["sell_date"],
            "equity": round(equity_val / initial, 4)
        })

    data["equity"] = curve
    data["meta"]["current_capital"] = round(equity_val, 2)
    print(f"[完成] 净值曲线已更新，当前净值 {curve[-1]['equity']:.4f}")


# ============================================================
# 验证涨停画像
# ============================================================
def add_portrait(data, code, name, signal_price, limit_price, tags, portrait_date=None):
    """记录一次伏击计划命中并验证涨停"""
    portrait_date = portrait_date or date.today().strftime("%Y-%m-%d")
    tag_list = [t.strip() for t in tags.split(",")] if isinstance(tags, str) else tags

    entry = {
        "code": code,
        "name": name,
        "signal_price": round(signal_price, 2),
        "limit_price": round(limit_price, 2),
        "tags": tag_list,
        "date": portrait_date
    }
    if "portrait" not in data:
        data["portrait"] = []
    data["portrait"].append(entry)

    # 同步更新涨停特征命中统计
    update_features(data)
    print(f"[完成] 涨停画像已添加: {code} {name} 信号价{signal_price}→涨停{limit_price} 标签={tag_list}")


def update_features(data):
    """根据所有涨停画像记录，统计各特征命中率"""
    portraits = data.get("portrait", [])
    if "features" not in data:
        data["features"] = {}

    # 特征关键词映射
    feature_map = {
        "five_yin": ["5阴超跌", "5阴", "超跌"],
        "trapped": ["主力被套", "被套"],
        "shrink_vol": ["缩量筑底", "缩量"],
        "good_news": ["消息面利好", "利好", "消息面"],
        "org_join": ["机构参与", "机构", "龙虎榜"],
        "low_cap": ["低价小盘", "低价", "小盘"]
    }

    for fkey, keywords in feature_map.items():
        hit = 0
        total = len(portraits)
        for p in portraits:
            tags = p.get("tags", [])
            for kw in keywords:
                if any(kw in t for t in tags):
                    hit += 1
                    break
        rate = f"{round(hit / total * 100)}%" if total > 0 else "0%"
        data["features"][fkey] = {"hit": hit, "total": total, "rate": rate}


# ============================================================
# 月度统计
# ============================================================
def update_monthly(data):
    """按月汇总交易表现"""
    trades = data["trades"]
    if not trades:
        print("[提示] 暂无交易记录，跳过月度统计")
        return

    from collections import defaultdict
    months = defaultdict(list)

    for t in trades:
        month_key = t.get("sell_date", "")[:7]  # YYYY-MM
        if month_key:
            months[month_key].append(t)

    monthly = []
    for month_key in sorted(months.keys()):
        month_trades = months[month_key]
        wins = [t for t in month_trades if t["pct"] > 0]
        ret = sum(t["pct"] for t in month_trades) / 10  # 按仓位10%估算组合收益
        dd = min(t["pct"] for t in month_trades) if month_trades else 0

        monthly.append({
            "month": month_key,
            "ret": round(ret, 2),
            "dd": round(dd, 2),
            "trades": len(month_trades),
            "wr": round(len(wins) / len(month_trades) * 100, 1) if month_trades else 0
        })

    data["monthly"] = monthly
    print(f"[完成] 月度统计已更新，共 {len(monthly)} 个月")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="天刃量化官网数据管理")
    sub = parser.add_subparsers(dest="command")

    # pool
    sub.add_parser("pool", help="更新股票池")

    # trade
    trade_parser = sub.add_parser("trade", help="交易记录")
    trade_sub = trade_parser.add_subparsers(dest="trade_action")

    add_parser = trade_sub.add_parser("add", help="开仓")
    add_parser.add_argument("--code", required=True, help="股票代码 如 000001")
    add_parser.add_argument("--name", required=True, help="股票名称")
    add_parser.add_argument("--buy", required=True, type=float, help="买入价格")
    add_parser.add_argument("--strategy", required=True, choices=["ambush", "steady"], help="策略: ambush=埋伏, steady=稳胜")
    add_parser.add_argument("--date", help="买入日期 YYYY-MM-DD，默认今天")

    close_parser = trade_sub.add_parser("close", help="平仓")
    close_parser.add_argument("--code", required=True, help="股票代码")
    close_parser.add_argument("--sell", required=True, type=float, help="卖出价格")
    close_parser.add_argument("--date", help="卖出日期 YYYY-MM-DD，默认今天")

    # portrait
    portrait_parser = sub.add_parser("portrait", help="验证涨停画像")
    portrait_sub = portrait_parser.add_subparsers(dest="portrait_action")
    p_add = portrait_sub.add_parser("add", help="添加涨停画像")
    p_add.add_argument("--code", required=True, help="股票代码")
    p_add.add_argument("--name", required=True, help="股票名称")
    p_add.add_argument("--signal", required=True, type=float, help="伏击信号价")
    p_add.add_argument("--limit", required=True, type=float, help="涨停价")
    p_add.add_argument("--tags", required=True, help="画像标签，逗号分隔，如：5阴超跌,主力被套")
    p_add.add_argument("--date", help="日期 YYYY-MM-DD，默认今天")

    # equity
    sub.add_parser("equity", help="重算净值曲线")

    # monthly
    sub.add_parser("monthly", help="更新月度统计")

    # all
    sub.add_parser("all", help="一键全更新（pool + equity + monthly）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    data = load_data()

    if args.command == "pool":
        update_pool(data)
        save_data(data)

    elif args.command == "trade":
        if args.trade_action == "add":
            add_trade(data, args.code, args.name, args.buy, args.strategy, args.date)
            save_data(data)
        elif args.trade_action == "close":
            close_trade(data, args.code, args.sell, args.date)
            # 平仓后自动重算净值和月度
            update_equity(data)
            update_monthly(data)
            save_data(data)
        else:
            trade_parser.print_help()

    elif args.command == "portrait":
        if args.portrait_action == "add":
            add_portrait(data, args.code, args.name, args.signal, args.limit, args.tags, args.date)
            save_data(data)
        else:
            portrait_parser.print_help()

    elif args.command == "equity":
        update_equity(data)
        save_data(data)

    elif args.command == "monthly":
        update_monthly(data)
        save_data(data)

    elif args.command == "all":
        update_pool(data)
        update_equity(data)
        update_monthly(data)
        save_data(data)


if __name__ == "__main__":
    main()
