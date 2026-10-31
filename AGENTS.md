# Agent notes

## Cursor Cloud specific instructions

### j18pro 排位页

- 交接说明见 `docs/J18PRO_RACECARD_HANDOFF.md`（架构、部署、硬规则、近期功能与接 API 建议）。
- 用户用手机强制刷新线上页验收，**不要录屏、不要截图、不要上传 walkthrough 视频/图片**。
- 改完 `static/racecard_board.html` 后，必须同步到 SERVER2 `/root/j18pro/public/racecard.html`，PM2 进程名 `j18pro`，端口 `3030`。验收地址：`http://120.77.253.95:3030/racecard.html`。
- 有改 `static/racecard_help.html` 时，同步到 SERVER2 `/root/j18pro/public/help.html`。
- 只动 j18pro。不要改、重启或部署 `finance-18`、`100852`、`cabinet-quoter`。
- 产品界面用繁体（zh-HK）；和用户对话用简体中文。
- 风格延续现有 j18（钢蓝顶栏、绿/蓝场次块、浅底斑马纹），做渐进改动，不要大改视觉。
- **功能更新日志（`static/racecard_help.html` → `FEATURE_CHANGELOG`）**：
  - 只记功能修改的**终态结果**（用户最终看到的行为／文案／样式），不记中途尝试与反复改版过程。
  - 按用户要求合并／精简序号区间时，改数组并重排 `no`；**合并日志本身不算功能改动，不另开序号**。
  - 有实质功能结果时，部署顺手追加一条（序号、版本、香港时间、精简说明）。
- **右滑列宽规则（快照与日后 API 都必须遵守）**：每列宽度按当场该字段最长内容（含表头）自动量，数据到分隔线固定 2px（`COL_FIT.dataToRulePx` / `--scroll-col-gap`）。禁止再写死 sm/md/wide/xl 或按字段手填列宽。换场、排序、灌入新数据都必须走 `applyMeeting` → `renderBoard` → `fitScrollColWidths`。
