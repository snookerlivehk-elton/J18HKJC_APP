# j18pro 排位（Flutter）

`apps/j18pro_racecard/` 是排位页的 **Flutter 重写** 工程（Phase 0 脚手架）。这不是 Capacitor，也不是用 WebView 包一层 `static/racecard_board.html`。

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
  domain/     领域模型（Phase 1 才放 Meeting / Race / Runner）
  data/       仓库实现（后续 Demo / API）
  features/   功能页。Phase 0 只有 features/racecard/racecard_page.dart 占位
  widgets/    跨功能控件（主题开关）
```

路由占位：`RacecardPage`，路径 `/`。没有赛事列表，也没有左锁右滑主表。

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

已打包 **Noto Sans TC** 子集（OFL，`assets/fonts/`，字重 400 / 700），不在运行时请求 Google Fonts。子集只覆盖 Phase 0 界面用字；Phase 2 按列宽测量之前要扩大子集，否则缺字会落到系统回退字体上。

## Phase 1 fixture（尚未实现，只记录导出方式）

1. 打开 `static/racecard_board.html`，定位 `MEETING` 对象字面量。
2. 规范化为 JSON（JS 里未加引号的键、尾逗号要处理）。
3. 放到 `apps/j18pro_racecard/assets/fixtures/meeting_YYYYMMDD.json`。
4. Phase 1 再写 `Meeting` / `Race` / `Runner` 与解析单测。本阶段不要提前建这些模型。

## 非目标（Phase 0）

赛事列表、主表、弹层、赛期、名家、心水、真 API、WebView。
