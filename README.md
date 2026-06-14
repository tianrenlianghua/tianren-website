# 天刃量化官网 - 数据管理脚本

## 快速上手

### 1. 更新股票池（自动抓取东方财富主力建仓TOP30）
```bash
python manage.py pool
```

### 2. 开仓记录
```bash
python manage.py trade add --code 000001 --name 平安银行 --buy 10.50 --strategy ambush
```
- `--strategy` 可选：`ambush`（埋伏）或 `steady`（稳胜）
- `--date` 可选，默认今天，格式 YYYY-MM-DD

### 3. 平仓记录
```bash
python manage.py trade close --code 000001 --sell 11.20
```
- 平仓后自动重算净值曲线和月度统计
- `--date` 可选，默认今天

### 4. 一键全更新
```bash
python manage.py all
```
更新股票池 + 净值曲线 + 月度统计

### 5. 单独重算
```bash
python manage.py equity    # 只重算净值曲线
python manage.py monthly   # 只更新月度统计
```

## 数据流转

```
东方财富API ──→ manage.py pool ──→ data.json ──→ index.html 自动渲染
手动交易     ──→ manage.py trade ──→ data.json ──→ index.html 自动渲染
```

## 部署自动化（推荐）

域名到手后，推荐用 GitHub + Vercel 自动部署：

1. 把 `天刃量化官网/` 目录推到 GitHub 仓库
2. Vercel 绑定仓库，自动部署
3. 本地运行 `manage.py` 更新 data.json → git push → Vercel 自动重新部署

进阶：可配 GitHub Actions 定时运行 manage.py，实现全自动更新。

## 文件结构

```
天刃量化官网/
├── index.html        # 官网页面（自动读取data.json）
├── data.json         # 所有动态数据（脚本维护，不要手动改）
├── scripts/
│   ├── manage.py     # 数据管理脚本
│   └── README.md     # 本文档
└── 部署说明.md       # Vercel/Netlify 部署指引
```
