# J18 下游對 api_jjjc 合約（消費端）

> 上游：HKJC Local Pipeline / api_jjjc。  
> 本檔係 J18 消費端必須遵守嘅 join／欄位／來源對照；**禁止猜欄位名**。  
> 若同 export 衝突，以 `GET /api/export/catalog` 同各 `jjjc.*.v1` 為準。

## 鐵律

1. Join 主鍵：`race_id` + `horse_no`（禁止 `horse_name`）；馬身份用 `horse_code`／`brand_num`
2. `race_id`：`YYYYMMDD` + `ST|HV` + 兩位場次（例 `20260916HV01`）
3. `race_date`：`YYYY-MM-DD`
4. `venue_code`：只得大階 `ST` / `HV`
5. `meeting_id`：`YYYY-MM-DD_ST` 或 `YYYY-MM-DD_HV`
6. 排位 DB 可能叫 `runner_no`＝export 嘅 `horse_no`（`jjjc_export_common.horse_no_of`）
7. placeholder／`energy_is_placeholder=true`／空殼唔當真值
8. **場額**：HV `horse_no` ≤12；ST ≤14。J18 results sync 會拒寫超額馬號，並喺重同步時清同場幽靈馬（常見污染：ST Glenealy 14 匹誤寫入 HV `race_id`）
9. **顯示名**：馬／騎／練優先中文（`*_ch` 或 sectionals／racecard）；results 英文唔好覆蓋已有中文。統計近績多數用 `horse_name`，中英混用會拆散同一匹馬——身份以 `brand_num` 為準，顯示應統一中文

## 開工檢查

```bash
curl "$JJJC_API_BASE/api/export/catalog"
```

## 你要咩 → 去邊度攞（J18 sync 模組）

| 資料 | Export | Schema | J18 sync |
| --- | --- | --- | --- |
| 賽前排位 | `/api/export/racecard` | `jjjc.racecard.v1` | `jjjc_racecard_sync.py` |
| 速勢能量 | `/api/export/speedguide` | `jjjc.speedguide.v1` | `jjjc_speedguide_sync.py`（略過 `energy_is_placeholder`） |
| 賽績指引 | `/api/export/formguide` | `jjjc.formguide.v1` | `jjjc_formguide_sync.py` |
| 官方賽果 R1 | `/api/export/results` | `jjjc.results.v1` | `jjjc_results_sync.py` → `finish_order_num` |
| 分段時間 R2 | `/api/export/sectionals`（別名 `/api/sectionals`、`/api/export/sectional`） | `jjjc.sectionals.v1` | `jjjc_sectionals_sync.py` → `runner_sections`／`race_sectionals` |
| 競賽報告 R3 | `/api/export/text-reports?report_type=incident_report` | `jjjc.text_reports.v1` | `jjjc_text_reports_sync.py` |
| 沿途走勢 R4 | `/api/export/text-reports?report_type=running_comment` | 同上 | 同上（query 別名 `corunning`→payload `running_comment`） |

可選：`&raceNo=1`

## 禁止用錯

| ❌ | ✅ |
| --- | --- |
| `finish_order` | `finish_order_num`（另有 `finishing_position`） |
| payload 內 `corunning` | `running_comment` |
| `racereport` / `race_report` | `incident_report` |
| placeholder 當真評述／真速勢 | 略過／waiting |
| Sha Tin／沙田／st | `ST` / `HV` |
| HV 場寫入 #13/#14（ST 幽靈） | 拒寫＋重同步清幽靈；查 `field_warnings`／ops 場額警告 |

## 分段（R2）payload 要點

- catalog product id：`sectional`
- 賽事層：`sectional_times`、`race_cumulative_times`
- 每馬：`horse_no`（+`runner_no`）、`sections[]`（`section_index`／`position`／`sectional_time`／`margin`）、`positions[]`、`sectional_times[]`；備援 `running_position`
- `status`／`content_updated_at`；`suspicious`｜`unpublished`｜`empty` 唔當 obtained

## CLI

```bash
curl -sS "$JJJC_API_BASE/api/export/catalog" | jq '.products[] | select(.id=="sectional")'
curl -sS "$JJJC_API_BASE/api/export/sectionals?date=2026-09-16&venue=HV" | jq '.schema,.status,.race_count'
python jjjc_sectionals_sync.py --date 2026-09-16 --course HV
python jjjc_sectionals_sync.py --from-file fixtures/jjjc_sectionals_HV_20260916_R1.json
```

## 修復 HV「14 匹」幽靈（ST→HV 污染）

症狀：跑馬地場次顯示 14 名次／出現 #13（如 GOOD FORTUNE），但上游分段／排位只有 12 匹；部分馬分段時間 `None`。

```bash
# 用正確上游重寫該日 HV 賽果（拒寫 #13+#14，並刪同場唔喺 export 的馬）
python jjjc_results_sync.py --date 2026-09-09 --course HV
# 再補分段
python jjjc_sectionals_sync.py --date 2026-09-09 --course HV
```

作戰室「③ 分段時間／走位」會顯示場額異常警告；覆蓋摘要 `gaps` 含「場額幽靈」。

## 有走位但無分段秒數（ST 正常 14 匹）

沙田場額 ≤14，**14 匹本身唔係 bug**。若作戰室顯示「有走位 14／有分段時間 0」，多數係：

1. 只跑咗 RESULTS（`running_position` → 走位），**未同步 R2** `GET /api/export/sectionals`
2. 舊 UI 誤寫「空秒數屬正常」——其實上游已有 `sectional_time` 時必須拉 R2

```bash
# 只補秒數（賽果已齊時）
python jjjc_sectionals_sync.py --date 2026-09-06 --course ST
# 或作戰室 RESULTS →「同步 R2 分段（jjjc）」／「重跑賽果＋回填分段」
```

未設 `JJJC_API_BASE` 時會預設 `https://apicc.up.railway.app`。
