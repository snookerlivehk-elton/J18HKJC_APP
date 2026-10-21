# 商店审核材料草稿

未提交商店。下面的文案和清单给持有账号的人用。隐私政策网址是占位，不能原样交审。

显示名称与工程一致：**排位**。不要写成香港赛马会官方应用。

## 短介绍（zh-HK）

副标题（30 字以内）：

> 賽馬排位，只供參考

Play 短说明（80 字以内）：

> 香港賽馬排位表。場次、馬匹與走位圖，只供參考，不提供投注。

完整说明：

> 排位顯示賽事場次、馬匹、檔位、獨贏與位置，以及速勢走位圖。可切換淺色和深色，並在本機保存個人筆記。
>
> 本應用只提供資料瀏覽，不接受投注，不代管帳戶，也不連接投注渠道。走位圖來自馬會公開的當前 SpeedPro，不一定等於你在應用內選中的賽日。未配置資料接口時使用內置示範賽日。

## Short description (en)

Subtitle:

> Racecard. Information only.

Play short description:

> Hong Kong racing racecard. Runners and speed maps for reference. No wagering.

Full description:

> Racecard shows race numbers, runners, draws, win and place prices, and a speed map. It supports light and dark themes and keeps personal notes on the device.
>
> The app only displays information. It does not take bets, hold accounts, or link to betting channels. The speed map is the racing authority's current public SpeedPro chart and may not match the meeting date selected in the app. Without a data API it opens a built-in demo meeting.

## 隐私政策网址

```text
privacy_policy_url: https://example.invalid/j18pro-racecard-privacy
```

`example.invalid` 不是可用网址。交审前换成真实 HTTPS 页面，并在页面写明：

- 不设账号
- 笔记、主题、列配置只存在设备上
- 会访问的网站（走位图、彩衣、可选排位接口）
- 当前没有崩溃上报；若以后打开，先改本页再发版

## 截图清单（需人工）

用演示日 `2026-09-23`、默认第 5 场。不要在截图里写测试账号或密钥。

| 商店 | 规格 | 要拍的画面 |
|------|------|------------|
| App Store iPhone | 6.7 吋（或当时 Connect 要求的最大尺寸）至少 3 张 | 主表「排位」；马匹详情；菜单（含深色或字号） |
| App Store iPad | 工程含 iPad 方向，若目标是通用应用则按 Connect 要求补 13 吋 | 同一主表 |
| Play 手机 | 至少 2 张，纵向 | 主表；马匹详情或走位图占位失败时的弹层（不要空白崩溃图） |

建议另备一张深色主表。走位图依赖外网，截图时打不开就改拍「此場暫無走位圖」或主表，不要用浏览器里的网页充数。

图标仍是 Flutter 模板图标。交审前若要换，替换 iOS `AppIcon` 和 Android `mipmap`，不要只换商店后台而仓库仍是默认图标。

## 问卷提示（需人工勾选）

- 不接受真钱投注，不模拟投注，不售卖数字商品
- 无登录、无广告、无追踪（`NSPrivacyTracking` = false）
- 出口加密：已在 `Info.plist` 标 `ITSAppUsesNonExemptEncryption` = false
- 无照片、相机、定位、麦克风权限

## 安装验证

- [ ] TestFlight 可安装 — **需人工**。本仓库没有上传
- [ ] Play 内测轨可安装 — **需人工**。本仓库没有上传
