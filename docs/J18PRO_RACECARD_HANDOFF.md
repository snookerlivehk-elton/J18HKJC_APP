# j18pro 排位页开发交接说明

> 面向接手同事的工程文档。产品文案用繁体（zh-HK）；本文用简体方便阅读。  
> 文档对应线上约 **`0.2.364`**（以 SERVER2 `package.json` / `VERSION` 为准）。  
> 主工作文件：`static/racecard_board.html`（单文件 HTML + CSS + JS，约 1.2 万行）。

---

## 1. 这是什么

j18 手机端风格的 **赛马排位页原型 / 业务页**：

- 顶栏媒体入口、菜单、赛期表
- 场次胶囊、赛况元信息
- 综合指数 / 赛果派彩胶囊
- 左锁列 + 右滑数据表（自动量列宽）
- 水位、马匹详情、心水笔记、心水战绩、**名家贴士** 等弹层

当前阶段：**前端演示数据为主**（内嵌 `MEETING` 快照 + 若干 DEMO）。接真 API 时尽量只换数据入口，少动交互壳。

---

## 2. 两条运行路径（别混）

| 路径 | 用途 | 入口 |
|------|------|------|
| **本仓库 FastAPI embed** | 本地/测 HTML、契约测试 | `GET /embed/racecard` → 读 `static/racecard_board.html`（见 `raceday_embed_api.py`） |
| **SERVER2 j18pro（验收真源）** | 产品手机验收 | 静态文件 `/root/j18pro/public/racecard.html`，PM2 `j18pro`，端口 **3030** |

验收地址：

```text
http://120.77.253.95:3030/racecard.html
```

**改完必须同步到 SERVER2 再验收。** 只改 Git、不部署 = 手机上看不到。

同机还有 `finance-18`、`cabinet-quoter`、`onlynow` 等进程——**只动 j18pro**，不要重启/改其它服务。

---

## 3. 关键文件

| 路径 | 说明 |
|------|------|
| `static/racecard_board.html` | **唯一主实现**（结构 / 样式 / 逻辑都在此） |
| `raceday_embed_api.py` | 仓库内 `/embed/racecard` 挂载 |
| `tests/test_raceday_embed.py` | 大量字符串断言锁 UI/行为（`test_racecard_board_prototype_serves`） |
| `AGENTS.md` | Cursor Cloud 排位页硬规则（部署、验收、列宽、文案语言） |
| `docs/JJJC_DOWNSTREAM_CONTRACT.md` | 下游 JJJC 数据契约（接 API 时对照，非本页交互说明） |

线上对应：

```text
仓库: static/racecard_board.html
  ↓ scp
SERVER2: /root/j18pro/public/racecard.html
版本: /root/j18pro/VERSION + package.json 的 version
进程: pm2 restart j18pro
```

---

## 4. 页面结构（自上而下）

```text
header.topbar
  左: 直播 TV · 收音机 · 返回
  中: 「排位」
  右: 名家 · 菜单（赛期 / 心水战绩 / 列排序 / 主题 / 字号…）
公告栏 .anno
场次胶囊 #racePills + 赛况元信息
洞察区: 时间轴 #timeScrub + 胶囊轨 #capsuleRail（综合指数 / 赛果派彩）
主表 #boardMain（左锁 + 右滑列）
若干 .cal-overlay 弹层（赛期、心水战绩、名家贴士、列排序、派彩明细…）
马匹详情 / 水位等 sheet
```

### 4.1 顶栏约定（近期）

- **返回**在左侧收音机后面（`#navBack`）
- **名家**在右侧菜单旁（`#navFamousBtn`）→ 打开名家贴士弹层
- **菜单** `#navMenuBtn` → 含赛期表、心水战绩、马匹数据排序、深浅色、字号缩放等

### 4.2 弹层一览

| Overlay / Sheet ID | 功能 |
|--------------------|------|
| `raceCalOverlay` | 赛期表（全局日期） |
| `tipRecordOverlay` | 心水战绩 |
| `famousTipsOverlay` | 名家贴士 |
| `colSortOverlay` | 马匹数据排序 / 显隐 |
| `payoutDetailOverlay` | 派彩明细表 |
| `synthReviewOverlay` | 综合评述 + 笔记 |
| `speedMapOverlay` | 走位/速度相关 |
| `jtCollabOverlay` | 骑练合作战绩 |
| `waterSheet` / `horseSheet` | 水位、马匹详情 |

约定：打开弹层前调用 `closeAllBoardOverlays(exceptId)` 统一互斥（含水位 / 马匹详情）。  
赛期表 `closeRaceDateCalendar` **仅在 overlay 原本已打开时**才 `loadMeetingForDate`；Escape 由顶栏处理链统一接管（含赛期 / 派彩）。  
心水战绩 / 名家贴士顶边对齐 **公告栏顶**（`tipRecordOverlayAnchorTop`），高度共用 `syncFillSheetHeight`（量高前必须解除 `max-height`）。号圈浅/深色样式与心水、名家共用同一组选择器。

---

## 5. 数据与状态（现状）

### 5.1 全局会议数据

- `let MEETING = { date, m, d, weekday, courseLabel, races: [...] }`
- `let currentRace`：当前场次号
- 换会：`applyMeeting(payload)` → `renderPills` / `renderMeta` / `renderBoard`
- 赛期表选择后应走同一套全局日期（**名家贴士不单独选日期**）

场次对象常见字段：`num`, `name`, `time`, `meta`, `runners[]`, 派彩相关（`paid` / dividends 等）。  
马匹：`no`, `name`, `draw`, `jockey`, `trainer`, `win`, `place`, `scratched`, `silk`, … 以及笔记/评述等扩展字段。

### 5.2 仍是演示的部分（接 API 优先替换）

| 符号 / 区域 | 说明 |
|-------------|------|
| 内嵌 `MEETING` | HKJC 排位 + WIN/PLA 快照风格演示 |
| `ensureTipNoteDemoForMeeting` | 心水标记演示填充 |
| `TIP_LEADERBOARD_DEMO` | 心水名家榜演示 |
| `FAMOUS_TIPSTERS_DEMO` / `famousTipsForTipster` | 名家名单与按 seed 生成的心水号 |
| 部分指数 / 派彩 / 水位 | 页面内仍有「演示」入口或合成逻辑 |

**名家综合心水权重（前端演示规则）：**  
票数优先；同分再比「提供早晚」（早餐 > 马房 > 临场）与名单内順位。真数据到来后应改为服务端聚合或明确产品公式。

**胜率展示：** 名家行显示 `wins/plays`（规则对齐心水战绩统计口径的展示方式）；演示数字写在 tipster 对象上。

---

## 6. 必须遵守的硬规则

1. **产品 UI 繁体（zh-HK）**；对内沟通可用简体。  
2. **视觉渐进**：钢蓝顶栏、绿/蓝场次块、浅底斑马；勿大改成另一套品牌风。  
3. **右滑列宽**（快照与日后 API 都必须遵守）：  
   - 每列按当场该字段最长内容（含表头）自动量宽  
   - 数据到分隔线固定 **2px**（`COL_FIT.dataToRulePx` / `--scroll-col-gap`）  
   - **禁止**再写死 sm/md/wide/xl 或按字段手填列宽  
   - 换场、排序、灌新数据：`applyMeeting` → `renderBoard` → `fitScrollColWidths`  
4. **浅/深色对比度**：弹层内未中号码圈不要继承胶囊「白字半透明底」。应对齐心水战绩：  
   - 浅色：白底 + `#1e2a38` 字 + 橙边  
   - 深色：深底 + 浅字 + 橙边  
   - 冠亚季殿 `is-w/q/p/4` 保持色底白字  
5. **验收**：用户手机强制刷新线上页；**不要**依赖录屏/截图 walkthrough 作为交付。  
6. **隔离**：只部署 j18pro，不动 finance-18 / 100852 / cabinet-quoter。

---

## 7. 近期已完成功能（接手上下文）

按时间从近到远（便于对照 PR / 版本）：

1. **名家贴士号圈浅色对比度**（约 `0.2.364`）  
   - 未中号可读；与心水战绩一致  
2. **名家入口 + 名家贴士弹层**（约 `0.2.363`）  
   - 顶栏布局调整；弹层含场次胶囊、综合心水、临场/早餐/马房、胜率、冠亚季殿  
3. **心水战绩**一整套  
   - 今日心水、战绩统计（本日/本赛季）、名家奖金榜  
   - 高度贴底/短内容收缩、深色可滚、灰色字对比度  
   - 弹层顶对齐公告栏  
   - 「每场预计奖金」类实验已按产品要求 **revert 掉**，勿擅自加回  

相关 PR 示例（栈会随合并变化，以 GitHub 为准）：

- #97 名家贴士弹层（base: `cursor/j18pro-racecard-board-6fd6`）  
- #98 名家号圈对比度（base: `cursor/famous-tips-sheet-6fd6`）  
- #61 等更早的 j18pro 排位基建（赛期表、状态灯、指数胶囊…）

---

## 8. 开发工作流

### 8.1 本地改代码

```bash
# 主文件
static/racecard_board.html

# 仓库内预览（需本机起 embed API）
# 例如：uvicorn raceday_embed_api:app --port $PORT
# 浏览器打开 /embed/racecard
```

### 8.2 测试

```bash
# 排位页相关断言（改 UI 后几乎必跑）
python3 -m pytest tests/test_raceday_embed.py -q -k racecard_board

# 抽主脚本做语法检查（从 HTML 抽出最大 <script>）
# node --check /tmp/rc_main.js
```

`test_racecard_board_prototype_serves` 用 **HTML 源码包含某字符串** 锁定行为（顶栏顺序、弹层 id、关键 CSS/函数名等）。改文案或改结构时同步改测试。

### 8.3 部署到 SERVER2（验收必做）

```bash
# 1) 上传页面
scp static/racecard_board.html root@120.77.253.95:/root/j18pro/public/racecard.html

# 2)  bump 版本（VERSION + package.json，二者一致）
#    例：0.2.364 → 0.2.365

# 3) 重启
ssh root@120.77.253.95 'cd /root/j18pro && pm2 restart j18pro'

# 4) 自检
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3030/racecard.html
```

SSH 密钥：环境里的 `SERVER2_SSH_PRIVATE_KEY`（或既有 `~/.ssh/server2_key`）。

手机验收：**强制刷新**（避免缓存旧 HTML）。版本号可在 `package.json` / `VERSION` 或发布说明中告知产品。

### 8.4 Git / PR 习惯（Cloud Agent 约定）

- 功能分支名：`cursor/<描述>-6fd6`（小写）  
- 排位页功能栈常见 base：`cursor/j18pro-racecard-board-6fd6`（再往上是 `main`）  
- 小修复可叠在上一功能分支上开 PR  
- 提交信息简洁说明「改了什么 / 为什么」

---

## 9. 关键代码锚点（便于搜索）

| 主题 | 搜索关键字 |
|------|------------|
| 列宽 | `COL_FIT`, `fitScrollColWidths`, `applyMeeting`, `renderBoard` |
| 赛期 | `bindRaceDateCalendar`, `raceCalOverlay`, `menuRaceDate` |
| 心水战绩 | `openTipRecordSheet`, `TIP_STAT_DEFS`, `syncTipRecordSheetHeight` |
| 名家贴士 | `openFamousTipsSheet`, `FAMOUS_TIPSTERS_DEMO`, `famousAggregateTips`, `ft-agg-nos` |
| 号圈渲染 | `renderCapNoHtml`, `payoutFinishNosForRace`, `tipFinishKindByNo` |
| 主题 | `data-theme`, `j18-racecard-theme` |
| 顶栏 | `navFamousBtn`, `navBack`, `navMenuBtn`, `navRadio` |

---

## 10. 常见坑

1. **只 commit 不部署** → 手机永远旧版。  
2. **弹层高度**：量高前若仍带 `max-height`，深色模式容易「内容够高却滚不动」。照抄 `syncTipRecordSheetHeight` / `syncFamousTipsSheetHeight`。  
3. **号圈对比度**：新列表若直接用 `.cap-no` 默认（为胶囊白字设计），浅色必翻车；在 sheet 内覆写浅/深两套。  
4. **列宽手调**：产品/设计临时要求「某列再宽一点」时，仍应通过内容或 `FIXED_SCROLL_COL_W` 的既有机制处理，不要引入一套 sm/md 体系。  
5. **互斥弹层漏关**：新 `openXxx` 记得 `closeFamousTipsSheet` / `closeTipRecordSheet` 等。  
6. **测试很脆但是有意的**：删掉一句产品文案可能导致 pytest 红——先改测试再改文案，或保持断言与 UI 同步。

---

## 11. 建议的下一步（给接手同事）

1. **接真会数据**：用赛期表选中的日期拉 racecard / odds / results，写入 `applyMeeting`；去掉或降级内嵌 `MEETING`。  
2. **接名家 API**：替换 `FAMOUS_TIPSTERS_DEMO` 与 `famousTipsForTipster`；综合心水与胜率改为后端或统一公式。  
3. **接心水战绩真统计**：替换 `TIP_LEADERBOARD_DEMO` 与本地 tip 估算。  
4. **工程拆分（可选）**：单文件过大时，可逐步拆 CSS/JS 模块，但需保证 SERVER2 仍能以单页或构建产物部署到 `public/racecard.html`。  
5. **缓存策略**：若上 CDN/强缓存，需与「强制刷新验收」流程对齐（query `?v=` 或短 Cache-Control）。

---

## 12. 快速自检清单（改完打勾）

- [ ] 只改了 j18pro 相关文件  
- [ ] UI 文案为繁体  
- [ ] 列宽仍走 `fitScrollColWidths`，无手写列宽体系回潮  
- [ ] 新弹层/号圈有浅色 + 深色可读样式  
- [ ] `pytest -k racecard_board` 通过  
- [ ] 已 scp 到 SERVER2 并 bump 版本 + `pm2 restart j18pro`  
- [ ] 手机强制刷新验收地址通过  

---

## 13. 联系与范围边界

- **本页范围**：j18pro 排位交互与演示数据。  
- **非本页**：finance-18、柜面报价、JJJC sync 管道细节（见 `docs/JJJC_DOWNSTREAM_CONTRACT.md`）、旧站 `j18.hk` famousfree 整页（仅作 UX 参考；新设计是弹层且日期跟全局赛期）。  

有产品歧义时：优先问产品确认，再改 UI；演示数据与真 API 字段不一致时，以「交互壳不变、数据层可替换」为原则推进。
