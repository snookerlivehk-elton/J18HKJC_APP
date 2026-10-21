# j18pro 排位（Flutter）

`apps/j18pro_racecard/` 是排位页的 **Flutter 重写** 工程（Phase 7C 走位图）。这不是 Capacitor，也不是用 WebView 包一层 `static/racecard_board.html`。

## 双轨

- **Web** `static/racecard_board.html` 仍是验收真源，直到某份阶段文档**书面宣布**切换。
- 本 App 并行开发。不要删除、停更或改写 Web 页的业务行为。
- 线上 SERVER2 / PM2 部署不在本工程范围内。
- 产品界面文案用繁体（zh-HK）。本 README 用简体说明工程。

## 状态管理（全项目锁定）

**Riverpod**（`flutter_riverpod`）。禁止再引入 Bloc / Provider 混用。

- 入口：`lib/main.dart` 的 `ProviderScope`
- 当前状态：`lib/app/theme_mode_controller.dart` 的 `themeModeProvider`
- 主题偏好键与 Web `localStorage` 相同：`j18-racecard-theme`（`light` / `dark`，缺省为浅色）

## 目录

```text
lib/
  app/        应用壳、路由、主题 token、主题状态
  domain/     `Meeting` / `Race` / `Runner`（不可变，对齐 Web `MEETING`）
  data/       `RaceRepository`、`DemoMeetingRepository`、`ApiRaceRepository`
  features/   `RacecardPage`：场次胶囊、赛况条、时间轴、指数/派彩胶囊、左锁右滑主表
  widgets/    跨功能控件（主题开关）
```

路由：`RacecardPage`，路径 `/`。主表上方是赛况灯、元信息、赛前时间轴，以及综合指数 / 赛果派彩胶囊。竖屏主表左锁马号/马名，右列按当场内容量宽。默认仍是檔位、獨贏、位置、近績。菜单「馬匹數據排序」可显隐和调整顺序，并写回 `SharedPreferences`（键 `j18-scroll-col-layout-v1`，与 Web `localStorage` 同名）。负磅、骑师等额外字段默认在「未顯示」。点马号或马名打开马匹详情；详情里的「水位」打开全场水位表。详情里的「綜合評述」换成综合评述弹层：上面是评述，下面是「為該馬匹創建個人筆記」和「點擊查看歷史筆記」。个人笔记写入 `SharedPreferences`，键 `j18-horse-notes-v1`。JSON 为 `{ "v": 1, "notes": { "2026-09-23:5:5": { "text": "", "history": [] } } }`，笔记键是 `日期:场次:马号`。某匹马一旦有保存记录，就不再使用演示种子，空字符串也算。Web 只把笔记留在内存里；这里为了重启后还在，改成落地保存。这不是心水勾选列 `j18-tip-note-picks-v1`。主表双行「評述／筆記」单元格是「Web only 暂缓」。马匹详情「騎練合作」，以及显示出来的「騎師」「練馬師」格，打开骑练合作战绩。这是按马号、场次和人名长度算出的演示数据，api_jjjc 没有合作战绩导出。退出马不打开。主表马匹列表下面是连赢矩阵：上三角赔率、下三角指数，可在「正Q」和「位置Q」之间切换，点一格会同时高亮赔率和指数。赔率由獨贏或位置合成（正Q 乘 0.26，位置Q 乘 0.62），没有真实 QIN／QPL 盘。超过 14 匹时矩阵可以横滑，首行首列不做 Web 的 sticky。日期行右侧「走位圖」打开速势走位图，请求 `https://consvc.hkjc.com/-/media/Sites/JCRW/SpeedPro/current/sg_race_` 加场次号（与 Web `SPEEDMAP_CMS` 相同）。响应按 `zh-hk` 整块优先，否则 `en-us`；`RaceMap` 必须是 `data:image` 的 base64 PNG。正文前会去掉 UTF-8 BOM。缓存只在内存，键是场次号，TTL 10 分钟（线上 `Cache-Control: max-age=600`）。失败和「此場暫無走位圖」不写入缓存。Web 把缺图和断网都显示「暫未能載入走位圖，請稍後再試」；这里缺图单独用「此場暫無走位圖」。这条 URL 是马会当前赛事，不是已选赛日。Web 从「預計跑法」列打开；该列不在本 App 的列目录里（加进去会改默认四列），所以入口是日期行按钮，弹层仍是同一张全场图。菜单「個人心水和戰績」打开心水战绩：今日心水、战绩统计（本日 / 本赛季、规则）、心水名家榜（演示数据）。菜单「名家」打开名家贴士：场次胶囊、综合心水、临场 / 早餐 / 马房、胜率和冠亚季殿。这两层不是同一页。日期只跟全局赛日，没有独立月历。内容短时弹层跟着收缩，内容超出屏幕时在弹层内滚动。同一时间只保留一个主弹层。燕尾标三态存在 `RacecardController`，换场保留，换赛日清空。从 stub 回到 `2026-09-23` 时回到第 5 场。顶栏菜单含赛期月历（香港马 / 外国马）、主题和字号。未设置 `JJJC_API_BASE` 时仍用演示快照。设置后香港赛日改走 api_jjjc 的排位和赛果；断网显示「未能連線，請檢查網絡」，空赛日显示「該日暫無賽事」。马匹详情里的彩衣走 HKJC CDN，失败时退回色块。

## 如何运行

需要 Flutter **3.x** 稳定版（本脚手架在 Flutter 3.47.7 / Dart 3.13.5 上创建）。

```bash
cd apps/j18pro_racecard
flutter pub get
flutter analyze
flutter test
flutter run
```

`flutter run` 会选用本机已连接的设备。常见目标：

| 环境 | 命令 |
|------|------|
| iOS Simulator（仅 macOS） | `flutter run -d ios` |
| Android Emulator | `flutter run -d android` |
| Chrome | `flutter run -d chrome` |
| 本机 Linux 桌面（需 GTK 3 开发包） | `flutter run -d linux` |
| 无窗口的 Web 服务 | `flutter run -d web-server --web-port 8080` |

打开后应看到标题「排位」，顶栏右侧有「深色」开关。浅色 / 深色 token 对齐 Web `--nav` / `--green` / `--orange`（以及 `--nav-2`、`--page`、`--text` 等骨架色），没有搬完整份 CSS。

### 本仓库约定的最低系统版本

- Android `minSdk` 24（Flutter 3.47 默认 `flutter.minSdkVersion`）
- iOS Deployment Target 15.0（`flutter create` 生成值）

### 字体

已打包 **Noto Sans TC** 子集（OFL，`assets/fonts/`，字重 400 / 700），不在运行时请求 Google Fonts。子集覆盖当前界面和这份 fixture 里的字。再加栏目或马名时要同步扩大子集，否则列宽会按缺字测量。

## 演示 fixture 怎么来的

文件：`assets/fixtures/meeting_20260923.json`。

1. 从 `static/racecard_board.html` 的 `let MEETING = { ... }` 抽出对象。源码里这段已是合法 JSON，没有再改 HTML。
2. 只保留第 1、5、6 场（精简 3 场；全日 9 场仍在 Web 里）。
3. 第 6 场套用页面在绘制前执行的 `ensureRace6Has10WithScratch7`：按马号留前 10 匹，7 号「雙劍合璧」`scratched: true` 且独赢/位置为 `null`，`meta` 末尾加上「（演示 10 匹，7號退出）」。字面量里所有马的 `scratched` 都是 `false`，这个标记是 Web 演示脚本加上的，不是 Flutter 另造的马。

`DemoMeetingRepository` 在香港范围下提供这一日（`2026-09-23`）的真实快照。其它日期，以及外国马范围，按 Web `buildStubMeeting` 返回一场空卡（马名为「賽事資料載入中」或场地名）。打开时默认第 5 场，与 Web `currentRace = 5` 一致。

接真接口（不设则继续用上面的演示快照）：

```bash
flutter run --dart-define=JJJC_API_BASE=https://apicc.up.railway.app
```

`JJJC_RESULTS_API_BASE` 可代替上一行。契约见 `docs/JJJC_DOWNSTREAM_CONTRACT.md`。当前公开目录不要求密钥；若部署要求 Bearer，再加 `--dart-define=JJJC_API_KEY=...`。彩衣根路径可用 `J18_SILK_BASE` 换成同源代理，默认是 `https://racing.hkjc.com/racing/content/Images/RaceColor`。

## 非目标

表头多列排序的真实面板、主表综合评述双行单元格（「Web only 暂缓」）、顶栏直播、性能大改、WebView。关闭综合评述时，未保存的草稿会先写入本地，包括点遮罩；Web 在有未保存内容时会拦住遮罩关闭。没有独立日期选择。名家贴士和心水战绩都是演示数据。两个「当前场之前视为已派彩」开关默认关闭，需要时用 `J18_DEMO_TIP_SETTLE_BEFORE_CURRENT` 和 `J18_DEMO_FAMOUS_SETTLE_BEFORE_CURRENT` 打开。心水战绩用每场最多 6 个最短独赢，主表没有心水勾选列。名家场次胶囊只切换贴士页，不改主表当前场。水位在详情里的水位表，不占主表一列，也不能在列排序里打开。目录里的 `live_odds` 没有 export 路径，所以位置赔率仍空，独赢只在赛果 `win_odds` 有值时填上。外国马仍是 stub。赛况元信息过长时省略，不跑马；开跑状态灯不脉冲。
