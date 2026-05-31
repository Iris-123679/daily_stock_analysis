# 股票深度分析增强系统 v4 — 快速开始

基于 AKShare 的 A股+港股 深度分析工具，支持微信推送，内置买入信号评分系统。

## 两种运行方式

### 方式一：本地运行（推荐）

```bash
# 安装依赖（首次）
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare pandas numpy

# 运行全部9只股票 + 自动微信推送
python stock_enhanced.py

# 运行单只
STOCK_LIST=601899 python stock_enhanced.py

# 关闭微信推送
PUSHPLUS_TOKEN=0 python stock_enhanced.py
```

### 方式二：GitHub Actions 自动运行

1. 在仓库 Settings → Secrets → Actions 中添加 `PUSHPLUS_TOKEN`（你的 PushPlus Token）
2. 在仓库 Settings → Variables → Actions 中添加 `ENHANCED_STOCK_LIST`（可选，默认9只股票）
3. 手动触发：Actions → 增强分析 → Run workflow
4. 自动运行：每天北京时间 18:30 自动执行（需先创建 `enhanced-analysis.yml` 工作流文件）

> **注意**：创建 workflow 文件需要在 GitHub 网页上操作（API 需要 workflow 权限），详见下方。

#### 创建工作流文件

在 GitHub 网页上：
1. 进入仓库 → `.github/workflows/` → **Create new file**
2. 文件名：`.github/workflows/enhanced-analysis.yml`
3. 粘贴以下内容：

```yaml
name: 增强分析（AKShare + PushPlus）

on:
  schedule:
    - cron: '30 10 * * 1-5'
  workflow_dispatch:
    inputs:
      stock_list:
        description: '股票代码（逗号分隔）'
        required: false
        default: ''
      skip_push:
        description: '跳过微信推送'
        required: false
        default: false
        type: boolean

concurrency:
  group: enhanced-analysis
  cancel-in-progress: false

jobs:
  enhanced-analysis:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: |
          pip install --upgrade pip
          pip install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare pandas numpy
      - env:
          STOCK_LIST: ${{ github.event.inputs.stock_list || vars.ENHANCED_STOCK_LIST || '601899,000426,002714,000582,688063,688122,09868,01810,01788' }}
          PUSHPLUS_TOKEN: ${{ secrets.PUSHPLUS_TOKEN }}
          REPORT_DIR: reports
        run: |
          if [ "${{ github.event.inputs.skip_push }}" = "true" ]; then
            PUSHPLUS_TOKEN=0 python stock_enhanced.py
          else
            python stock_enhanced.py
          fi
      - uses: actions/upload-artifact@v6
        if: always()
        with:
          name: enhanced-reports-${{ github.run_number }}
          path: reports/
          retention-days: 30
```

## 功能一览

| 模块 | 说明 | A股 | 港股 |
|------|------|-----|------|
| 财务指标 | PE/PB/ROE/净利率/同比 | ✅ | ✅ |
| 技术分析 | MACD/RSI/布林带/均线/趋势 | ✅ | ✅ |
| 信号评分 | 6维度100分制买入信号 | ✅ | ✅ |
| 资金异动 | 主力/超大单/大单净流入 | ✅ | ❌ |
| 基本面透视 | 营收/利润/业绩/分红 | ✅ | ✅ |
| DCF估值 | 现金流折现+安全边际 | ✅ | ❌ |
| 微信推送 | PushPlus HTML卡片 | ✅ | ✅ |

## 买入信号评分系统

| 维度 | 满分 | 判断 |
|------|------|------|
| 趋势 | 30 | 多头26/弱势多头18/空头4 |
| 乖离率 | 20 | 回踩20/贴近18/追高4 |
| 量能 | 15 | 缩量回调15/放量上涨12 |
| 支撑 | 10 | MA5+MA10支撑 |
| MACD | 15 | 金叉12/多头8/死叉0 |
| RSI | 10 | 超卖10/强势8/超买0 |

信号等级: ≥75强烈买入 / ≥60买入 / ≥45持有 / ≥30观望 / ≥15卖出 / <15强烈卖出

## 默认股票列表

601899 紫金矿业 | 000426 兴业银锡 | 002714 牧原股份
000582 北部湾港 | 688063 派能科技 | 688122 西部超导
09868 小鹏集团-W | 01810 小米集团-W | 01788 国泰君安国际

## 微信推送

1. 关注公众号「PushPlus推送加」
2. 获取 Token，设置环境变量: PUSHPLUS_TOKEN=xxx
3. 关闭推送: PUSHPLUS_TOKEN=0

## 注意事项

- 东方财富接口非交易时段(夜间/周末)可能不可用
- 建议交易时间(9:30-15:00)运行获取完整数据
- 仅供参考，不构成投资建议
