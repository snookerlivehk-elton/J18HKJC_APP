# j18pro 排位页 — 程序开发介绍与语言架构

> **给接手同事**：先读本文（总览），再读 [`J18PRO_RACECARD_HANDOFF.md`](./J18PRO_RACECARD_HANDOFF.md)（交互细节、硬规则、部署清单）。  
> 产品 UI 文案：繁体（zh-HK）。本文用简体，方便对内交接。  
> 文档对应线上验收真源约 **`0.2.416`**（以 SERVER2 `/root/j18pro/VERSION` 与 `package.json` 为准）。

---

## 1. 程序是做什么的

**j18pro 排位页**是手机端风格的赛马「排位／赛日」业务页，给用户看：

| 区域 | 作用 |
|------|------|
| 顶栏 | 直播／收音机／返回／名家／菜单 |
| 公告 + 场次胶囊 | 切场、赛况元信息 |
| 洞察区 | 时间轴、综合指数／赛果派彩胶囊 |
| 主表 | 左锁列（彩衣／马号／马名／档／独赢位置）+ 右滑数据列 |
| 弹层 | 赛期表、心水战绩、名家贴士、列排序、派彩明细、水位、马匹详情、使用说明等 |

**当前阶段**：前端以**内嵌演示数据**（`MEETING` 快照 + 若干 `*_DEMO`）为主，交互壳已成型；接真 API 时优先只换数据入口，少动 UI 壳。

**验收真源**（产品手机强制刷新看这里，不是 Git 仓库预览）：

```text
http://120.77.253.95:3030/racecard.html
```

同机还有 `finance-18`、`cabinet-quoter`、`onlynow` 等——**只动 j18pro**，不要改／重启其它进程。

---

## 2. 语言与技术栈（一张表看清）

本产品横跨「两个运行体」，语言不同，职责不同，**不要混成一个服务改**：

| 层级 | 语言 / 运行时 | 在哪里 | 职责 |
|------|----------------|--------|------|
| **页面本体** | **HTML + CSS + 原生 JavaScript（无框架）** | 仓库 `static/racecard_board.html` → 线上 `public/racecard.html` | 全部交互、排版、演示数据、主题／字号 |
| **使用说明页** | 同上（更小单页） | `static/racecard_help.html` → `public/help.html` | 功能更新日志 `FEATURE_CHANGELOG` |
| **线上静态宿主** | **Node.js ≥18**（原生 `http`，无 Express） | SERVER2 `/root/j18pro/src/server.js` | 静态文件、彩衣代理缓存、`/health` |
| **仓库内预览／契约测** | **Python 3 + FastAPI + uvicorn** | `raceday_embed_api.py`、`tests/test_raceday_embed.py` | `GET /embed/racecard` 读同一份 HTML；字符串断言锁 UI |
| **上游量化／爬虫（别系）** | Python + Postgres 等 | 同 GitHub 仓其它模块 | 因子、JJJC sync、预测 API——**不是本页日常改动范围** |

**刻意不做的事**：排位页**没有** React／Vue／Vite／Webpack；不靠构建流水线产出页面。改完 HTML 直接 scp 上线。

字体：页面用 Google Fonts「Noto Sans TC」+ 系统中文兜底；主题用 `html[data-theme="dark"]` + `localStorage`（`j18-racecard-theme`）。

---

## 3. 架构图（逻辑）

```text
┌─────────────────────────────────────────────────────────────┐
│  开发者改代码（GitHub J18HKJC_APP）                           │
│    static/racecard_board.html   ← 唯一主实现（~1.3 万行）     │
│    static/racecard_help.html    ← 使用说明／更新日志           │
│    tests/test_raceday_embed.py  ← 源码字符串契约              │
└───────────────────────┬─────────────────────────────────────┘
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
┌──────────────────────┐   ┌──────────────────────────────────┐
│ 仓库 FastAPI embed   │   │ SERVER2 j18pro（验收真源）         │
│ Python / uvicorn     │   │ Node src/server.js · PM2 · :3030   │
│ /embed/racecard      │   │ public/racecard.html               │
│ 本地预览、跑 pytest  │   │ public/help.html                   │
└──────────────────────┘   │ silk-cache（HKJC 彩衣代理）        │
                           └──────────────────────────────────┘
                                          │
                                          ▼
                           产品手机强制刷新验收
```

**数据流（现状）**：页面内 `MEETING` → `applyMeeting` → `renderPills` / `renderMeta` / `renderBoard` → `fitScrollColWidths`。  
**接真 API 后期望**：拉会／场／马／赔／赛果 → 仍灌进 `applyMeeting`，交互壳不动。

**进程隔离（同 SERVER2）**：

| 进程 | 端口（约定） | 说明 |
|------|--------------|------|
| `j18pro` | **3030** | 本页 |
| `finance-18` | 3000 一带 | 财务，勿动 |
| `cabinet-quoter` | 3020 一带 | 柜面，勿动 |

---

## 4. 单文件前端怎么组织（给读代码的人）

`racecard_board.html` 是**单文件应用**：

1. `<style>`：布局、左锁／右滑表、各弹层、浅／深色覆盖  
2. `<body>`：顶栏、表壳、各 overlay／sheet 的 DOM 骨架  
3. 一个大 `<script>` IIFE：状态、`MEETING`、渲染、事件绑定  

读代码时按主题搜关键字（比从上到下通读快）：

| 主题 | 关键字 |
|------|--------|
| 换会／灌表 | `applyMeeting`, `renderBoard`, `COL_FIT`, `fitScrollColWidths` |
| 赛期 | `raceCalOverlay`, `bindRaceDateCalendar` |
| 心水战绩 | `openTipRecordSheet`, `TIP_STAT_DEFS` |
| 名家贴士 | `openFamousTipsSheet`, `FAMOUS_TIPSTERS_DEMO`, `famousAggregateTips` |
| 水位／马匹详情 | `waterSheet`, `openHorseSheet`（详情正文待重设计，暂只彩衣／马号／马名） |
| 主题 | `data-theme`, `j18-racecard-theme` |
| 弹层互斥 | `closeAllBoardOverlays` |

**列宽硬规则（API 接上后也要守）**：右滑列按当场最长内容自动量宽；数据到分隔线固定 2px；禁止再搞 sm/md/wide 手写列宽体系。

---

## 5. 线上 Node 宿主做什么

路径：`/root/j18pro`

| 路径 | 说明 |
|------|------|
| `src/server.js` | 静态服务 + `/silk/:code` 代理缓存 HKJC 彩衣 + `/health` |
| `public/racecard.html` | 排位页（由仓库 `racecard_board.html` 覆盖） |
| `public/help.html` | 使用说明 |
| `VERSION` + `package.json` `version` | **必须一致**；每次功能发布 bump |
| `ecosystem.config.cjs` | PM2：`j18pro`，fork，PORT=3030 |

版本显示：改完功能后 bump（例 `0.2.416` → `0.2.417`），`pm2 restart j18pro`。手机要**强制刷新**。

---

## 6. 仓库 Python 侧与本页的关系

同仓还有完整「J18 量化／爬虫／预测」Python 栈（见根目录 `DEVELOPMENT_REPORT.md`、`AUTOMATION_HANDBOOK.md`、`docs/JJJC_DOWNSTREAM_CONTRACT.md`）。

对排位页接手同事：

- **日常改 UI**：几乎只动 `static/racecard_board.html`（+ 偶尔 `racecard_help.html` / 测试）。  
- **本地看页／锁契约**：`raceday_embed_api.py` 的 `/embed/racecard` + `pytest tests/test_raceday_embed.py`。  
- **接真数据时**：才需要对照 JJJC／upcoming 表字段；交互仍落在前端 `applyMeeting`。

仓库根 `VERSION`（如 `1.1.0`）是**整仓 Python 应用**版本，与 SERVER2 j18pro 的 `0.2.x` **不是同一计数器**。

---

## 7. 开发 → 测试 → 部署（最短路径）

```bash
# 1) 改
#    static/racecard_board.html
#    （若有功能终态）static/racecard_help.html 的 FEATURE_CHANGELOG 追加一条

# 2) 测
python3 -m pytest tests/test_raceday_embed.py -q -k 'racecard_board or help_changelog'

# 3) 部署到 SERVER2
scp static/racecard_board.html root@120.77.253.95:/root/j18pro/public/racecard.html
scp static/racecard_help.html  root@120.77.253.95:/root/j18pro/public/help.html
# bump /root/j18pro/VERSION 与 package.json 的 version（二者一致）
ssh root@120.77.253.95 'cd /root/j18pro && pm2 restart j18pro'

# 4) 手机强制刷新
#    http://120.77.253.95:3030/racecard.html
```

更新日志规矩：只记**终态**；合并序号本身不算新功能、不另开号。详见 `AGENTS.md`。

---

## 8. 建议接手顺序

1. 手机打开验收地址，点一遍：切场、排序、水位、马匹详情、心水战绩、名家、菜单主题／字号、使用说明。  
2. 在仓库搜 `applyMeeting` / `openFamousTipsSheet` / `fitScrollColWidths`，建立地图。  
3. 跑通 pytest，改一句无关注释确认「字符串契约」会红。  
4. 做一次无行为变更的 scp + bump，确认版本与强制刷新流程。  
5. 再谈接 API：先定 `applyMeeting` 入参形状，再替换 `*_DEMO`。

更细的弹层约定、近期功能、常见坑与自检清单 → [`J18PRO_RACECARD_HANDOFF.md`](./J18PRO_RACECARD_HANDOFF.md)。

---

## 9. 范围边界（避免改错系统）

| 属于本交接 | 不属于本交接 |
|------------|--------------|
| j18pro 排位 HTML／CSS／JS | finance-18、100852、cabinet-quoter |
| help 更新日志 | 旧站 famousfree 整页（仅 UX 参考） |
| embed 预览与 racecard 契约测试 | 因子模型数学大改（见 FACTOR_MODEL_DESIGN） |
| 部署 SERVER2 j18pro | 擅自重启同机其它 PM2 应用 |

有产品歧义：先问产品，再改 UI。演示字段与真 API 不一致时：**壳不变、数据层可替换**。
