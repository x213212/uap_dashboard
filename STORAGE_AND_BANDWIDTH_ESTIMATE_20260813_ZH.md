# 全球 UAP／USO／天文控制資料：硬碟與流量估算

更新：2026-08-13（Asia/Taipei）  
範圍：只計算可直接下載的端點；**不以爬蟲抓網頁、不下載未授權的媒體**。

## 結論先講

- 現在工作區可用空間約 **431.8 GiB**（463.59 GB；2026-08-13 即時查核，此數字會隨工作區其他工作變動）。足夠先跑「全球事件表＋天文排除控制」；不夠存完整的國家檔案影像／PDF 母庫。
- 已做的第一個有效「目前資料」基線是 **29,322 筆、原始下載 11.936 MB、壓縮保存 5.289 MB**。這是實測值，不是推估；另有一份同日九大行星 immutable snapshot，因此歷史 row version 為 29,331、目前去重後仍為 29,322（見 `DATA_INTEGRITY_AUDIT_20260813_ZH.md`）。
- 若每天重新抓整包、而每次內容都變動，該首批來源一年最多約 **4.357 GB 網路流量**、**1.930 GB 壓縮硬碟**。實際可藉內容雜湊去重與降低更新頻率而小得多。
- 美國 NARA 的 Project Blue Book 單一系列，影像版合計 **379.31 GB**、PDF 版合計 **391.59 GB**；兩種版本都留是 **770.90 GB**。2026-08-13 對 NARA 官方頁列出的所有 **120 個**可下載 UAP ZIP 去重加總為 **1.077 TB**（0.980 TiB）。目前這顆碟不能做全媒體母庫。

## 下載器預覽（不連網）

目前下載器在真正接觸來源前，會先以 `--dry-run` 輸出固定預算表。它不做 HEAD／GET，故不會產生任何來源流量。

| 項目 | 預覽值 |
| --- | ---: |
| 可自動來源 | 4 個（僅 `OPEN_BATCH`） |
| 請求數 | 12（九大行星資料拆為 9 個） |
| 首輪預估下載 | **12,231,072 B**（約 12.23 MB） |
| 各來源硬上限合計 | **51,380,224 B**（約 51.38 MB） |
| 整次預設總量硬閘 | **67,108,864 B**（64 MiB） |

這是下載器的**上限預算**，不是保證會下載的量；若來源內容宣告或串流超過來源上限／整次預算，下載器會 fail-closed 中止。預覽指令：

```bash
python3 uap_lab/collect.py collect --all-open --dry-run
```

只有使用者明確執行未帶 `--dry-run` 的 `collect` 指令才會有網路請求。NARA、NUFORC、國家檔案與其他 `OPEN_QUERY`／`ARCHIVE_REQUEST` 來源仍不會被這個程式批次抓取。

## 一、已實測的首批下載

只採集明確公開的 CSV／API，原始回應與標準化 JSONL 都以 gzip 保存，並保留 SHA-256 收據。九大行星是「八行星加冥王星」的日心星曆控制組；它不是目擊證據。

| 來源 | 記錄數 | 當次原始下載 | raw gzip | canonical JSONL gzip |
| --- | ---: | ---: | ---: | ---: |
| UAPDrop sightings CSV | 28,314 | 11,733,269 B | 2,324,482 B | 2,814,045 B |
| UAP Observatory incidents CSV | 118 | 53,460 B | 16,458 B | 18,544 B |
| NASA/JPL CNEOS fireballs | 881 | 63,389 B | 17,563 B | 41,434 B |
| NASA/JPL Horizons 九大行星 | 9 | 85,997 B | 34,483 B | 9,660 B |
| **合計** | **29,322** | **11,936,115 B** | **2,392,986 B** | **2,883,683 B** |

加上四份收據（12,217 B），此有效基線的實際留存量是 **5,288,886 B = 5.289 MB = 5.044 MiB**。這不把同日 Horizons 重複快照與 API 錯誤隔離檔算進去；它們保留做驗證證據，不能算進有效事件資料。

壓縮效果的主要來源 UAPDrop：

- 原始 CSV：11.733 MB → 2.324 MB，減少 **80.19%**（約 **5.05×**）。
- 統一 JSONL：27.711 MB → 2.814 MB，減少 **89.85%**（約 **9.85×**）。

收據可在 `data/receipts/` 查核；實際檔案路徑與下載指令見 [README](README.md)。

## 二、首批來源的年度流量／硬碟情境

這是保守上限，假定每天都下載完整歷史檔，且每天內容都不同、因此無法由 SHA-256 去重。

| 更新節奏 | 年下載流量 | 年新增壓縮保存量 | 適用情況 |
| --- | ---: | ---: | --- |
| 每日 | 4.357 GB（4.057 GiB） | 1.930 GB（1.798 GiB） | 活躍回報源的最保守上限 |
| 每週 | 0.622 GB | 0.276 GB | 目前較合適的起步節奏 |
| 每月 | 0.143 GB | 0.063 GB | 靜態／緩慢更新檔案 |

其中 UAPDrop 幾乎佔了首批體積的全部；其他三個來源合計不足 0.3 MB 原始下載。因此不應每天重抓歷史檔案包，應以「首次完整快照 + 週／月更新 + 雜湊去重」為預設。NASA Horizons 已限制為同一 UTC 日期只保留一份有效星曆快照。

## 三、NARA 官方母庫的容量門檻

NARA 官方 UAP bulk 頁同時提供 metadata JSON 與 full ZIP，並說明檔案至少每年更新三次。其頁面列出經過處理的 Project Blue Book case files：

| 下載選擇 | 官方標示總量 |
| --- | ---: |
| 五個 images ZIP | 379.31 GB |
| 五個 PDFs ZIP | 391.59 GB |
| images + PDFs 都留 | 770.90 GB |

而該頁另列 Project Blue Book 36.48 GB、Air Intelligence 33.71 GB、4602D 29.77 GB、Bluebook artifacts 67.10 GB、OSI 34.45 GB、Condon 66.14 GB、Roswell 動態影像 16.25 GB 等大型包。用 NARA 同頁的 **120 個唯一 ZIP URL** 與其官方標示尺寸做去重加總，完整可下載 UAP ZIP 為 **1,077.123 GB**；這還沒有把解壓、OCR／縮圖、其他國家檔案館，或未公開下載材料算進去。

資料來源：[NARA UAP bulk download 官方頁](https://www.archives.gov/research/catalog/catalog-bulk-downloads/uap-bulk-download)。這些是官方標示的下載大小，不是我對壓縮率的猜測。

### 新確認但尚未下載的來源量級

| 來源 | 官方／上游公告量 | 目前採集決策 |
| --- | ---: | --- |
| UFOSINT `ufo_public.db` | 約 **553 MB** public SQLite（618,316 筆） | `OPEN_BATCH_REVIEW`：本機 provenance／privacy 轉換器已完成；仍缺受控 streaming、原始檔驗證與授權審核，不會出現在 `--all-open` |
| [WAR.GOV/UFO PURSUE](https://www.war.gov/UFO/) 五個 release | 文件約 **2.453 GB** + 影片約 **13.413 GB**，合計約 **15.866 GB** | `METADATA_BATCH_REVIEW`：只收 release manifest，絕不預設抓文件／影片包 |
| [The Black Vault UAP search/archive](https://www.theblackvault.com/documentarchive/) | 來源頁列其處理後的 UAP Release #1–#4 ZIP 約 **2.04 + 5.17 + 5.44 + 2.29 = 14.94 GB**；包含 OCR 後 PDF、影片、圖片與 metadata，屬私人二次處理／包裝，與官方 UAP release 有高重疊 | `INDEX_ONLY`：零下載、不納入 100 GB 預算，也**不能**與 WAR.GOV 的 15.866 GB 相加。只保留該頁作 FOIA／agency／官方原件尋址；若官方原件通過單獨權利、隱私與容量審核，仍只從原 agency 收 metadata manifest。 |
| [CelesTrak GP／OMM](https://celestrak.org/NORAD/documentation/gp-data-formats.php)／[使用政策](https://celestrak.org/usage-policy.php) | 站方只要求取實際需要的 current GP；未把全域 current catalog 公告成固定容量 | `OPEN_QUERY`：不為預備而抓全庫。僅對實際要比對的當下／近期報告取最小資料集，cache 至下一個 2 小時更新窗；同一更新最多一次，非 200 立即停 |
| [Space-Track GP_HISTORY](https://www.space-track.org/documentation) | 官方文件稱超過 **1.38 億** historical element sets，但未提供可安全套用的單一壓縮容量 | `LICENSE_REQUEST`：這 1.38 億筆不納入任何本機容量計畫，也不為估容量去下載／枚舉。若未來取得帳號／條款，只允許逐案、時間界定的歷史比對與 receipt；完整歷史軌道鏡像另立專案、儲存與權利審核 |
| [GFZ Kp index 資料／API](https://kp.gfz.de/en/data) | 官方提供自 1932 年起的 Kp／ap 等 scalar time series、Web API 與版本化 DOI archive；本輪不為估量而下載 | `OPEN_BATCH_REVIEW`：即使完整數值序列通常遠小於影音／軌道歷史庫，仍先用小時間窗確認 response schema、definitive/nowcast、DOI 與壓縮率，再把實測值寫入容量表。它只會是低量控制表，不含圖像／媒體 |
| [Meteoritical Bulletin Database](https://www.lpi.usra.edu/meteor/metbull.php)／[Meteoritical Society 說明](https://meteoritical.org/publications/meteoritical-bulletin) | 權威已命名隕石目錄含 map-service／精確 find-location 尋址，但未公告可安全鏡像的固定容量，且本站本輪收到 access gate | `INDEX_ONLY`：零 request、零 KML、零地圖、零標本／影像／敘述。只保留 parent URL、資料庫角色與未來單案必要欄位契約；不為估量而列舉、抓取或把目錄紀錄／座標放入事件或地圖預算。 |
| [NASA POWER Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/) | 全球氣象／太陽 archive 很大，但官方 API 是單點、時間窗輸出；本輪不以掃全球格網來估算 | `OPEN_QUERY`：只存被選定 report／研究格網的 bounded response 與 receipt。完整氣象 archive 不納入工作區容量；先驗來源格網、期間、參數數量和壓縮率，再以實測決定長期資料預算 |
| [WMO OSCAR/Surface](https://oscar.tools.wmo.int/web-client/)／[NOAA NCEI ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database) | OSCAR 是全球站點／平台 metadata，未公告可安全套用的單一 snapshot 容量；ISD 官方頁說全庫約 **600 GB 未壓縮**，涵蓋逾百個輸入源、且站點與歷史覆蓋不均 | `METADATA_BATCH_REVIEW`：本輪零 request。OSCAR 先只存 schema／版本／權利 manifest；ISD 不進全庫下載或目前 100 GB 預算。日後只在報告／研究格已選定時，做一個 station／時間窗的最小 query 或 availability aggregate，先實測回應大小與品質旗標再定預算。 |
| [WorldPop Global 2 API](https://api.worldpop.org/v2/) | 官方 API 是 2015–2030 的 global 100m／1km population polygon summary；不以「所有年份 × 所有 raster」假裝成單一可安全相加容量 | `OPEN_QUERY`：本輪零 request／零 raster。只在地圖格網與年度確定後，做 bounded polygon summary 並保存小型 response + receipt；全域 100m／1km raster 鏡像不列進此工作區容量計畫，先以一個受控 cell／country 實測回應大小再估。 |
| [World Bank WDI：IT.NET.USER.ZS](https://data.worldbank.org/indicator/IT.NET.USER.ZS?most_recent_value_desc=true&year_high_desc=true) | 本專案 193 國 × 1990–2025 的理論上限僅 **6,948** country-year scalar（未扣缺值）；本輪未呼叫 API，故不捏造 byte 數 | `OPEN_BATCH_REVIEW`：若驗證通過，預期屬極低量 country-year control；仍要保存 API／資料版本、citation、缺值與 receipt。它不需要任何 raster、媒體或全域逐點下載。 |
| [JPL Small-Body Identification API](https://ssd-api.jpl.nasa.gov/doc/sb_ident.html)／[MPC Data Services](https://data.minorplanetcenter.net/)／[ESA Gaia Archive](https://gea.esac.esa.int/archive/)／[NASA Exoplanet Archive TAP](https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html) | 小天體、恆星與系外行星的全域科學 catalog 規模極大，且各服務同時提供有限 query 與不同 bulk product；本輪不做任何 request 或容量探測 | OPEN_QUERY：它們是獨立天空／科學目錄域，不是事件資料。只准對單一已授權 report 的有限時間／視場做最小查詢，或取得 schema；不估算／下載「全宇宙」、不鏡像 Gaia/MPC/系外行星資料、不寫進目前 100 GB 的事件與地圖預算。 |
| [義大利空軍 OVNI 官方頁](https://www.aeronautica.difesa.it/ovni/) | 官方頁以歷史期間／年別列已結案案件入口；本輪不為估量而開啟或下載 PDF／附件，故沒有可誠實加總的 byte 數 | `METADATA_BATCH_REVIEW`：先只記根頁、期間／年別可用性、權利與個資遮罩規則；若日後獲逐件許可，先以單一 metadata manifest 實測，再另立預算。原案、PDF、照片、影片與附件不進目前 100 GB 計畫。 |
| [Forsvaret「UFO-arkiv online」](https://www.forsvaret.dk/da/nyhedsarkiv/flyverstaben/2009/ufo-arkiv-online/) | 官方頁列可取得的歷史混合 archive；本輪不為容量估算而開啟或下載任何檔案，故沒有可誠實加總的 byte 數 | `METADATA_BATCH_REVIEW`：先只記 release／期間／來源構成與遮罩規則。通過逐件權利、個資、去重與人為核准前，檔案、原案、照片、影片與附件全不進目前 100 GB 計畫。 |
| [CIA「UFOs: Fact or Fiction?」](https://www.cia.gov/readingroom/collection/ufos-fact-or-fiction)／[FBI Vault「UFO」](https://vault.fbi.gov/UFO/)／[NSA FOIA UFO 主題頁](https://www.nsa.gov/Helpful-Links/NSA-FOIA/Frequently-Requested-Information/Unidentified-Flying-Objects-UFOs/) | 三者都是官方 parent-level collection／vault／policy 入口；本輪不翻頁、列舉分件或取樣，因此沒有可誠實加總的檔案數或容量 | CIA／NSA 為 `INDEX_ONLY`，FBI 為 `METADATA_BATCH_REVIEW`：零 request、零 PDF／掃描／OCR／媒體。只保存 URL、頁面角色與存取限制；不以「官方 collection」假定可鏡像，也不把其中任一歷史文件納入目前 100 GB 計畫。 |
| [LAC Herzberg Institute non-meteoric sighting reports series](https://recherche-collection-search.bac-lac.gc.ca/eng/Home/Record?IdNumber=134925&app=fonandcol&new=-8585647437964411660) | 正式目錄列 1965–1995、2.6 m textual records、1 object、12 photographs、1 map、126 個下層描述與 3 個 digital object；這些是館藏／媒體型別描述，不是可加總的可下載 GB | `METADATA_BATCH_REVIEW`：零 request、零下層列舉、零數位件。先建 series／finding-aid／restriction manifest；文字、卡片、照片、物件、地圖與任何掃描都排除於目前 100 GB 計畫。實體長度、下層描述數與數位物件數都不能當事件數或容量估計。 |
| [UFO Ireland 通報頁](https://ufoireland.com/report-a-sighting/) | 公開頁顯示可填 email／姓名、文字與多附件上傳及刊登同意選項，但未公告案件數、附件總量、留存期、公開 catalog、匯出範圍或重用權；不可由表單的單檔限制推估 archive 容量 | `OPEN_QUERY`：本輪零 submit、零登入、零案件頁、零附件。只允許未來保留 parent page／欄位／同意規則 manifest；任何證詞、影音、照片、個資與精確位置均排除於目前 100 GB 計畫，取得去識別／保存／撤回與授權契約前不作容量估算。 |
| [UFO Klub Trnava](https://www.ufoklub-trnava.sk/) | 現役入口有通報表和觀察分類，但未公告個案總量、附件／媒體總量、下載範圍、保存期、公開 catalog 或重用權；不能由可見入口或頁面更新頻率估算容量 | `OPEN_QUERY`：零 submit、零登入、零觀察／論壇個案、零附件。僅可保存 root／form 存在與權利問題 manifest；原始文字、照片、影片、姓名、聯絡資料與精確位置都不進目前 100 GB 計畫。 |
| [DEGUFO Austria：UFO melden](https://www.degufo.at/ufo-melden/) | 現役本地通報入口有問卷與保密個案調查說明，但未公告個案、附件／媒體總量、下載範圍、保存期、公開 catalog 或重用權；不能由問卷或聯絡方式估算 archive 容量 | `OPEN_QUERY`：零 PDF、零 submit、零登入、零個案、零附件。僅可保存 root／portal 與資料處理規則 manifest；原始文字、照片、影片、姓名、email、聯絡資料與精確位置都不進目前 100 GB 計畫。 |
| [ASSA Report a Sighting](https://assa.saao.ac.za/contact-us/report-a-sighting/) | 南非現役天空觀察回報入口連到 sightings archive，但未公告個案、附件／媒體總量、下載範圍、保存期、公開 catalog 或重用權；且它是 `control-first` 天文判讀來源，不能由表單或 archive 連結估算 UAP 資料量 | `OPEN_QUERY`：零 submit、零登入、零個案、零附件。僅可保存 root／portal／欄位與 archive-existence manifest；原始文字、照片、影片、姓名、email、GPS 與精確位置都不進目前 100 GB 計畫，也不進 UAP 分子。 |
| [DUAP Polaris 現役回報／archive 入口](https://duap-polaris.hr/polaris/index.php) | 克羅埃西亞本地回報／archive 入口，但未公告個案、附件／媒體總量、下載範圍、保存期、公開 catalog 或重用權；不能由可見見證分類或聯絡方式估算 archive 容量 | `OPEN_QUERY`：零 submit、零 email、零登入、零個案、零附件。僅可保存 root／portal／分類與組織狀態 manifest；原始文字、照片、影片、姓名、email、聯絡資料與精確位置都不進目前 100 GB 計畫。 |
| [BalkanUFO Registar](https://balkanufo.org/balkan-ufo/)／[通報表](https://balkanufo.org/prijave/) | 現役區域平台公開列 PDF、RAW、照片／影片等可能高容量附件，但沒有可信總件數、總大小、保存期、公開範圍、license、去識別或撤回規則；不能從單案可見檔案大小外推 archive 容量 | `EXPERIMENTAL`／`INDEX_ONLY`：零 submit、零登入、零案例、零附件、零下載。只可保存 root／form／可見格式與權利問題 manifest；任何文字、原始檔、影音、姓名、聯絡、細位置與座標都不進目前 100 GB 計畫。 |
| [CROM UAP 目擊回報入口](https://reporte.cromuap.com.mx/index.html) | 現役墨西哥表單可收文字、繪圖／影片等附件、姓名、聯絡與細位置，但未公告案件量、附件量、大小上限、保存期、公開 catalog、去識別、撤回或重用範圍；不能由表單欄位外推 archive 容量 | `OPEN_QUERY`：零 submit、零登入、零 testimonials、零案件、零附件、零下載。只可保存 root／form／欄位與同意規則 manifest；所有原始文字、影音、姓名、聯絡、細位置與座標均不進目前 100 GB 計畫。 |
| [《科學東亞》對韓國 UFO 調查分析中心的 2021 報導](https://images.dongascience.com/uploads/article/pdf/202110/S202110-all002.pdf) | 報導轉述年量級影像投稿，但沒有母庫總量、單檔大小、媒體格式、保存期、公開範圍、匯出或重用條款；不能由「每年投稿數」推出 GB | `ARCHIVE_REQUEST`：零 PDF、零影像、零個案 request。它只保留持有人／資料型態尋址；在取得資料契約與單一去識別 manifest 的實測前，所有原始影像、文字、姓名與位置均排除於目前 100 GB 計畫。 |
| [Andina OIFAA 2013](https://andina.pe/agencia/noticia-cada-dia-mas-personas-avistan-cosas-extranas-los-aires-482325.aspx)／[FAE Dirección de Desarrollo Aeroespacial](https://www.fae.mil.ec/direccion-de-desarrollo-aeroespacial/) | 前者是秘魯國家通訊社的機構任務報導，後者是厄瓜多空軍的歷史組織頁；兩者都沒有公告 UAP／CEIFO 案件檔數、可下載 metadata 範圍或容量 | `ARCHIVE_REQUEST`：兩頁僅作持有人／年代／檔號尋址，零下載。文章、照片、影片、註解與所有後續原始案件均排除於目前 100 GB 計畫；沒有可誠實估算的容量前，不拿網頁大小或組織存在捏造 GB。 |
| [斯里蘭卡 SLUFORA 歷史來源鏈](https://www.sundaytimes.lk/981206/plus9.html)／[在地回顧](https://archive.roar.media/english/life/srilanka-life/of-aliens-and-ufos-e28092-sri-lankas-strangest-sightings) | 只驗到歷史回報網、組織解散與可能由書籍保存 case files 的敘述；未驗持有館、檔案數、檔案大小、數位化範圍或重用權，不能估 byte 數 | `ARCHIVE_REQUEST`：零下載。先索取 title／年份 finding aid、可公開去識別 metadata 和權利；書籍、案例、照片、影片與原始敘述不進目前 100 GB 計畫。 |
| [UNAM Hemeroteca Nacional 的 125 年 OVNI 新聞說明](https://www.dgcs.unam.mx/boletin/bdboletin/2022_908.html) | 只驗到主題策展與報刊館藏範圍；未驗專題的檔案數、頁數、數位化範圍、API、批次重用權或檔案大小，不能估 byte 數 | `ARCHIVE_REQUEST`：零下載。若日後取得清楚的題名／年份 metadata 契約，先對單一 manifest 實測；報紙頁、全文、影像與 OCR 不進目前 100 GB 計畫。 |
| [El Diario de Hoy 歷史檔案尋址頁](https://www.elsalvador.com/h-entretenimiento/h-cultura/jueves-recuerdo-ovni-sobrevuela-san-salvador-en-1969/1083591/2023/) | 只驗到一條本地報紙歷史原件的持有人／年代尋址線；未驗原始版面數、數位化範圍、catalog、API、批次重用權或檔案大小，不能估 byte 數 | `ARCHIVE_REQUEST`：零下載。若日後權利人提供明確的刊名／日期／版面 metadata 契約，先對單一 manifest 實測；原報頁、全文、影像與 OCR 不進目前 100 GB 計畫。 |
| [NOAA NCEI Passive Acoustic Data](https://www.ncei.noaa.gov/products/passive-acoustic-data) | 官方說明涵蓋 raw audio 與衍生產品，但未公布可直接相加的全庫容量 | `METADATA_BATCH_REVIEW`：各 collection 的聲學 raw audio 容量差異很大，尚未取樣就不能誠實估算。先只收 deployment manifest、格式、權利與檔案大小；這是海洋聲景控制，非 USO 事件集 |
| [Argo GDAC](https://argo.ucsd.edu/data/data-from-gdacs/)／[Copernicus Marine Data Store](https://data.marine.copernicus.eu/) | Argo 官方說明提供完整 global collection 的 metadata、detailed trajectory、profile、technical NetCDF 與 index files，但未給本輪可安全套用的單一容量；Copernicus 是多產品的全球／區域資料服務，產品、格網與歷史長度不同，不能捏造成一個總 GB | Argo 為 `METADATA_BATCH_REVIEW`、Copernicus 為 `LICENSE_REQUEST`：本輪零 request、零帳號註冊、零軌跡／profile／格網下載。兩者皆不進目前 100 GB 預算；若未來獲授權，只能先以一個指定海域／時間窗／產品做最小實測，分別記版本、大小、QC／analysis status、license 與 receipt。 |
| [OOI Data Explorer](https://dataexplorer.oceanobservatories.org/help/)／[Ocean Networks Canada Oceans 3.0](https://data.oceannetworks.ca/)／[EMSO Data Portal](https://data.emso.eu/)／[MBARI Data & Repositories](https://www.mbari.org/our-work/data-repositories/) | 固定／纜線／繫泊與研究航次觀測資料的型別、歷史長度、資料延遲、媒體比例與 access 條件差異很大；本輪未枚舉 catalog、未 request API／資料交付，沒有可誠實相加的全庫容量。部分入口可含 raw／realtime、被動聲學、影像、影片、地圖或大型 archive，不能以「公開 portal」假定低量。 | OOI／EMSO／MBARI `METADATA_BATCH_REVIEW`；ONC `LICENSE_REQUEST`，本輪零 request、零帳號／token、零下載。只允許未來先對單一已核准 source/product 的 metadata manifest 實測大小、版本、權利與 receipt；連續量測、聲學、聲譜、影像、影片、精確站位、載具軌跡與完整 archive 全不進目前 100 GB 預算。 |
| [UCalgary Space Remote Sensing／THEMIS ASI](https://data.phys.ucalgary.ca/data/) | 官方開放高緯度全天相機／極光 archive，但未以單一可相加數字公告全庫容量 | `METADATA_BATCH_REVIEW`：先只收 station／產品／日期／大小 manifest。圖像與校正資料可能遠大於事件表；不為估容量而枚舉或下載影像 |
| [Natural Earth 50m Admin 0 Countries](https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/)／[UNSD M49](https://unstats.un.org/unsd/methodology/m49/overview/) | Natural Earth 頁列 version 5.1.1 countries vector 約 **781.78 KB**；M49 是低量 country/area code reference | `OPEN_BATCH_REVIEW`：僅作未來 country-coverage renderer asset／統計主鍵，不是事件或 control。尚未下載；真接入時保存版本、SHA、boundary view 和 193-member roster version。不可把 NE 的 258 顯示單位或 M49 的所有 area 當成 193 國分母 |
| GEIPAN cases + witness CSV | 尚未以 HEAD／GET 探測大小 | `OPEN_BATCH_REVIEW`：先完成關聯表 normalizer；不為容量估算而接觸來源 |
| [SCEAU／Archives OVNI](https://www.sceau-archives-ovni.org/) | 法國 archive-transfer 組織，材料可在編目後放入不同國家／地方檔案或公共圖書館；本輪沒有對任一具體 deposit 取得數位化範圍、檔案數、檔案大小或重用權，不能估 byte 數 | `ARCHIVE_REQUEST`：零下載。先取得具體 collection／deposit 的 finding aid、館藏位置、年代、公開 metadata 與存取／重用條件，再以單一 manifest 實測；卷宗、掃描、照片、影音與全文均不進目前 100 GB 預算。 |
| Global Meteor Network | 全表量未假裝估計 | 本機 planner 限制 31 天／1,000 筆 composite-cursor query；仍需一頁 probe，禁止無界全表下載 |
| [USGS Earthquake Catalog API](https://earthquake.usgs.gov/fdsnws/event/1/)／[Smithsonian GVP](https://volcano.si.edu/search_eruption.cfm)／[NASA Black Marble](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/science-domain/nighttime-lights/)／[GDACS](https://www.gdacs.org/gdacsapi/swagger/index.html) | USGS／GVP 可做小型有界 metadata；Black Marble 的日／月／年全球 raster 可遠大於事件表；GDACS 是可能重複上游的 alert gateway。本輪零 request，不能捏造單一「全球背景資料」總量 | USGS 僅時間－H3 bounded query；GVP 先驗 spreadsheet；Black Marble 只做 product manifest、日後若核准只用粗格統計，不下載全球 tile；GDACS 僅上游／alert manifest。四者都不會進目前的事件分子，Black Marble raster 也不進目前 100 GB 計畫。 |
| [GDELT Data](https://www.gdeltproject.org/data.html)／[GKG index](https://data.gdeltproject.org/gkg/index.html)／[GKG 2.1 codebook](https://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf) | GKG 目錄樣本日檔可見約 15–42 MB 的壓縮檔，但目錄持續更新，這不是全史、當期或可安全相加的容量估計 | `INDEX_ONLY`：本輪零 request。完整 GKG、文章 URL／內文、圖片與影片都排除於目前 100 GB 計畫；若未來另行放行，只能先以有限 query 的去內容 metadata／receipt 實測，不得以日檔大小推估或鏡像「全球新聞庫」。 |
| [GEBCO 全球海底地形](https://www.gebco.net/data-products/gridded-bathymetry-data) | 官方 global grid 會隨年度 release 改版；其公開頁曾列 global NetCDF 約 **4 GB**、解壓約 **7.5 GB**，並提供 tile／subset／WMS。此為官方某 release 的公告量級，不是本機測量，也不能假定後續版本相同 | `METADATA_BATCH_REVIEW`：本輪零 request、零 tile。只存 release／datum／TID／授權 manifest；完整全球 bathymetry 及其衍生 raster 都排除於目前 100 GB 事件與地圖預算。若日後真有海域 UI 需求，先以一個固定 bbox 的最粗必要 subset 實測大小、版本與快取期限，再另立預算。 |
| [American Meteor Society Fireball Logs](https://amsmeteors.org/fireballs/fireball-report/)／[IMO Video Meteor Network](https://www.imonet.org/access.html) | AMS 未公告可安全套用的 bulk 量；IMO 的完整 archive 需帳密、Glacier restore，沒有本輪可驗的免費下載總量 | 前者僅做公開頁／去識別 aggregate 的 `OPEN_QUERY` 審核；後者為 `LICENSE_REQUEST`。本輪零 request、零媒體、零 archive restore，不能把任一方的全部報告或相機資料納入容量預算。 |

UFOSINT 的數字來自其公開 schema／methodology 文件；WAR.GOV 的數字來自 2026-08-13 官方 portal 顯示的五個 release bundle（R1–R5）。它們是「來源公告的當前量級」，不該被加總成全球所有資料的精確總量。

### AFU 私有母庫的歷史容量參考（不是下載計畫）

[AFU 2017 年報](https://www.afu.se/afu2/wp-content/uploads/2018/11/AFU-Annual-Report-2017_OCR.pdf) 是館方第一手的**歷史自述**，不是目前可公開下載的 inventory。它列出的內部量級如下；僅用來避免把「全球資料」錯估成幾百 GB。

| 2017 年報分類 | 館方自述檔案數 | 館方自述儲存量 |
| --- | ---: | ---: |
| UFO reports | 約 21,000 | 約 136 GB |
| UFO organizations／groups／individuals | 約 80,000 | 約 1.24 TB |
| Video | 約 3,500 | 約 9.3 TB |
| Photo library | 約 12,000 | 約 232 GB |
| 全館內部儲存 | — | 當時「接近 20 TB」 |

這些是 2017 年單一館藏的自報值，分類彼此可能有索引、備份或衍生檔重疊，**不可相加成可下載總量，也不可外推成 2026 年容量**。年報同時說明版權與敏感見證材料限制公開；因此 AFU 保持 `ARCHIVE_REQUEST`，本輪沒有下載、列舉或鏡像其中任何材料。

[National UFO Historical Records Center（NUFOHRC）](https://nufohrc.org/) 的館方頁列出多個歷史 collection，內容可含案件卷宗、文獻、信件、照片、音／影片與研究材料，但本輪沒有可驗的逐件 catalog、數位化範圍、公開檔案數、檔案大小或通用重用權。它不進容量加總或採集器；只列 `ARCHIVE_REQUEST`，日後即使取得館方同意，也必須先以單一 collection-level manifest 實測並另立權利／隱私／容量預算。

[Northwestern University 的 J. Allen Hynek Papers](https://findingaids.library.northwestern.edu/repositories/6/resources/373) 與 [University of Arizona 的 James E. McDonald papers](https://lib.arizona.edu/special-collections/collections/james-e-mcdonald-papers) 都是正式館藏尋址，而非可自由下載資料集。前者館方列 14 箱，後者明示含訪談、照片、錄音與案件材料；但盒數或文字範圍不能換算成安全容量。兩者皆不進容量加總、採集器或目前 100 GB 預算，僅能在取得指定 collection／series 的權利與去識別契約後，以單一 manifest 實測。

[Rice University 的 Richard F. Haines Ufology papers](https://archives.library.rice.edu/repositories/2/resources/1404) 與 [Jacques F. Vallee UFO and paranormal phenomena papers](https://archives.library.rice.edu/repositories/2/resources/1085) 也同樣排除。官方 finding aid 分別列 17 與 48 linear feet，但那是實體館藏長度、不是數位容量；兩者皆 off-site，Vallée 的不同系列另有 2028／2031 的 donor access restriction。它們不進採集器、流量估算或 100 GB 預算；未來即使獲准，也只能先取得單一 collection／series 的 metadata manifest 與權利／隱私範圍，不可預先請求或下載卷宗、照片、影音、訪談或原始回報。

[University of Utah 的 Frank B. Salisbury papers](https://archiveswest.orbiscascade.org/ark:80444/xv35620) 亦排除。其 finding aid 列整體 234.5 linear feet、含 1952–1996 UFO materials series，但整館長度不代表 UAP 子集的數位容量，也不代表可下載量；材料限館內使用、權利並非全部由館方控制，且有人格／隱私限制。它不進採集器、流量估算或 100 GB 預算；任何未來審核只能先看 collection／series metadata manifest，不能以目錄存在為由請求、掃描或下載個案、通訊、照片、聲音或影音。

[University of Wyoming 的 R. Leo Sprinkle papers](https://archiveswest.orbiscascade.org/ark:80444/xv805708) 是少見列出數位量的例子：87 cubic feet（94 boxes）加 **19.04 GB**。但其 Research Use Agreement 禁止記錄／重製任何人或家庭姓名，且部分盒件封存至 2095；因此 19.04 GB 不是可抓流量、不是可入庫資料量，也不納入目前 100 GB 預算。日後若有明確館方授權，第一步仍只能是 collection／series metadata manifest 和去識別契約，不能要求或下載個案、通訊、評估、照片、影音或原始研究材料。

[Ohio State University 的 William E. Jones UFO Collection](https://library.osu.edu/collections/SPEC.RARE.0018/inventory) 只揭示 inventory，不提供可安全加總的數位容量；其混合報告、通信、訪談、視聽與電腦媒體，部分材料還需館員事前同意。它不進採集器、流量估算或 100 GB 預算。日後僅可先索取 collection／series metadata manifest、權利、access restriction 與去識別範圍，不能按 inventory 批次要求或下載任何 case／媒體／儲存媒體內容。

[Texas A&M University 的 Roy Craig Collection](https://findingaids.library.tamu.edu/roy-craig-collection) 僅列 9 boxes／約 10 linear feet 的實體館藏，包含可能涉及個案、實物、照片與錄音的 Condon study 工作材料；材料 off-site，且各件著作權仍可能屬原作者或繼承人。該數字不是數位容量、可抓流量或可公開範圍，零納入採集器與 100 GB 預算。未來只可先請求 collection／series metadata manifest、權利、去識別與存取條件。

[American Philosophical Society 的 Edward U. Condon Papers](https://as.amphilsoc.org/repositories/2/resources/1395) 列全館 75 linear feet、其中 UFO materials Series V 為 33 boxes／16.5 linear feet；這是實體館藏描述，不代表數位化、可下載或純 UAP 容量。它不進採集器、流量估算或 100 GB 預算；日後即使取得許可，第一步也只能是 Series V 的 collection-level metadata manifest、權利與去識別邊界，不能請求或下載 case／folder 級材料、照片、錄音、剪報或通訊。

[Rice University 的 Clifford Stone Ufology research papers](https://archives.library.rice.edu/repositories/2/resources/1560) 只列 13 linear feet；這是混合研究材料的實體範圍，無法轉成數位容量、UAP 子集容量、可抓流量或重用權。它完全排除於採集器與 100 GB 預算，未來只能先詢問 collection／series metadata、access、權利、去識別條件與來源重疊。

[Rice University 的 Dennis Stillings research papers](https://archives.library.rice.edu/repositories/2/resources/1551) 列為 **234 GB** digital collection，但主題混合 bioelectromagnetics、parapsychology、health 與 ufology；故 234 GB 既不是純 UAP 容量，也不是可公開、可下載、可重用或可去識別的量。它不進採集器、流量估算及 100 GB 預算。若日後取得明確館方授權，第一步仍只能是 collection／series-level metadata manifest、nearline access、權利與去識別審核，不能枚舉、下載或處理任何數位件、照片、通訊、筆記、個案或媒體。

[Rice University 的 Wendelle Stevens collection](https://archives.library.rice.edu/repositories/2/resources/1528)、[Larry W. Bryant collection](https://archives.library.rice.edu/repositories/2/resources/1390)、[Columbia University 的 Leon Davidson collection](https://findingaids.library.columbia.edu/pdf/cul-4079689.pdf)，以及 [American Philosophical Society 的 Sanderson](https://as.amphilsoc.org/repositories/2/resources/1789)／[Klass](https://as.amphilsoc.org/repositories/2/resources/2894) 都只公布實體館藏描述（8、120、65、27 linear feet 等）或目錄；沒有一筆能誠實轉換成可抓 GB、合法可重用量或純 UAP 容量。它們全數排除於採集器、流量估算與 100 GB 預算。日後一律先取得 collection／series metadata manifest、權利、敏感內容／隱私和來源重複審核，不請求或下載 case／folder 級材料、照片、影音、聲音、通信或剪報。

## 四、可執行的容量分層

| 層級 | 保存內容 | 建議容量 | 目前 431.8 GiB 是否可行 |
| --- | --- | ---: | --- |
| A：來源圖譜 | URL、權利／更新狀態、目錄 metadata | < 10 GB | 可以 |
| B：全球事件表 | 公開 CSV/API、raw gzip、canonical JSONL、天文／流星控制 | 10–25 GB | 可以 |
| C：選案證據 | 被模型挑中的文件、照片／影片與衍生縮圖 | 100–200 GB | 可以，但要配額 |
| D：完整 NARA 原始 ZIP 母庫 | 僅留壓縮包、不要同時解壓 | **外接／物件儲存至少 2 TB** | 不可以 |
| E：完整母庫 + 解壓 + OCR／影像衍生物 | 原 ZIP、解壓內容、索引及再生檔 | **至少 4 TB** | 不可以 |
| F：跨國私有／實體母庫鏡像 | 只在逐件取得授權後才可能成立 | **不預先採購為「可抓全世界」**；單一 AFU 的 2017 館內總量已接近 20 TB。NUFOHRC、Hynek、McDonald、Rice Haines／Vallée、Utah Salisbury、OSU Jones 等未有可驗公開數位容量；Wyoming Sprinkle 雖列 19.04 GB，仍受姓名／封存限制，不能作可用容量（實體長度也不能換算） | 不可以；且權利不是容量可解決 |

全球所有民間與政府來源的原始照片、影片、掃描件並沒有一個可驗證的總量，不能誠實地報成精確 GB。若把目標定義為「所有事件記錄與可下載 metadata」，層 B 足夠先建機率模型；若目標是「所有原始媒體副本」，容量會進入多 TB，且每一來源要分別確認條款、個資與下載權利。

上述層 B／100 GB 預算**明確排除**完整衛星歷史軌道庫（Space-Track GP_HISTORY）、全天相機影像、被動聲學原始音訊、完整全球氣象 archive，以及 WorldPop 的全年度高解析人口 raster。GFZ Kp／ap 這類低量 scalar control、World Bank 的國別年表、NASA POWER／WorldPop 這類按案／按格時間窗的 bounded response 可以在契約通過後納入層 B，但仍不為了「看起來完整」而先抓。這些資料是對單案／單站的控制證據，不是「把全宇宙資料抓下來」的必需品；把它們鏡像進來既無助於 `P_report` 的分子，也會把容量與授權風險無限放大。

### 工程預算（非假裝精確的全球總量）

| 目標 | 最低可啟動 | 建議預留 | 原因 |
| --- | ---: | ---: | --- |
| 所有合法可得的事件／控制／來源 metadata | 25 GB | **100 GB** | text／CSV／JSON、raw、canonical、GeoParquet、H3／map products 與增量空間 |
| 加上經授權、人工挑選的文件／照片／影片 | 200 GB | **500 GB** | 媒體大小差異遠大於事件列；要有配額與內容雜湊去重 |
| 完整 NARA 官方 UAP ZIP | 1.1 TB | **2 TB** | 官方 ZIP 本身約 1.077 TB，需更新與操作緩衝 |
| NARA 完整 ZIP + 解壓／OCR／縮圖 | 2 TB | **4 TB** | 需要保留原 ZIP、工作檔和衍生品 |
| 私有／實體母庫全鏡像 | 不作可用容量估計 | **不立項** | AFU 2017 單館內部儲存已接近 20 TB，但沒有可批量下載權利；先做目錄／授權，不以硬碟替代同意 |

「全世界所有未受限的媒體」沒有可證實總量：NUFORC、MUFON、地方研究會、歷史掃描、私人照片和影片中不少沒有 bulk 下載權限或未公開大小。因此不能誠實報一個全球精確 TB 數字；完整 NARA 的 1.077 TB 是目前可驗證的下限之一，不是全球上限。

## 五、採集決策

1. 目前直接下載端點繼續進層 B；raw／canonical 都壓縮並保留收據。
2. NARA 與其他大型檔案庫先只收 **metadata JSON + 下載 URL + 檔案大小 + SHA-256**，不抓 full ZIP。
3. 模型或人工挑出高價值事件後，才放行對應照片／PDF／影片到層 C。
4. 真要做全母庫鏡像，先掛 2 TB（只留 ZIP）或 4 TB（需解壓與 OCR）的獨立磁碟；不得塞進交易工作區。
