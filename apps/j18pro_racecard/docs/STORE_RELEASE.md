# 上架准备（仓库内能做的部分）

本文件是 Phase 8 的操作说明。商店包不是新功能。这里**没有**上传 TestFlight，也**没有**上传 Play Console。证书、账号和隐私政策网址要人工完成。

Web `static/racecard_board.html` 不在这次改动里。不要用 WebView 或 Capacitor 包网页。

## 版本

唯一来源是 `pubspec.yaml`：

```yaml
version: 1.0.0+1
```

`1.0.0` 是版本名，`1` 是构建号。它和 Web 的 `0.2.x` 没有对应关系。下次上架只改这一行，再重新构建。

| 平台 | 字段 | 这次的值 |
|------|------|----------|
| iOS | `CFBundleShortVersionString`（`FLUTTER_BUILD_NAME`） | 1.0.0 |
| iOS | `CFBundleVersion`（`FLUTTER_BUILD_NUMBER`） | 1 |
| Android | `versionName` | 1.0.0 |
| Android | `versionCode` | 1 |

iOS 工程用 `$(FLUTTER_BUILD_NAME)` / `$(FLUTTER_BUILD_NUMBER)`，不要在 Xcode 里另写死一个版本。`ios/Flutter/Generated.xcconfig` 是构建时生成的，不要提交。

包名：

- Android `applicationId`：`hk.j18.j18pro_racecard`
- iOS `PRODUCT_BUNDLE_IDENTIFIER`：`hk.j18.j18proRacecard`

两边拼写不同，是现有工程的包名。上架前不要改，否则会变成另一个商店应用。

## 双轨发布

Web 保留，继续作为网站的验收真源。Flutter 是单独的商店应用。

| | Web | Flutter |
|--|-----|---------|
| 位置 | `static/racecard_board.html` | `apps/j18pro_racecard/` |
| 版本 | 网站自己的 `0.2.x`（交接文档约 `0.2.364`） | `1.x.y` |
| 谁发布 | 现有网站流程。本仓库的上架步骤不部署 SERVER2 | TestFlight / Play 内测轨，由持有账号的人上传 |
| 能否同一天 | 可以，但不要求版本号相同 | 可以晚于或早于网站 |

两边用同一份演示日 `2026-09-23` 做回归。网站改版不要等商店审核；商店包也不要为了跟上网站的 `0.2.x` 而改 `pubspec.yaml`。

## iOS

### 隐私清单

`ios/Runner/PrivacyInfo.xcprivacy` 已放进 Runner 的 Resources。

- 不追踪（`NSPrivacyTracking` = false）
- 不声明收集数据类型。主题、列配置、马匹笔记只留在本机 `UserDefaults`
- Required Reason API：`NSPrivacyAccessedAPICategoryUserDefaults`，原因 `CA92.1`（只读写本应用自己的偏好）
- 没有照片、相机、定位、麦克风、通讯录。`Info.plist` 故意不写这些用途字符串。用不到的用途字符串不要补
- Flutter 引擎和插件如果自带隐私清单，由它们的包提供。这里不重复声明引擎的文件时间戳等 API

### ATS

没有 `NSAppTransportSecurity` 例外。系统默认只允许 HTTPS。

会连的主机：

- `https://consvc.hkjc.com`（走位图）
- `https://racing.hkjc.com`（彩衣）
- `JJJC_API_BASE` 若设置，必须是 `https://`

不要加 `NSAllowsArbitraryLoads`。以后若接口是明文 HTTP，应改服务器，而不是放宽 ATS。

### 加密出口

`Info.plist` 已设 `ITSAppUsesNonExemptEncryption` = false。应用只用系统 HTTPS，没有自备加密算法。

### 登录

没有账号系统，不需要 Sign in with Apple，也不需要账号删除入口。

### 签名与 TestFlight（需人工）

1. 用 Apple Developer 账号注册 App ID `hk.j18.j18proRacecard`。
2. 在 Xcode 打开 `ios/Runner.xcworkspace`，Signing 选该 Team。Distribution 证书和描述文件由 Xcode 或开发者网站签发。不要把 `.p12`、描述文件密码放进仓库。
3. 在 Mac 上构建：

   ```bash
   cd apps/j18pro_racecard
   flutter build ipa --release
   ```

4. 用 Transporter 或 Xcode Organizer 把 `build/ios/ipa/*.ipa` 交到 App Store Connect，再在 TestFlight 加测试员。
5. 本环境没有 Apple 账号，**没有**执行上传。TestFlight 可安装 = 需人工。

## Android

### 权限

已核对三个清单：

| 清单 | 权限 |
|------|------|
| `src/main` | `INTERNET`。正式包要拉走位图、彩衣和可选 API |
| `src/debug`、`src/profile` | `INTERNET`。Flutter 工具热重载也要用 |

没有相机、麦克风、定位、存储、通知、开机启动、前台服务。没有可删的多余权限。`PROCESS_TEXT` 的 `<queries>` 是 Flutter 引擎自带的包可见性声明，不是权限。

### 后台

没有后台任务、没有前台服务、没有定时唤醒。Android 12 及以后的后台启动限制用不上，也不需要豁免。应用离开前台后不应继续联网。

### 签名（需人工）

`android/.gitignore` 已忽略 `key.properties`、`*.jks`、`*.keystore`。密钥放在仓库外。

四个环境变量要一起设置，缺一则正式构建仍用 debug 签名（只能本机安装，不能上传 Play）：

```bash
export J18_UPLOAD_STORE_FILE="$HOME/keystores/j18pro-upload.jks"
export J18_UPLOAD_STORE_PASSWORD="..."
export J18_UPLOAD_KEY_ALIAS="upload"
export J18_UPLOAD_KEY_PASSWORD="..."
```

生成密钥（在自己的机器上执行，不要把文件提交）：

```bash
keytool -genkeypair -v \
  -keystore "$HOME/keystores/j18pro-upload.jks" \
  -alias upload \
  -keyalg RSA -keysize 2048 -validity 10000
```

构建：

```bash
cd apps/j18pro_racecard
flutter build appbundle --release
```

产物在 `build/app/outputs/bundle/release/app-release.aab`。上传到 Play Console 内测轨。本环境**没有**上传。

未设置上述变量时，`flutter run --release` 继续用 debug 签名，方便本机安装。

## 崩溃上报与分析

延后。仓库里没有接入 Firebase、Sentry 或其他 SDK，默认构建不会上报。

以后若要加，用编译开关，默认关闭：

```bash
flutter build ipa --dart-define=J18_CRASH_REPORTING=true
```

未定义该变量时必须保持关闭。隐私政策写上供应商和收集字段之前，不要把马匹笔记或赛日标识送出设备。

## 仍要人工完成

- Apple 证书、App Store Connect、TestFlight 上传与安装验证
- Play Console 应用、上传密钥、内测轨
- 把审核稿里的隐私政策占位网址换成真实页面
- 按 `STORE_REVIEW_DRAFT.md` 截图
- 商店问卷（年龄、博彩：本应用不接受投注、不连投注账户）
- 若不想用 Flutter 默认图标，先换 iOS AppIcon 和 Android `mipmap`
