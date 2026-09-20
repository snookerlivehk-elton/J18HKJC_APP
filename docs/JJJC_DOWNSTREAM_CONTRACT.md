# J18 下游對 api_jjjc 合約（消費端）

> 上游：HKJC Local Pipeline / api_jjjc。  
> 本檔係 J18 消費端必須遵守嘅 join／欄位／來源對照；**禁止猜欄位名**。  
> 若同 export 衝突，以 `GET /api/export/catalog` 同各 `jjjc.*.v1` 為準。

## 鐵律

1. Join 主鍵：`race_id` + `horse_no`（禁止 `horse_name`）
2. `race_id`：`YYYYMMDD` + `ST|HV` + 兩位場次（例 `20260916HV01`）
3. `race_date`：`YYYY-MM-DD`
4. `venue_code`：只得大階 `ST` / `HV`
5. `meeting_id`：`YYYY-MM-DD_ST` 或 `YYYY-MM-DD_HV`
6. 排位 DB 可能叫 `runner_no`＝export 嘅 `horse_no`（`jjjc_export_common.horse_no_of`）
7. placeholder／`energy_is_placeholder=true`／空殼唔當真值

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
