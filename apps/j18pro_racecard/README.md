# j18pro 排位（Flutter）

`apps/j18pro_racecard/` 是排位页的 **Flutter 重写** 工程（Phase 4 菜单与赛期）。这不是 Capacitor，也不是用 WebView 包一层 `static/racecard_board.html`。

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
  data/       `RaceRepository` 与 `DemoMeetingRepository`
  features/   `RacecardPage`：场次胶囊、赛况条、时间轴、指数/派彩胶囊、左锁右滑主表
  widgets/    跨功能控件（主题开关）
```

路由：`RacecardPage`，路径 `/`。主表上方是赛况灯、元信息、赛前时间轴，以及综合指数 / 赛果派彩胶囊。竖屏主表左锁马号/马名，右列按当场内容量宽（檔位、獨贏、位置、近績）。燕尾标三态存在 `RacecardController`，换场保留。顶栏菜单含赛期月历（香港马 / 外国马）、主题和字号；名家、个人心水战绩、马匹数据排序先打开占位页，日期跟随全局赛日。

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

## 非目标

表头多列排序的真实面板、综合评述双行单元格、名家与心水的正式内容、马匹资料页、真 API、WebView。菜单里这几项目前是占位（「稍後提供」），没有独立日期选择。右滑列目前固定为檔位 / 獨贏 / 位置 / 近績。赛况元信息过长时省略，不跑马；开跑状态灯不脉冲。
