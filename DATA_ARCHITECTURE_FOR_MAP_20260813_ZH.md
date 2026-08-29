# 全球 UAP／USO／九大行星資料架構研究：為地圖而設計

更新：2026-08-13（Asia/Taipei）  
目標：讓全球目擊報告、官方文件、照片／影片索引、自然現象控制與九大行星星曆，未來可安全接到 2D 地圖、3D 地球與統計模型；不把「報告」誤當成「真實物體位置」。

## 結論

不要把所有下載檔直接丟進地圖，也不要把地圖目前顯示的 JSON 當資料庫。

正確結構是：

```text
直接下載 URL
   │
   ├── 原始不可變快照（證據、壓縮、SHA-256）
   ├── 標準化 observation（每個來源的一筆報告）
   ├── candidate event（人工／版本化去重後的候選同事件）
   ├── controls（流星、行星、衛星、天氣、飛機等；不計入目擊分子）
   └── 只讀地圖衍生層（H3 聚合、GeoJSON／PMTiles、縮圖）
```

**觀測報告（observation）是唯一不可改寫的主表。** 地圖 pin、熱度圖、去重事件、出沒率都是從它衍生，隨時可重算。這樣新來源、來源修正、權利撤回或更換地圖框架時，不必重抓整個母庫。

## 一、從兩個專案學到什麼

| 專案 | 真正的資料架構 | 值得借用 | 不應當母庫設計 |
| --- | --- | --- | --- |
| World Monitor | TypeScript SPA → Vercel/Railway → Redis 快取／seed metadata → 多種 map layer | 明確來源 registry、資料新鮮度、layer contract、快取分層、地圖與 UI 分離 | Redis／瀏覽器 cache 是即時顯示層，不保存原始證據；RSS 地理推斷常是文章層級的粗座標 |
| Shadowbroker | FastAPI fetcher 群組 → 共用 `latest_data` 記憶體 dict → 地圖快照；少量啟動 JSON 快取 | fetcher 分域、來源開關、快取明示 stale、row delta | `latest_data` 是運行期狀態，重啟／更新可變；不具版本、來源世系或長期去重契約 |
| 我們的 UAP 庫 | 原始 gzip + JSONL + receipt 已存在 | raw 快照、SHA-256、來源／原始 URL、禁止未授權批抓 | 下一步需補 spatial schema、事件關聯與 map serving；不能只維持扁平 JSONL |

World Monitor 的架構將資料分為 UI、Edge gateway、Redis seed 與 map layer；其資料模型把單篇 `NewsItem` 與 `ClusteredEvent` 分開。這正好印證「來源報告」和「推論後事件」不可混成一表。[World Monitor architecture](https://github.com/koala73/worldmonitor/blob/main/ARCHITECTURE.md) · [World Monitor data model](https://github.com/koala73/worldmonitor/blob/main/docs/Docs_To_Review/DATA_MODEL.md)

Shadowbroker 的 fetcher store 則清楚是 `latest_data` 的 in-memory dashboard state，適合畫即時層，但不是不可變檔案庫；它的啟動快取也有過期時間。這是我們要避免用來保存歷史目擊的模式。[Shadowbroker fetcher store](https://github.com/BigBodyCobain/Shadowbroker/blob/main/backend/services/fetchers/_store.py) · [fetch orchestrator](https://github.com/BigBodyCobain/Shadowbroker/blob/main/backend/services/data_fetcher.py)

## 二、建議的四層資料架構

```text
┌──────────────────┐
│  0. source registry│  URL、授權、頻率、欄位映射、風險／隱私規則
└────────┬─────────┘
         ▼
┌──────────────────┐
│  1. evidence lake │  raw response.gz + receipt.json + SHA-256
│     永不覆寫       │  只保存明確允許下載的原件／metadata
└────────┬─────────┘
         ▼
┌──────────────────┐
│  2. observation   │  標準化、但仍保留每個來源的一筆報告
│     lake/warehouse │  GeoParquet + 本機 DuckDB；可重建
└────────┬─────────┘
         ▼
┌──────────────────┐
│  3. curated graph │  去重關聯、事件候選、媒體 manifest、控制資料關聯
│     （可版本化）    │  初期 DuckDB；多人／即時查詢才進 PostGIS
└────────┬─────────┘
         ▼
┌──────────────────┐
│  4. map products  │  H3 heatmap、GeoJSON viewport、PMTiles、縮圖
│     可全部重建      │  絕不當原始資料唯一副本
└──────────────────┘
```

### Layer 0：來源台帳

每個來源一個 `source_id`，至少記錄：

```text
source_id, owner, portal_url, direct_download_url, parent_index_url,
parent_collection_id, archival_scope, access_class, license_or_terms,
privacy_risk, update_cadence, expected_format, normalizer_version,
geographic_coverage, upstream_sources, media_download_allowed, last_checked_at
```

`parent_index_url`、`parent_collection_id` 與 `archival_scope` 專門處理 NARA、CIA、FBI 這類「上層入口連到多個檔案系列」的情況；parent index 不是 child document，不能因一條 collection URL 就產生大量事件列。NSA 類的 negative-record page 則只記 policy／檢索範圍，不能轉成任何事件或 absence inference。

`access_class` 延用現在的 `OPEN_BATCH / OPEN_BATCH_REVIEW / METADATA_BATCH_REVIEW / OPEN_QUERY / ARCHIVE_REQUEST / INDEX_ONLY / LICENSE_REQUEST`。這使「已知道網址」和「有權批次下載」永遠是兩件不同的事。

### Layer 1：evidence lake（原始證據）

每一次成功下載保存原始 bytes，gzip 壓縮、不可覆寫，並伴隨收據：

```text
snapshot_id, source_id, collected_at, request_url, http metadata,
raw_sha256, raw_bytes, compressed_sha256, parser_version, license_at_fetch
```

這層的目的不是讓地圖直接讀，而是讓任何標準化／去重結果可回到原檔驗證。已做的 raw + receipt 模式正確，繼續保留。

### Layer 2：observation lake（可分析、可重建）

將每個來源 report 標準化為一筆 **observation**；不可因為同案出現在三個站就刪掉其中兩筆。初期寫 JSONL gzip 方便除錯；穩定後以 GeoParquet 作為分析主格式。

GeoParquet 是將 geometry 與其 metadata 放入開放 Parquet 的規格，適合欄位裁切、按時間／來源掃描與跨工具讀取；它要求幾何欄在 schema 根層，並推薦以 longitude, latitude 的 WGS84／CRS84 互通。[GeoParquet 1.1 specification](https://geoparquet.org/releases/v1.1.0/)

建議 parquet partition：

```text
lake/observations/
  schema=v1/
    source_id=uapdrop/
      observed_year=1997/
        observed_month=07/part-000.parquet
    source_id=nuforc/
      observed_year=2026/observed_month=08/part-000.parquet
```

沒有可靠時間的資料進 `observed_year=unknown`，而不是假裝日期精準。

### Layer 3：curated graph（可修正的推論層）

這層分三張概念表：

| 表 | 一列代表什麼 | 可否改寫 |
| --- | --- | --- |
| `observations` | 某來源的一筆原始報告／文件索引 | 否；只可新增訂正版本 |
| `candidate_events` | 多個 observation 推斷為同一事件的候選群 | 可；必須有 `dedup_version` |
| `event_links` | observation ↔ candidate event 的關聯、信心與理由 | 可；保留歷史版本 |

這是最重要的反重複規則：地圖可選「報告數」或「去重後候選事件數」，但兩者不能混算。

### Layer 4：map products（可丟掉、可重建）

地圖不直接讀 raw 或整個 parquet：

- 全球縮放：讀按日／月、來源、環境分組的 H3 heatmap。
- 中尺度縮放：讀 cluster／bbox 下的精簡 point feature。
- 高倍率縮放：讀通過權利與隱私規則的 observation pin；文字／媒體再按需取。
- 歷史底圖或離線包：將固定版本輸出成 PMTiles；它是單檔 tile archive，方便地圖端透過 range request 讀取，但不是資料庫。[PMTiles v3 specification](https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md)

### 國家覆蓋圖不是邊界檔的副產品

國家覆蓋色階的主體是本專案的 versioned `country_coverage` join table，不是從 polygon 名稱臨時推論。顯示幾何可在未來採用 [Natural Earth 50m Admin 0 Countries](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/)；其目前頁面列 258 個顯示單位、version 5.1.1、約 781.78 KB，並說明預設畫 de facto boundaries。它雖為 public-domain vector（見 [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/)），仍只是一個可替換的 renderer asset。

統計主鍵採 [UNSD M49](https://unstats.un.org/unsd/methodology/m49/overview/) 的數字碼／ISO 對照，另用此專案的版本化 193 會員國 roster 加上明示補充地區；不能把 Natural Earth 的 258「countries」、M49 的 country/area 範圍或地圖上看似獨立的島嶼直接等同於 coverage 分母。最小 row 如下：

```text
country_coverage_id, ledger_version, m49_code, iso_alpha2,
membership_scope, coverage_status, status_reason_code,
source_ledger_refs_json, source_scope_as_of_utc,
boundary_dataset, boundary_dataset_version, boundary_feature_id,
boundary_view, geometry_sha256, generated_at_utc
```

`coverage_status` 只可來自國家帳本的 A/B/C/D 與可追溯理由；`source_ledger_refs_json` 只放資料來源台帳的 stable reference，不塞原始案例或文件內容；`boundary_view` 要明示如 `ne_de_facto`，而不是暗示法律邊界。台灣、巴勒斯坦、梵蒂岡、科索沃、海域與南極等補充項必須以 `membership_scope` 分開，絕不靠 polygon 名稱偷偷併入或刪除。這一層只有靜態低量 geometry／code reference，沒有 report、目擊率或「外星人機率」。

### 來源覆蓋、已接入資料與 `P_report` 是三個不同狀態

`country_coverage.coverage_status` 只能回答「有沒有可追溯的來源入口」，不可拿來生成數字或當成 report count。地圖要另外持有當期資料可得性與估計資格：

```text
country_data_availability_id, ledger_version, iso_alpha2, time_bucket,
local_source_admission_state, admitted_report_scope,
source_bias_status, p_report_estimation_status,
source_refs_json, policy_version, assessed_at_utc
```

其中 `local_source_admission_state` 只能是 `none_confirmed`、`lead_not_admitted`、`metadata_admitted` 或 `report_data_admitted`；`admitted_report_scope` 只能是 `none`、`withheld`、`partial` 或 `bounded`。`p_report_estimation_status` 只能是 `not_estimated`、`source_insufficient`、`source_limited`、`model_review_required` 或 `published_with_caveat`，且絕不能由 A/B/C/D 自動推導。

渲染契約如下：

| 國家來源狀態 | 國家覆蓋圖允許顯示 | report heatmap／`P_report` 禁止做的事 |
| --- | --- | --- |
| A | 「已驗來源入口」的 categorical badge 與可追溯台帳連結 | 不得因入口存在就顯示事件量、採集量或概率 |
| B | 「館藏／申請／實驗線索」badge 與下一道權利門 | 不得將館藏存在、書目或申請路徑轉成事件或率 |
| C | 「僅跨境／全球基線」badge；必須顯示無本地一手母庫 | 不得用外國文件、全球平台國別標籤或單案填補本地 coverage；預設 `source_insufficient` |
| D | 「未驗本地入口」badge／斜線或空白原因 | 不得把未找到資料渲染成零回報、低出沒或低 `P_report`；預設 `not_estimated` |

國家來源圖與 report heatmap 必須分圖層、分圖例。report heatmap 只可讀已通過權利／隱私／去重審核的 `report` aggregate；`P_report` 只有在資料範圍、時間窗、分母 proxy、來源偏差和 `p_report_estimation_status` 一併顯示後才可發表。任何 C/D 國家的模型值若未顯示 `source_limited`／`source_insufficient` 狀態即屬無效輸出。

### 新聞發現層也不能變成事件層

GDELT／RSS／新聞搜尋只可回答「哪裡、何時、哪些媒體正在報導或連結某個主題」。它們的列通常是**新聞文件**，不是目擊報告；文內地名或自動抽取的 GKG geo-tag 也可能是被提及的地方，而非事情發生地。因此另用 `news_discovery_context` 表，與 `observation`、`candidate_event`、`country_coverage` 和所有 control 表分離：

```text
news_discovery_context_id, provider, query_profile_id, query_hash,
provider_batch_id_or_record_ref, published_at_utc, publisher_domain,
article_url_sha256, source_language, mentioned_country_codes_json,
location_extraction_status, discovery_reason, source_bias_note,
query_receipt_sha256, access_class, collected_at_utc
```

這張表不保存文章全文、原 URL、圖片、影片、文章地點 geometry 或原始 GKG 列。它只能幫人工發現真正的資料持有人，或在方法審核後量測「報導注意力」；絕不寫入 `report` 分子、事件 pin、國別 A/B/C/D、`P_report` 分母或分子。任何使用它的圖層都必須標示「新聞發現／報導量，不是目擊量或發生位置」。

## 三、最小穩定事件 schema

以下是下載器應該產出的 stable schema；所有欄位可為 null，但未知與推論不得混淆。

```text
observation_id              # source_id + source_record_id + source version
source_id
source_record_id
snapshot_id
record_role                 # sighting / official_document / astronomy_control / other_control

observed_at_start_utc
observed_at_end_utc
source_time_text            # 原字串，保留時區／模糊日期
time_precision              # second/minute/hour/day/month/year/unknown

geom_original_wgs84         # Point / Polygon / null，longitude,latitude
geom_display_wgs84          # 已依隱私規則做格網化後的幾何
coordinate_precision_m      # 來源明示或估計；不可缺省為「精準」
location_method             # source_gps / named_place / geocoded / coarse_region / withheld
h3_r4, h3_r6, h3_r8         # 派生欄位，不是原始事實
country_code, admin1_code, venue  # air / land / water / submerged / orbit / unknown

title, summary_redacted
status, explanation
original_source_url
source_document_url

media_manifest_id           # 不把影像 blob 塞進事件列
rights_status               # permitted_download / metadata_only / unknown / restricted
privacy_tier                # public_exact / public_coarse / restricted
raw_sha256
normalizer_version
ingested_at_utc
```

`geom_original_wgs84` 和 `geom_display_wgs84` 必須分開。原稿有精確住址、私人目擊地或敏感設施時，地圖只能用顯示幾何；原始幾何只在權利與存取權限允許下保留。

H3 適合做全球格網聚合與不同資料密度的比較，但它是派生索引，不是精確的原始位置。H3 是多精度、階層式全球六角格網，且官方也說跨層 parent/child 的幾何包含是近似關係；因此最後的點／polygon 查詢仍以原 geometry 為準。[H3 overview](https://h3geo.org/docs/3.x/core-library/overview/) · [H3 indexing caveat](https://h3geo.org/docs/highlights/indexing/)

## 四、九大行星和控制資料不能塞進「目擊事件」

「歷史九大」集合（八大行星 + 冥王星；冥王星在 IAU 分類中是矮行星）要用獨立的 ephemeris product：

```text
schema_version, body_id, body_name, epoch_utc, epoch_time_scale,
observer_center, observer_mode, coordinate_frame,
ra_icrf_deg, dec_icrf_deg, apparent_coordinate_frame,
apparent_ra_deg, apparent_dec_deg, range_au, range_rate_km_s,
altitude_deg, azimuth_deg, azimuth_altitude_status,
api_signature_source, api_signature_version,
source_id, snapshot_id, source_record_id, raw_sha256
```

它的座標是天球／觀測者座標，不是地表事件的 `lat/lon`。在未來 UI 中：

- 地球地圖：用來做特定目擊當時的天文排除／對照，不畫成地表 pin。
- 星空／天空視圖：依觀測者位置與 epoch 畫軌跡。
- 模型：當控制變數，絕不能與 UAP report 加總成熱度。

目前可重現的初始快照採 `observer_center=500@10`（Sun bodycentric），
`observer_mode=heliocentric_bodycentric_reference`。這個設定保留地球在歷史九體集合中，
但不是地表觀測者座標：`altitude_deg`／`azimuth_deg` 必為 `null`，
`azimuth_altitude_status=not_applicable_non_topocentric`。它只能作軌道／參考控制，**不能**拿來判定任一目擊是否為行星。

日後若要針對單一、已獲權利允許的目擊做天空比對，須另建
`topocentric_case_control`：只取該事件時間與經隱私格網化的觀測者位置，保留 query receipt、時間／位置精度和可撤銷權利狀態；地球目標則明示 `not_applicable`，不能捏造一個地球天空角度。此類 case-level product 不可由目前的日級 heliocentric snapshot 自動推得。

同理，火球、衛星、航班、AIS、極光和天氣是 `record_role=*_control` 或獨立 time-series 表，不進「目擊數」分子。

對航班與船舶這類 exposure control，地圖層預設只保存可審核的格網聚合，而不是可回溯的個體軌跡：

```text
control_id, provider, provider_dataset_version, interval_start_utc, interval_end_utc,
h3_cell, h3_resolution, aircraft_count_or_presence_hours,
vessel_count_or_presence_hours, coverage_fraction, query_receipt_sha256,
access_class, attribution_required, collected_at_utc
```

`callsign`、`icao24`、`MMSI`、船名、owner、原始 ADS-B／AIS points 都不進地圖事件表。這同時避免把控制資料誤當目擊，也避免未經許可保留個體移動資料。OpenSky 與 Global Fishing Watch 都要先通過帳號／授權與用途審核，才可能寫入這張 control 表；在此之前只保留來源 URL 與資料契約。

`P_report` 的「分母」也必須與事件分子分表，至少拆成空間人口估計與國別連網 proxy：

```text
population_exposure_control_id, provider, provider_release, reference_year,
source_grid_key, source_resolution, display_h3_cell, display_h3_resolution,
population_estimate, model_vintage, input_census_vintage,
query_geometry_sha256, query_receipt_sha256, access_class, collected_at_utc

country_connectivity_control_id, provider, indicator_code, iso3, reference_year,
value_pct, source_revision, source_definition, missingness_status,
query_receipt_sha256, collected_at_utc
```

WorldPop 類資料是建模後的人口估計，非實際在場觀測者；必須保留 release、來源解析度與模型／普查年代。它只可對已選定的國別或粗 H3 display cell 做 bounded polygon summary，不能為地圖方便而掃描每個 100m cell 或鏡像所有年份 raster。World Bank WDI 的 `IT.NET.USER.ZS` 則是「過去三個月使用網際網路」的**國別年別**比例；它不是網路覆蓋、手機訊號、夜空可見性、回報意願或可回推到單一個人的機率。因此不得將它向 H3 假插值，也不得拿人口或網路 proxy 製造 UAP event pin。兩類控制都只可作曝光偏差的候選特徵，並必須顯示缺值、版本與方法限制。

海洋被動聲學另以 `deployment_id + coarse_h3 + time window` 管理：可保留儀器型別、取樣率、頻帶／噪音等**衍生指標**與權利 metadata；不把原始音檔、可識別船訊、敏感站點精確座標或聲學觸發直接畫成 UAP pin。它是 `ocean_acoustic_control`，不是 report。

海底地形是另一個獨立資料角色：`bathymetry_context` 只描述「地圖上這一海域的來源地形背景與資料品質」，不描述任何現象、感測器或觀測者。GEBCO 類全球 grid 必須保留 release、vertical datum、原生解析度與 TID（資料來源型別）；不能因渲染方便就把內插海深變成精確實測，更不能由深度推導 USO／UAP 機率：

```text
bathymetry_context_id, provider, grid_release, vertical_datum,
source_grid_resolution, display_grid_key, display_grid_resolution,
depth_summary_m, tid_summary, area_geometry_sha256,
query_receipt_sha256, access_class, collected_at_utc
```

地圖層最多顯示來源原生或更粗格網的等深／色階背景，且必須標示 release 與「模型／編製地形」身分；它不和 `report`、`ocean_acoustic_control`、`maritime_control` 或 `P_report` 分子／分母相加。完整全球 grid、tile、WMS 影像快取都要另有明確需求與容量預算，預設不進 evidence lake。

Argo 與 Copernicus Marine 也必須與目擊分表。Argo 的浮標 metadata／trajectory 只能被約化成「某一粗格、某一時窗是否有合格公開觀測平台」；不可保留或顯示 float ID 的逐點移動軌跡。Copernicus 產品則必須標明是 analysis、forecast 或 reanalysis，以及其來源格網和資料延遲；它提供海況 context，不是現場量測或事件解釋。最小契約如下：

```text
ocean_platform_coverage_control_id, provider, provider_dataset_version,
network, interval_start_utc, interval_end_utc, display_h3_cell,
display_h3_resolution, platform_presence_hours, variable_summary,
qc_status_summary, coverage_bias_note, query_receipt_sha256,
access_class, collected_at_utc

ocean_state_control_id, provider, product_id, product_version,
state_kind, valid_time_utc, production_time_utc, source_grid_key,
source_resolution, display_grid_key, display_grid_resolution,
value_summary, uncertainty_summary, analysis_status,
query_receipt_sha256, access_class, collected_at_utc
```

前者不寫入 float ID／軌跡，後者不把模型格網下推成精確 point。兩者都只可作 `P_report` 的資料可得性／誤認與解釋限制註記，不能進 report 分子、不能當水下事件數，亦不能替任何國家補 UAP 母庫覆蓋。

固定／纜線／繫泊海洋觀測網（OOI、ONC、EMSO、MBARI 等）是第三種東西：它們只說明某一粗海域、某一時間窗可能有何種科學觀測能力，和 Argo 的移動浮標、Copernicus 的海況產品分表。即使上游公開 data explorer，也不可把平台的即時資料流、聲學觸發、影像、影片、載具位置或某個 station 的存在畫成 USO／UAP evidence。最小可公開契約如下：

```text
ocean_observatory_coverage_control_id, provider, source_product_or_network,
metadata_release_or_version, interval_start_utc, interval_end_utc,
display_h3_cell, display_h3_resolution, observatory_class,
sensor_family_summary, availability_status, coverage_bias_note,
query_receipt_sha256, access_class, collected_at_utc
```

此表沒有 station ID、精確經緯度、連續數值、hydrophone／spectrogram、影像／影片、載具軌跡或原始檔 URI；地圖只可顯示來源原生或更粗的 H3／時間 aggregate。availability 僅表示 metadata 層的觀測可得性，不能當成有人看見、儀器偵測或「未看見」的證據，更不能進 `report`、`P_report` 分子／分母、USO 計數或任何國別 A/B/C/D 覆蓋。

火點也使用 `fire_control`：只保存 `date_utc + h3_cell + detection_count + product_version + quality_summary`，作為偏遠森林／山區的自然或人為光源背景。衛星火點、煙柱或熱異常不是 UAP report，也不帶動任何「熱點」結論。

已命名隕石資料則獨立為 `meteorite_catalog_control`。例如 Meteoritical Bulletin Database 的合法、最小單案尋址只可保留 canonical name、classification、country／year、`fall_or_find`、資料庫版本與 receipt；不取 KML、精確尋獲點、地圖、標本持有人、樣本、照片或敘述。它只幫助辨識「已知自然落物」的控制情境，不能把目錄列當目擊、UAP、USO、地表 pin 或出沒率證據。

地磁／太空天氣使用沒有地表 geometry 的 `space_weather_control`。例如 Kp 是全球性、三小時級的地磁擾動指數；可協助標記磁暴／極光背景期，卻不能直接表示某一地點看得到極光，更不能解釋、證實或否定任何單筆目擊：

```text
space_weather_control_id, provider, interval_start_utc, interval_end_utc,
index_name, index_value, index_status, source_dataset_version,
citation_or_doi, query_receipt_sha256, collected_at_utc
```

因此 Kp／ap 只以 UTC window join 到 report 或固定相機站的模型特徵，絕不畫成地圖 pin、絕不與目擊數加總。對歷史分析優先保留 `definitive` 值與其 DOI／版本；nowcast 另存 status，不能在日後被靜默覆寫。

全球模型／衛星氣象使用 `weather_control`，也不是「目擊當地的真實實測」。其 geometry 必須保留供應者原生格網或更粗的 display cell，不能把低於來源解析度的 H3 pin 假裝成精確雲層：

```text
weather_control_id, provider, interval_start_utc, interval_end_utc,
source_grid_key, source_resolution, display_h3_cell, display_h3_resolution,
cloud_proxy, precipitation, wind_speed, temperature, radiation_proxy,
time_standard, latency_class, source_dataset_version,
query_receipt_sha256, collected_at_utc
```

例如 NASA POWER 的 hour/point API 僅在已有 report 的粗化 display cell 或明確研究格網中按有限時間窗查詢；其 meteorology 原生約 0.5°×0.625°、solar 約 1°，不可用大量更細 H3 點做同一格的重複請求。`weather_control` 只作模型 feature／可見性偏差註記；沒有地面站比對時，`latency_class` 必須標明它是近即時或事後改善版本，不能悄悄以新版覆寫原先判讀。

WMO OSCAR/Surface 與 NOAA ISD 的角色是 `station_coverage_control`。前者描述登錄站／平台的能力與狀態，後者才是長期站點觀測；兩者都不能代表「有人看見」或「現場天氣真值」。儲存與顯示時要分開 station identity、來源精確位置、粗化展示格與有限時間窗，避免用大量站點點位形成偽精確的人類／感測器熱度：

```text
station_coverage_control_id, provider, provider_dataset_version,
provider_station_id, station_type, operational_status,
interval_start_utc, interval_end_utc, variables_available,
source_location_wgs84, display_h3_cell, display_h3_resolution,
availability_summary, quality_flag_summary, coverage_bias_note,
query_receipt_sha256, access_class, collected_at_utc
```

`provider_station_id` 與 `source_location_wgs84` 只可留在權利與敏感站規則允許的受控層；對外地圖只顯示 coarse H3／國別 aggregate 或「有無可用對照」。ISD 的全球 archive 約數百 GB，不得因為它公開就整庫搬入；只允許對已選定 report／研究格做最小 station-time query，並保存來源品質旗標、coverage bias 與 receipt。

衛星、火箭體、碎片與再入的正確角色是**單一報告的可解釋性對照**，而不是另一張全球事件圖。對有可信時間窗與概略觀測位置的 report，才建立一筆 `satellite_prediction_control`：

```text
satellite_match_id, observation_id, prediction_window_start_utc,
prediction_window_end_utc, observer_h3, ephemeris_source,
ephemeris_snapshot_id, element_epoch_utc, prediction_method,
candidate_count, nearest_angular_separation_deg, altitude_deg,
azimuth_deg, illumination_assumption, match_status, model_version,
query_receipt_sha256, generated_at_utc
```

`match_status` 只可為例如 `known_orbital_object_possible`、`no_candidate_in_checked_scope`、`insufficient_time_or_location`、`historical_elements_unavailable`；它不是「已證明」或「不明物體」的判決。CelesTrak current GP 僅適用當下／近期的最小查詢，並以站方 2 小時更新與任何非 200 即停為硬閘；它不能回推長年前的目擊。歷史比對只有在 Space-Track 帳號／條款及逐案預算通過後，才可以向 GP_HISTORY 查必要時間窗。

任何 raw orbit elements、catalog/object reference、傳播中間點和衛星軌跡都放在受控 receipt／工作區，不進 `observation`、H3 分子或公開地圖。地圖可在單案審計面板顯示資料來源、方法版本、時間差與「可匹配／未命中／資料不足」，但不得把完整軌道線、衛星密度或預測線偽裝成 UAP 熱點。採集／分析端應使用可容納六位以上 catalog ID 的 OMM／CSV／JSON；不可依賴 legacy TLE 的固定寬度欄位。

## 五、媒體與文件的正確位置

```text
media_manifest_id, observation_id, original_url, media_type,
license, download_permitted, content_sha256, bytes,
local_object_path, thumbnail_path, redaction_status
```

- 授權不明：只存 URL、描述、權利狀態、可選的公開縮圖連結；不下載。
- 明確允許：物件以 SHA-256 content-addressed path 保存，附件不重複。
- 官方 PDF／圖片：保存原件與 hash，但不在地圖 API 直接送大檔；只送縮圖／metadata。
- 文件 metadata 與 actual observation 分開：一份官方檔可能涵蓋多事件，一個事件也可能有多份文件。

## 六、初期技術選型：不要太早上複雜伺服器

| 階段 | 建議主體 | 為什麼 |
| --- | --- | --- |
| 現在（首批數萬列） | gzip raw + JSONL + DuckDB + GeoParquet export | 可離線、可查核、零常駐服務、容量很小 |
| 開始大量歷史回填／多人查圖 | PostgreSQL + PostGIS 作 serving DB；raw lake 照留 | bbox／半徑／時間窗查詢與權限過濾更可靠 |
| 大量固定歷史地圖／離線使用 | 從固定資料版本產生 PMTiles | CDN／靜態檔效率好，不把原庫複製到前端 |

PostGIS 的 geometry/geography 與 GiST 空間索引適合多維空間查詢；官方文件也指出資料超過數千列就需要 spatial index。對非常大的、低更新歷史分區，可以再評估 BRIN；它較小但需要資料有空間排序且查詢較慢。[PostGIS spatial indexes](https://postgis.net/docs/postgis-en.html)

**現在不需要 Docker、Redis、全套 World Monitor，也不需要先部署 PostGIS。** 首批 29,322 筆用 DuckDB／GeoParquet 足夠。等 UAP 地圖真的要讓多人互動、做 bbox + timeline + 權限查詢，再把 curated 層載入 PostGIS。

## 七、建議的目錄結構

```text
uap_lab/
  registry/
    sources.json                  # 來源、權利與正規化規則
    schema/observation-v1.json
  lake/
    raw/<source_id>/<snapshot_id>/*.gz
    receipts/<source_id>/<snapshot_id>.json
    observations/schema=v1/source_id=.../observed_year=.../*.parquet
    controls/<control_kind>/.../*.parquet
    media/sha256/ab/<full_sha256>  # 僅允許下載的原件
    media_manifests/*.jsonl.gz
  warehouse/
    uap.duckdb                     # 可重建的本機索引／views
  derived/
    candidate_events/dedup_v1/*.parquet
    h3/resolution=4/date=.../*.parquet
    h3/resolution=6/date=.../*.parquet
    map_features/release=.../*.geojson.gz
    tiles/release=.../*.pmtiles
  reports/
    source_coverage/...
```

`lake/raw` 和 `lake/receipts` 是不可變；`warehouse` 與 `derived` 可全刪重建。這個界線會讓硬碟管理、備份和資料稽核都很清楚。

## 八、實作順序

1. 保持既有 raw gzip／receipt；把 current JSONL 改名定位為暫存 canonical export，不當唯一主檔。
2. 新增 `observation-v1` schema，補 `time_precision`、`coordinate_precision_m`、`rights_status`、`geom_display`、`record_role`。
3. 建一個 compaction 指令：JSONL → GeoParquet + DuckDB catalog；不重新下載。
4. 建 H3 r4/r6/r8 aggregate；先只輸出數量、來源數、可解釋／未解釋狀態，不能直接輸出「外星機率」。
5. 產生第一個 read-only map release（GeoJSON 小樣本）；確認隱私與來源連結後，才做 PMTiles／PostGIS API。
6. 來源接入依同一 schema 做，不允許來源自行決定 map 欄位或覆蓋 `original_source_url`。

## 九、採納／不採納結論

採納 World Monitor 的：來源 registry、freshness / health metadata、明確 layer contract、視窗／縮放才載入的地圖設計。

採納 Shadowbroker 的：按領域拆 fetcher、來源 opt-in、將 stale 標示成資料欄位而不是偷偷覆蓋、快取與正式資料分開。

不採納兩者的：將 live dashboard memory/cache 當永久歷史庫、把標題推論的粗略位置假裝成 GPS、未經權利確認地鏡像照片／影片、把控制資料與目擊報告混成同一熱度。

這套結構能讓「全球來源」持續擴張，同時保住未來接 2D／3D 地圖、H3 機率圖、事件時間軸與資料審計的路。
