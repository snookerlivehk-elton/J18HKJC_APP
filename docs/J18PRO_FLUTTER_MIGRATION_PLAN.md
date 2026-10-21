# j18pro 排位页 → Flutter 分阶段改造规划

> 供产品决策与后续 Agent（含 Grok bot）**按阶段下单执行**。  
> 产品 UI 文案：繁体（zh-HK）；本文：简体。  
> 对照现状实现：`static/racecard_board.html`；工程交接：`docs/J18PRO_RACECARD_HANDOFF.md`。  
> **原则：这是重写，不是转换。Web 排位页在 Flutter 未达同等验收前继续维护与部署。**

---

## 0. 总原则（执行时必须遵守）

1. **双轨并行**：Flutter 新建工程目录（建议 `apps/j18pro_racecard/` 或仓库约定路径）；**不要删除或停更** `static/racecard_board.html`，直到某阶段明确「Web 退役」。
2. **一阶段一可验收切片**：每阶段结束必须有可运行 Demo + 验收清单勾选；未完成不进入下一阶段大功能。
3. **数据先契约、后 UI 像素**：优先 `Meeting` / `Race` / `Runner` 模型与仓库对齐；UI 允许「视觉接近」而非第一期就 1:1 抄 CSS。
4. **硬规则继承自 Web**（见 `AGENTS.md` / 交接文档）：
   - 右滑列宽：按当场最长内容自动量，数据到分隔线固定 2px 语义（Flutter 用测量/布局实现同等效果）
   - 弹层互斥：统一 `closeAllExcept`
   - 深浅色对比度（号圈、燕尾标选中色等）
   - 只动 j18pro 相关；不碰 finance-18 等
5. **下单话术模板**（给 Grok bot）：  
   `按 docs/J18PRO_FLUTTER_MIGRATION_PLAN.md 执行 Phase N：<标题>。勿改 Web 验收路径 unless 本阶段清单要求。完成后更新本文件「进度」一节。`
6. **禁止**：在未完成 Phase 0–1 前大面积「把整页 HTML 搬进 WebView 叫 Flutter」——那是 Capacitor 路线，与本规划无关。

---

## 1. 现状模块地图（Web → 逻辑单元）

| 逻辑单元 | Web 锚点（搜索） | Flutter 建议模块 |
|----------|------------------|------------------|
| 会议/场次数据 | `MEETING`, `applyMeeting`, `currentRace` | `domain/meeting.dart`, `RaceRepository` |
| 顶栏 | `topbar`, `navFamousBtn`, `navMenuBtn` | `widgets/top_bar.dart` |
| 赛期表 | `raceCalOverlay`, `loadMeetingForDate` | `features/race_calendar/` |
| 场次胶囊 + 元信息 | `racePills`, `raceMeta` | `features/race_header/` |
| 时间轴 | `timeScrub` | `features/time_scrub/` |
| 综合指数 / 赛果派彩胶囊 | `capsuleRail`, `capsuleIndex`, `capsulePayout` | `features/capsules/` |
| 主列表（左锁+右滑） | `renderBoard`, `fitScrollColWidths` | `features/racecard_table/`（**核心难点**） |
| 燕尾标 | `row-flag`, `cycleRowMark`, `mark-1/2` | 同上 table 内 |
| 心水勾选 | `tip-note`, `tipNotePicks` | `features/tip_note/` |
| 马匹详情 / 水位 | `horseSheet`, `waterSheet` | `features/horse_sheet/`, `features/water_sheet/` |
| 个人心水与战绩 | `tipRecordOverlay`, `openTipRecordSheet` | `features/tip_record/` |
| 名家贴士 | `famousTipsOverlay`, `FAMOUS_*` | `features/famous_tips/` |
| 列排序 | `colSortOverlay` | `features/col_sort/` |
| 综合评述/笔记 | `synthReviewOverlay` | `features/synth_review/` |
| 走位图 | `speedMapOverlay`, `fetchSpeedMap` | `features/speed_map/` |
| 骑练合作 | `jtCollabOverlay` | `features/jt_collab/` |
| 连赢/qin | `qinPanel` | `features/qin/`（可后置） |
| 主题/字号 | `data-theme`, list zoom | `app_theme.dart`, `text_scale` |

---

## 2. 分阶段计划

### Phase 0 — 工程脚手架与规范（地基）

**目标**：可在 iOS Simulator / Android Emulator 跑出空壳 App，CI/本地命令清晰。

**交付**
- Flutter 工程创建（Flutter 3.x 稳定版；约定 min iOS / min Android）
- 目录：`lib/{app,domain,data,features,widgets}`
- 主题骨架：浅色 / 深色（颜色 token 对齐 Web `--nav/--green/--orange` 等，不必一次抄全）
- 路由占位：`RacecardPage`
- README：如何 `flutter run`；与 Web 双轨说明
- （可选）melos / 单包即可

**验收**
- [ ] `flutter analyze` 无 error
- [ ] 真机或模拟器打开见 App 标题「排位」与主题切换开关
- [ ] 文档写明：Web 仍是验收真源，直到 Phase 宣布切换

**非目标**：任何业务列表、弹层。

---

### Phase 1 — 领域模型 + 演示数据（无复杂 UI）

**目标**：用 Dart 表达与 Web 相同的会议结构，UI 可用最简 List 验证。

**交付**
- `Meeting` / `Race` / `Runner` 不可变模型（字段对齐 Web 快照：`no,name,draw,jockey,trainer,win,place,scratched,silk,...`）
- `DemoMeetingRepository`：可先从 Web 导出一份 JSON fixture（或手写精简 2–3 场）
- `RacecardController` / `Riverpod|Provider|Bloc`（任选其一，**全项目锁定一种**）
- 简易页：场次下拉 + 马名列表 + 独赢/位置数字

**验收**
- [ ] 切换场次列表变化
- [ ] 退出马 `scratched` 有区分展示
- [ ] 单测：模型解析 fixture

**非目标**：左锁右滑表、弹层。

**Agent 注意**：此阶段可顺带定义 `RaceRepository` 接口，为 Phase 6 API 留洞。

---

### Phase 2 — 排位主表 MVP（核心）

**目标**：手机竖屏可用的主列表，覆盖 80% 浏览路径。

**交付**
- 顶栏：返回（行为产品再定）、标题「排位」、菜单入口（可先空）
- 场次横向胶囊（`racePills`）
- 主表：
  - 左锁：马号、马名（可先简化彩衣/骑练首字）
  - 右滑列：至少 档位、独赢、位置、近绩（列集合可配置）
  - 斑马纹、深浅色
- **列宽策略 v1**：用 `TextPainter`/`intrinsic` 按当场数据量宽；列间距体现「内容到分隔」的固定空隙语义
- 燕尾标三态：无 → 黄 → 绿 → 无；整行底色联动；**深色选中标必须有色**（对齐 Web 0.2.367 修复）

**验收**
- [ ] 11 场切换流畅，无整页白屏
- [ ] 横滑右列与左锁纵向滚动同步（同一滚动或联动）
- [ ] 浅色/深色下燕尾选中可见
- [ ] 与 Web 同 fixture 对比：场次马匹数量、关键号码一致

**风险点（本阶段最大）**
- 表头排序先不做或只做单列
- 不要第一期就做「综合评述双行单元格」等复杂 cell

---

### Phase 3 — 赛况条 + 胶囊区

**目标**：主表上方信息 denseness 接近 Web。

**交付**
- 赛况状态灯 + 元信息一行（过长可跑马或省略）
- 时间轴 `timeScrub`（可先静态点位 + 拖动改 `scrubPointIdx`）
- 综合指数胶囊 / 赛果派彩胶囊：展开收起、号圈（W/Q/P/4 色）
- 派彩明细页/Sheet（已派彩时）

**验收**
- [ ] 胶囊互斥展开合理
- [ ] 号圈浅色未中可读、深色未中可读（对照 Web 心水/名家号圈规则）
- [ ] 时间轴拖动有状态变化（哪怕仅 UI）

---

### Phase 4 — 全局菜单与赛期

**目标**：日期与菜单成为 App 内全局控制（与 Web「赛期表全局控日期」一致）。

**交付**
- 菜单：赛期、個人心水和戰績、名家、马匹数据排序、主题、字号
- 赛期月历：港/海外范围切换（可先港）、选日 → `repository.load(date)`
- Demo：非快照日用 stub meeting（对齐 Web `buildStubMeeting` 行为或简化）

**验收**
- [ ] 选日后主表数据源切换
- [ ] 名家/战绩弹层**无独立日期选择**，只跟全局选日
- [ ] 深浅色、字号即时作用于主表

---

### Phase 5 — 高频弹层（业务闭环）

按子阶段拆单，避免一次做完爆炸：

#### 5A 马匹详情 + 水位
- 点马号/马名开详情；水位表
- 打开时互斥关闭其它 sheet

#### 5B 個人心水和戰績
- 对齐 Web tip-record：今日心水、统计、名家榜（Demo 可）
- 高度：内容短收缩 / 长则内滚（不要死抄 Web 的 DOM 量高，用 Flutter 约束即可）

#### 5C 名家贴士
- 场次胶囊、综合心水、临场/早餐/马房、胜率、冠亚季殿
- `TIP_SETTLED_TREAT_BEFORE_CURRENT_AS_PAID` 同类演示开关单独配置

#### 5D 列排序
- 显隐与顺序，写回列表列配置

**验收（每个子阶段各自）**
- [ ] 打开/关闭/返回键/系统 back 行为正确
- [ ] 互斥：同时只显示一个主 sheet
- [ ] 繁体文案与菜单命名一致

---

### Phase 6 — 数据接真 API

**目标**：Demo 降级为 fallback，真赛日可看。

**交付**
- `ApiRaceRepository`：对接既有/规划中的 racecard、odds、results（契约参考 `docs/JJJC_DOWNSTREAM_CONTRACT.md`）
- 错误态、加载态、空赛日
- 关闭或默认关闭「当前场次之前视为已派彩」演示开关
- 彩衣：同源代理或 CDN；定义失败占位

**验收**
- [ ] 指定真实赛日可加载（由产品给日期）
- [ ] 断网有明确提示
- [ ] Web 与 Flutter 对同日关键场次马匹数一致性抽检

---

### Phase 7 — 次要能力与打磨

**目标**：对齐长尾 Web 功能。

- 综合评述 + 个人笔记
- 走位图（HKJC SpeedPro fetch + 缓存）
- 骑练合作战绩
- 连赢 qin 面板
- 顶栏直播/收音机（可先占位）
- 无障碍：字号、语义标签
- 性能：场次切换 jank、列表重建

**验收**：产品按清单点验；允许个别项标「Web only 暂缓」。

---

### Phase 8 — 上架准备

**目标**：商店包，不是功能新开。

- iOS：证书、隐私清单、ATS、账号登录政策（若需）
- Android：签名、权限、后台限制
- 版本号与 Web `0.2.x` 脱钩，使用 App `1.x.y`
- 崩溃上报、基础分析（可选）
- 明确是否保留 Web；若保留，写明双端发布流程

**验收**
- [ ] TestFlight / 内测轨可安装
- [ ] 商店审核材料草稿齐

---

## 3. 推荐技术选型（可调整，但要锁定）

| 项 | 建议 | 说明 |
|----|------|------|
| 状态管理 | Riverpod 或 Bloc（二选一） | Phase 0 锁死，禁止混用 |
| 网络 | `dio` + 简单 repository | |
| 本地 | `shared_preferences`（主题/列配置/心水） | 对齐 Web localStorage 键语义可迁移 |
| 表格 | 自研 `CustomScrollView` + 横滑；或评估 `two_dimensional_scrollables` | Phase 2 尖刀 |
| 字体 | 思源/Noto Sans TC 打包 | 勿强依赖 Google Fonts 运行时下载 |
| 设计 | 先「功能等价」，像素完美放 Phase 7 | |

---

## 4. 与 Capacitor 路线的关系

- **本规划 = Flutter 重写。**
- 若中途需要「先上架」：可并行走 Capacitor 包 Web，**不阻塞**本规划；不要把 Capacitor 工程误称为 Phase 完成。
- Agent 接单时若用户说「先上架」，应确认走 Capacitor 文档还是继续本 Flutter 规划。

---

## 5. 每阶段 Agent 工作流（给 Grok bot）

1. 阅读本文件对应 Phase + `J18PRO_RACECARD_HANDOFF.md` 相关节  
2. 开分支：`cursor/flutter-phaseN-<slug>-6fd6`  
3. 只改本阶段范围；Web 文件默认不动（除非清单写明双端同步文案）  
4. 更新下方「进度」表  
5. 本地 `flutter analyze` + 阶段验收清单  
6. PR 描述贴上本阶段验收勾选结果  

**回归**：每完成一阶段，用同一 Demo fixture 跑一遍上一阶段验收（防止表头一加、主表裂开）。

---

## 6. 进度（执行时维护）

| Phase | 状态 | 分支/PR | 备注 |
|-------|------|---------|------|
| 0 脚手架 | 完成 | `cursor/flutter-phase0-scaffold-e86b` / https://github.com/snookerlivehk-elton/J18HKJC_APP/pull/104 | 2026-10-21。状态管理锁定 Riverpod。`flutter analyze` 无 error。标题「排位」与深色开关：widget test 通过，并用 Chrome 打开 web 构建核对浅色 `#eef1f5` / 深色 `#1a1f27` 可来回切换。本环境无 iOS Simulator / Android Emulator，真机命令见 `apps/j18pro_racecard/README.md`。Fixture 导出方式已在 Phase 1 落地。 |
| 1 模型+Demo | 完成 | `cursor/flutter-phase0-scaffold-e86b` / https://github.com/snookerlivehk-elton/J18HKJC_APP/pull/104 | 2026-10-21，续在 Phase 0 同一 PR。`Meeting`/`Race`/`Runner` + Riverpod `RacecardController`。Fixture `apps/j18pro_racecard/assets/fixtures/meeting_20260923.json`：从 `static/racecard_board.html` 的 `let MEETING` 抽出第 1/5/6 场（源码已是 JSON，未改 HTML），并套用页面绘制前的 `ensureRace6Has10WithScratch7`（7 号雙劍合璧退出、赔率 null）。`flutter analyze` 无 error；`flutter test` 含 fixture 解析与场次切换。未做左锁右滑表。仓库内无 06 清单文件。 |
| 2 主表 MVP | 完成 | `cursor/flutter-phase0-scaffold-e86b` / https://github.com/snookerlivehk-elton/J18HKJC_APP/pull/104 | 2026-10-21，续同一 PR。竖屏主表：场次胶囊、左锁马号/马名、右列檔位/獨贏/位置/近績按当场 `TextPainter` 量宽（内容到分隔线 2px + 1px 线）。左右同一 `ListView` 行，横滑共用一个 offset。燕尾无→黄→绿→无，深色选中色 `#e8b04a` / `#5dce7a` 不回落到灰。未做表头排序、综合评述双行、胶囊和时间轴。 |
| 3 胶囊+时间轴 | 完成 | `cursor/flutter-phase0-scaffold-e86b` / https://github.com/snookerlivehk-elton/J18HKJC_APP/pull/104 | 2026-10-21，续同一 PR。赛况灯按距开跑分钟（待開賽／出跑道／入閘中／開跑中／已派彩），元信息一行省略。时间轴 10 个静态点，拖动写入 `scrubPointIdx`。综合指数与赛果派彩胶囊互斥展开，箭头下展策略或各场派彩；已派彩才开明细。号圈未中对齐心水／名家（浅色白底橙边，深色 `#2a313c`）。W/Q/P/四色。未做跑马灯、状态灯脉冲、赛期菜单。 |
| 4 菜单+赛期 | 未开始 | | |
| 5A 马匹/水位 | 未开始 | | |
| 5B 个人心水战绩 | 未开始 | | |
| 5C 名家贴士 | 未开始 | | |
| 5D 列排序 | 未开始 | | |
| 6 真 API | 未开始 | | |
| 7 次要+打磨 | 未开始 | | |
| 8 上架 | 未开始 | | |

---

## 7. 风险清单（规划期已知）

1. **主表左右锁死滚动**：Phase 2 唯一可能超时点；宁可砍列数，不要假完成。  
2. **像素级复刻**：勿作为 Phase 2 验收标准。  
3. **双端维护**：Flutter 推进期 Web 仍会改文案/小 bug；关键文案变更要记「需同步 Flutter」或接受短期不一致。  
4. **演示逻辑污染**：`tipRaceSettled` 类开关必须配置化，接真后关闭。  
5. **人员技能**：执行 Agent 需能写 Flutter；若环境无 Flutter SDK，Phase 0 先装环境再动业务。

---

## 8. 第一期建议下单原文（可直接复制给 Grok）

```text
按 docs/J18PRO_FLUTTER_MIGRATION_PLAN.md 执行 Phase 0（工程脚手架与规范）。
创建 Flutter 工程，锁状态管理方案，搭好目录与深浅色主题骨架，RacecardPage 占位可运行。
不要改 static/racecard_board.html 的业务行为。
完成后更新该文档第 6 节进度表，并列出 Phase 1 所需的 fixture 导出方式建议。
```

第二期：

```text
按 docs/J18PRO_FLUTTER_MIGRATION_PLAN.md 执行 Phase 1（领域模型 + 演示数据）。
从现有 Web MEETING 结构导出或手写精简 fixture，实现 Meeting/Race/Runner 与简易场次切换列表。
不要开始左锁右滑主表（那是 Phase 2）。
```

---

## 9. 文档维护

- 本文件路径：`docs/J18PRO_FLUTTER_MIGRATION_PLAN.md`  
- 入口：`AGENTS.md`、`docs/J18PRO_RACECARD_HANDOFF.md` 应链到本文  
- 阶段完成后只更新进度表与「备注」，避免改写已验收阶段的验收标准（若必须改，注明原因与日期）
