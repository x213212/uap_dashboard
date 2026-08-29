# 九體星曆控制層契約（2026-08-13）

目的：把「八大行星 + 冥王星」做成可重現的天文參考層，供未來天空視圖與誤認控制使用；它不是 UFO／UAP 事件資料，也不能產生「外星人出沒機率」。冥王星在現行 IAU 分類是矮行星，此處保留它只是為了滿足歷史九大集合。

## 已完成的本地成果

- 上游：NASA/JPL Horizons API；回應需帶 `signature.source=NASA/JPL Horizons API` 與版本字串。
- 現有原始快照：UTC `2026-08-13` 有兩個 immutable receipt；本地 audit 驗證雜湊都正確，但標示為同日重複快照，不重複計數。
- 已選最新且已驗證的 snapshot `20260813T010454984327Z` 轉成 9 列獨立星曆表：
  [ephemeris.jsonl.gz](data/derived/ephemeris/nasa_horizons_9_bodies/20260813T010454984327Z/ephemeris.jsonl.gz)（1,694 bytes gzip）與 [manifest.json](data/derived/ephemeris/nasa_horizons_9_bodies/20260813T010454984327Z/manifest.json)。
- 此次轉換完全離線：先驗 receipt／raw gzip SHA-256，再讀原始回應；沒有向 JPL 或其他網站發出請求。

## 為什麼不是地球地圖 pin

目前的 Horizons 請求固定為：

```text
EPHEM_TYPE=OBSERVER
CENTER=500@10             # Sun bodycentric
START_TIME=<UTC day>
STEP_SIZE=1 d
```

這讓地球也能作為九體中的一列；因此產物的精確模式是：

```text
observer_mode = heliocentric_bodycentric_reference
observer_center = 500@10
coordinate_frame = ICRF
altitude_deg = null
azimuth_deg = null
azimuth_altitude_status = not_applicable_non_topocentric
```

也就是說，RA／Dec 和距離是相對於太陽中心的參考數值，不是台灣、海上或任何目擊者看到的天空方向。前端只能把它放在「天文參考／天空」圖層；地球地圖絕不畫 pin，統計模型也絕不把它加進目擊數。

## 每列欄位

```text
schema_version = uap.ephemeris.v1
body_id, body_name
epoch_utc, epoch_time_scale
observer_center, observer_mode
coordinate_frame, ra_icrf_deg, dec_icrf_deg
apparent_coordinate_frame, apparent_ra_deg, apparent_dec_deg
range_au, range_rate_km_s
altitude_deg, azimuth_deg, azimuth_altitude_status
api_signature_source, api_signature_version
source_id, source_portal_url, snapshot_id, source_record_id
original_source_url, raw_sha256
```

解析器會 fail closed：JPL signature、目標 body ID、`Sun (10)`／`BODYCENTRIC` header、`$$SOE`／`$$EOE` table sentinel、UTC 日期、RA/Dec 格式、距離欄位任一不符就拒絕產物，不會猜測或以零填補。

## 地圖接法

```text
raw JPL JSON.gz + receipt
        │（離線 hash audit）
        ▼
ephemeris.jsonl.gz（九列、無地表 geometry）
        ├── 星空／天空視圖：ICRF 參考軌跡
        └── 個案控制層：另行授權的 topocentric query，不能自動套用
```

若某個已取得權利、具足夠時間精度的目擊要做「可能是行星嗎」的比對，必須另開 `topocentric_case_control`：輸入只能是該事件的經隱私格網化觀測位置、精確度與時間窗；保存 request receipt；結果要有角距、可見高度、地平線／日照假設與 `not_applicable` 狀態。地球對地球觀測者不是天空目標，必須標明不適用，不能偽造角度。這一層尚未開啟，也不會從全球目擊資料自動抓取精確地點。

## 容量與操作

- 每日星曆快照：9 個小型 API response；registry 預估 100,000 bytes，單源硬上限 9 MiB，整個 collector 的總硬上限 64 MiB。
- 已轉出的 9 列只占 11,299 bytes 未壓縮／1,694 bytes gzip；所以來源 URL 很多不代表這個天文控制層會很大。
- 先看不下載：

```bash
python3 uap_lab/collect.py collect --source nasa_horizons_9_bodies --date 2026-08-13 --dry-run
python3 uap_lab/audit_data.py audit
python3 uap_lab/ephemeris_export.py --snapshot-id 20260813T010454984327Z --dry-run
```

官方格式與 API contract 以 [JPL Horizons API documentation](https://ssd-api.jpl.nasa.gov/doc/horizons.html) 和 [Horizons user manual](https://ssd.jpl.nasa.gov/horizons/manual.html) 為準；任何 API 欄位／版本變更都應先做受限 schema probe，再更新 parser，不應直接批次重抓。
