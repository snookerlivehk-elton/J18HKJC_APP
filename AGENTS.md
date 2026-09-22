# Agent notes

## Cursor Cloud specific instructions

### j18pro 排位页

- 用户用手机强制刷新线上页验收，**不要录屏、不要截图、不要上传 walkthrough 视频/图片**。
- 改完 `static/racecard_board.html` 后，必须同步到 SERVER2 `/root/j18pro/public/racecard.html`，PM2 进程名 `j18pro`，端口 `3030`。验收地址：`http://120.77.253.95:3030/racecard.html`。
- 只动 j18pro。不要改、重启或部署 `finance-18`、`100852`、`cabinet-quoter`。
- 产品界面用繁体（zh-HK）；和用户对话用简体中文。
- 风格延续现有 j18（钢蓝顶栏、绿/蓝场次块、浅底斑马纹），做渐进改动，不要大改视觉。
