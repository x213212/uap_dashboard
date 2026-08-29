# 8 國缺口：來源研究路由表

更新：2026-08-13（Asia/Taipei）  
範圍：`coverage_inventory.py gaps` 所列的 8 個聯合國會員國；`C=0`、`D=8`。

這不是「60 國沒有目擊」或「60 國沒有外星人資料」的清單，而是 **尚未驗到本地、題材直接且可追溯的合格來源路徑**。B 級控制資料入口並不等於 UAP／USO 母庫；本表仍把未來工作固定成可重現的尋址佇列，不會把全球聚合站、外國文件或泛用國家檔案硬算成當地 UAP 資料庫。

## 使用規則

- `ROOT_CONFIRMED`：已驗到本地的官方檔案／研究入口，但尚無 UAP 專題 catalogue、具名報導或正式回報路徑；**國別仍維持 D**。
- `FOREIGN_ONLY`：已有外國或區域保存的紀錄，**國別仍維持 C**；它不是本地來源。
- `NO_PUBLIC_ROOT`：本輪未驗到可公開、可追溯的本地入口；不代表該國沒有檔案或目擊。
- 只有「本地持有人 + UAP／不明空中或水下現象的具名報導、館藏 finding aid、正式申請或回報路徑」才可由 C／D 升為 B／A。泛用檔案館、單一社群貼文、外國檔案與全球資料庫都不夠。
- 這是 **source-manifest** 佇列，不是爬蟲清單：不下載文章、原始證詞、照片、影片、姓名、聯絡方式或精確位置；不繞過付費牆、登入或 CAPTCHA。

離線取得最新名單：

```bash
python3 uap_lab/coverage_inventory.py gaps --format csv
python3 uap_lab/coverage_inventory.py gaps --format json
```

## 一、太平洋：4 個 D 國 + 4 個 B 級海事／地質控制來源

這一組最容易被全球／殖民檔案、論壇或鄰國新聞「假補齊」。D 列只用於詢問 collection-level finding aid；索羅門群島、東加、吐瓦魯與萬那杜為本輪已驗的本地水域／地質控制來源，仍不是 USO 事件資料。

| 國家 | ISO | 目前可用路由 | 目前能證實／不能證實 | 下一道門檻 | 狀態 |
| --- | --- | --- | --- | --- | --- |
| 密克羅尼西亞聯邦 | FM | [FSM Office of National Archives, Culture and Historic Preservation](https://fsmculture.wordpress.com/) | 頁面自稱為 FSM National Archive of History and Culture；未驗 UAP 專題索引、公開 catalogue 或重用條款 | 只詢問「民航／流星／不明物」是否有 collection-level finding aid、年代與去識別 metadata | `ROOT_CONFIRMED`；D 不變 |
| 帛琉 | PW | [Republic of Palau 2019 National Archive System RFP](https://www.palaugov.pw/wp-content/uploads/2019/04/PCS-2019-013MCCA.pdf) | 政府文件證實曾規劃國家檔案系統、索引與搜尋功能；**未驗**目前 public catalogue、現行資料庫或 UAP 主題入口 | 先找現行 archive owner／public catalogue；再只問 collection-level metadata | `STATE_EVIDENCE_ONLY`；D 不變 |
| 索羅門群島 | SB | [《Solomon Star》未知漂流海上物報導](https://www.solomonstarnews.com/a-strange-object-floating-along-the-maramasike-passage-in-malaita/)／[National Archives access policy（Solomon Islands Government）](https://solomons.gov.sb/wp-content/uploads/2020/02/AR-Policy-1-Access-Policy.pdf) | 本地日報保存未知漂流物初報及疑似廢棄駁船的常規候選；官方 access policy 可作後續 finding-aid 路徑。兩者都不是 UAP／USO 事件庫 | 只詢問海事／報刊的 collection-level finding aid；不抓文章、影像或原案 | `CONTROL_FIRST`；B（不計入 UAP／USO 分子） |
| 萬那杜 | VU | [Vanuatu Meteorology and Geohazards Department（VMGD）：Volcano Alerts](https://www.vmgd.gov.vu/geohazards/volcanoes) | 政府機關頁明示重大火山活動變化時發布 alert bulletin，並列 East Epi 海底火山的公開自然現象脈絡；不是 UAP／USO 事件、即時感測資料或重用契約 | 只詢問公告系列的年月、公開 metadata、權利與去識別／粗格可用範圍；不輪詢警報、不取相機、地震圖、風險地圖、原始感測、船位或精確位置 | `CONTROL_FIRST`；B（不計入 UAP／USO 分子） |
| 吉里巴斯 | KI | [Kiribati Government：Broadcasting and Publication Authority](https://kiribati.gov.ki/information/broadcasting) | 政府頁確認 BPA 經營 Radio Kiribati 與國家報紙 *Te Uekera*；未驗可查的歷史索引、題材直接報導、UAP／USO catalogue、去識別資料或重用條款 | 只詢問報紙／廣播的民用天空、水下或未知落物 collection-level finding aid、年代、公開 metadata 與權利；不開啟／下載刊物、錄音、影像、姓名或精確位置。`ROOT_CONFIRMED`；D 不變 |
| 諾魯 | NR | [Nauru Government Information Office：Nauru Bulletin](https://www.nauru.gov.nr/government-information-office/nauru-bulletin.aspx) | 政府頁確認 *Nauru Bulletin* 是 Government Information Office 發行的定期出版品並按年度列入口；未驗題材直接索引、UAP／USO catalogue、去識別資料或重用條款 | 只詢問歷年 bulletin 的民用天空、水下或未知落物 collection-level finding aid、年代、公開 metadata 與權利；不開啟／下載 PDF、刊物、影像、姓名或精確位置。`ROOT_CONFIRMED`；D 不變 |
| 東加 | TO | [Matangi Tonga：Vavaʻu 外海「sea of stone」與新島形成觀察](https://matangitonga.to/2006/11/08/tonga-volcanic-eruption-seen-yacht-crew) | 本地新聞保存船員初遇海上浮石帶、後續火山噴發／新島形成的觀察與常規地質脈絡；沒有 UAP／USO 案件表、原始航海紀錄、去識別或重用權 | 只詢問刊名、日期、題名、collection-level metadata 與權利；不抓文章、照片、船員紀錄、船位或精確位置 | `CONTROL_FIRST`；B（不計入 UAP／USO 分子） |
| 吐瓦魯 | TV | [Tuvalu Fisheries Authority：海岸海參異常沖岸調查](https://tuvalufisheries.tv/2017/03/17/a-large-number-of-lollyfish-holothuria-atra-washed-ashore/)／[機構入口](https://tuvalufisheries.tv/) | 本地漁業機構保存水域異常、現場水溫／混濁度調查與溶氧、藻類、循環／污染候選；沒有 USO／UAP 案件表、原始樣本、影像、去識別或重用權 | 只詢問刊名、日期、題名、collection-level metadata 與權利；不抓文章、照片、樣本、調查紀錄、姓名或精確位置 | `CONTROL_FIRST`；B（不計入 UAP／USO 分子） |

## 二、8 個 D 國：按語言與持有人類型排隊

下表是搜尋路由，不把「語言」誤當來源。每一群都只接受本地持有、可回溯、與題材直接相關的入口。

### 2.1 已驗本地公有根，但尚無題材命中（狀態仍為 D）

這些 URL 只降低下一輪的尋址成本：它們證實當地存在可聯絡／檢索的本地檔案或科學持有人，**沒有**證實 UAP、USO、流星或未知落物的具名館藏。因此不能升級國別覆蓋、不能接 connector，也不列入 Atlas URL 統計。

| 國家（ISO） | 本地根入口 | 目前可證實／不可證實 | 下一道門檻 |
| --- | --- | --- | --- |
| 赤道幾內亞 GQ | [Primatura：Dirección General de Archivo y Documentación](https://primatura.gob.gq/directores/direccion-general-de-archivo-y-documentacion/) | 官方頁面確認公共檔案系統、編目與建立國家歷史檔案的職責；沒有公開 catalogue、UAP／天象主題命中或資料授權 | 只詢問本地民用報刊、科學／氣象、未知落物的 finding aid 與公開 metadata；不抓文件、影像、姓名、精確座標或安全資料 |

### 2.2 其餘 D 國：按語言與持有人類型排隊

| 工作群 | 國家（ISO） | 首輪語言／索引面 | 優先找什麼 | 明確排除 |
| --- | --- | --- | --- | --- |
| 非洲葡語島嶼與南部 | 聖多美普林西比 ST | 葡萄牙語 | 國家檔案、國家圖書館數位報刊、科學／氣象機構的具名 archive | 巴西／葡萄牙案例站或葡語聚合站 |
| 非洲英語／本地語 | 甘比亞 GM | 英語；依國別補當地語 | 本地報紙／廣播 archive、民航／氣象／大學科學組織的具名記錄 | Reddit、YouTube、跨國目擊資料庫 |
| 赤道幾內亞 | 赤道幾內亞 GQ | 西班牙語／法語 | 本地官方報刊、國家檔案／圖書館與民用科學機構 | 西語全球 UAP 聚合及外國殖民檔案 |
| 亞洲：中亞／東北亞 | 北韓 KP | 韓語／俄語 | 國家檔案、國家圖書館、民用學術／天文史料 | 俄語聚合站、軍事事件、地緣政治內容 |
| 大洋洲 | 吉里巴斯 KI、密克羅尼西亞聯邦 FM、諾魯 NR、帛琉 PW | 英語＋本地語 | 先用本表第一節的 archive route；之後只找具名本地報導／official response | 區域／殖民檔案、NUFORC／UAPDrop、社群影片 |

## 四、每個新來源要存什麼（地圖可接，但不收事件）

在尚未取得書面授權前，只新增一列 `source_manifest`，欄位如下：

| 欄位 | 範例／目的 |
| --- | --- |
| `country_iso` | `FM`；只作國別路由，不推定事件位置 |
| `source_url`、`owner_name`、`source_type` | root／catalogue／local-press finding aid／official request |
| `locality_basis` | 為何可判斷為該國本地持有人 |
| `topic_evidence` | UAP／unknown-sky／unknown-underwater 的具名題名或正式回應；沒有就維持 root-only |
| `access_posture` | `INDEX_ONLY`、`ARCHIVE_REQUEST`、`CONTROL_FIRST`；不是 download permission |
| `rights_privacy_gate` | 條款、去識別、撤回、重用、重複來源尚缺哪一項 |
| `time_coverage`、`language`、`reviewed_at` | 只記 collection-level 範圍與可重現的複查時間 |
| `next_gate` | 要求 finding aid／metadata，不要求或保存原案、媒體、姓名與精確位置 |

任何能跨過上述門檻的來源，先補入 `COUNTRY_SOURCE_GAP_QUEUE_20260813_ZH.md` 與全球 atlas，再更新 A/B/C/D 帳本與離線測試。沒有跨過門檻就只留在本路由表，不下載、不計數、不畫成熱區。
