# 來源授權審查紀錄 — 2026-08-30

對 `SOURCE_ADMISSION_QUEUE_20260813_ZH.md` 中五個候選來源做授權與條款審查。

**審查方法**：只讀取各來源的**授權／條款／法律頁面**與套件中繼資料，**未接觸任何資料端點**、未下載任何事件資料、未繞過任何存取控制。所有判定附上可複驗的網址與逐字條文。

| 來源 | 判定 | 依據 |
|---|---|---|
| Global Meteor Network | **PASS** | CC BY 4.0，僅需引用 |
| NARA（美國國家檔案館） | **PASS（需逐件檢查）** | 聯邦機關產出屬公有領域；捐贈件另有限制 |
| GEIPAN／CNES | **CONDITIONAL** | 著作權全部保留；重製／抽取／衍生「formellement et strictement interdits」 |
| NUFORC | **REJECT（暫）** | 站方封鎖自動化存取；既有紀錄載明禁止未授權大量擷取 |
| UFOSINT ufo-dedup | **REJECT** | 無授權條款；專案自述不得再散布 |

---

## 1. Global Meteor Network — PASS

- 查核頁面：`https://globalmeteornetwork.org/data/`（HTTP 200）
- 逐字條文：「The data are released under the **CC BY 4.0 license**, so if you are using the data for scientific purposes, we kindly ask you to reference this web site in your work, as well as the papers in the References section.」

**判定**：全隊列中授權最乾淨的一個。CC BY 4.0 允許再散布與衍生，義務只有標示出處與引用其論文。

**待辦**：仍需完成 registry 既有的 `LOCAL_INCREMENTAL_PLAN_READY_ENDPOINT_PROBE_PENDING`（端點探測與增量計畫），以及在地圖頁腳加上 CC BY 署名與論文引用。角色為 `false_positive_control`（流星誤判對照），不是目擊事件來源。

## 2. NARA — PASS（需逐件檢查）

- 查核頁面：`https://www.archives.gov/global-pages/privacy.html`（HTTP 200）
- 逐字條文：「Generally, materials produced by Federal agencies are in the **public domain** and may be reproduced without permission.」
- 但同頁另載：「**not all materials appearing on this website are in the public domain**… items… may have been donated or obtained from individuals or organizations and **may be subject to restrictions on use**.」並聲明「we cannot confirm copyright status for any item」。

**判定**：法律面是本隊列最寬鬆的一類（美國聯邦政府作品無著作權），但**不能整批假定公有領域**：捐贈件需逐件確認，且館方明言不為個別件的著作權狀態背書。

**待辦**：`catalog.archives.gov` 的 v2 API 以本次未帶金鑰的請求回傳前端 HTML，實際接入需申請 API 金鑰並確認查詢配額。若之後要取掃描影像，須逐件記錄 use restriction 欄位。

## 3. GEIPAN／CNES — CONDITIONAL（僅限本機／教育用途，不得發布）

- 查核頁面：`https://www.cnes-geipan.fr/fr/mentions_legales`（HTTP 200）
- 逐字條文：「Tous droits de propriété intellectuelle liés au site Internet… sont la propriété du CNES」；「les droits de (i) reproduire, représenter, adapter et/ou traduire, (ii) **extraire**, ou (iii) de créer tout **travail dérivé** de tout ou partie du site Internet et/ou de contenus y afférent, sont **formellement et strictement interdits** en dehors du cadre strictement limité à l'exception de **copie privée ou à visée éducative**.」
- 強制標示：「ce document est extrait du site Internet GEIPAN. Informations protégées - Tous droits réservés © CNES (+ année publication)」
- 補充查核：`data.gouv.fr` 搜尋 `geipan` 回傳 **0 筆資料集** —— GEIPAN **不在法國開放資料平台上**，因此**沒有** Licence Ouverte／Etalab 授權可依。

**判定**：常被誤認為「法國官方開放資料」，實際是**著作權全部保留**。抽取與衍生作品原則上禁止，僅私人重製或教育用途例外，且必須逐份附上上述 © CNES 聲明。

**可做／不可做**：
- 可：本機、非公開的研究與教育用途，並在每筆紀錄顯示 © CNES 聲明。
- 不可：納入任何對外發布的版本（含先前討論的 GitHub Pages）。要發布必須先取得 CNES 書面授權（僅有聯絡表單 `/contactez-nous`，無自助授權管道）。

**維護發現**：registry 內登記的 CSV 網址 `https://www.cnes-geipan.fr/en/actualites/mise-a-jour-csv` **已失效**（站方回傳 404 頁面）。即使授權通過，該端點也需重新定位。

## 4. NUFORC — REJECT（暫，待書面授權）

- 查核：`https://nuforc.org/terms-of-use/`、`/about/`、站台首頁三個網址在標示身分的請求下**一律回傳 HTTP 403**。
- 既有紀錄：`SOURCE_ADMISSION_QUEUE_20260813_ZH.md` 已載明 NUFORC 原站「禁止未經許可的大量擷取」，並已將其 Hugging Face／ShadowBroker 鏡像列為 `REJECTED_AS_INGESTION`。

**判定**：站方以技術手段封鎖自動化存取，這本身就是明示的不同意。**未嘗試繞過**（不偽裝瀏覽器指紋、不改走鏡像）。要接入只有一條路：直接向 NUFORC 取得書面授權。鏡像路徑維持既有的 REJECTED 判定不變。

## 5. UFOSINT `ufo-dedup` — REJECT

- 查核：資料實際發布於**另一個 repo** `UFOSINT/ufosint-explorer`（registry 的下載網址指向該處），而非 `ufo-dedup`。兩個 repo 的 GitHub API 皆回傳 `license: null`，`main`／`master` 分支皆**無 LICENSE 檔**（HTTP 404）。
- `ufosint-explorer` 確有 4 個 release，`ufo_public.db` 為 release 資產，**實測 628.1 MB**（隊列文件記載的 553 MB 已過時）。**有發布不等於有授權。**
- 專案自述（`data/raw/README.md`）逐字：「**None of the actual data files are committed to this repo** — they're either too large, paid/subscription-gated, or have **licensing restrictions that prevent redistribution**.」「**We can't redistribute these files**.」
- 其上游逐一標註：NUFORC「NUFORC's terms govern redistribution」；MUFON「**MUFON owns the case database. Confirm membership terms before any redistribution.**」；UFOCAT「CUFOS-owned… verify before redistribution」。
- 專案自身在 README 中亦區分「legally-safe, non-copyrighted features」與原始內容，顯示其自知原始文本受著作權保護。

**判定**：無授權即為著作權全部保留（兩個 repo 皆然）；且即使取得該 DB，其構成來源（NUFORC／MUFON／UFOCAT）各自禁止或限制再散布，本專案逐筆發布事件資料的形態無法被涵蓋。維持 `OPEN_BATCH_REVIEW` 之外，應降級為 **REJECTED_AS_INGESTION**，與既有的 ShadowBroker 鏡像判定一致。

---

## 對隊列的具體影響

1. **UFOSINT 從候選名單移除** —— 這推翻了「最快讓地圖點數翻倍」的路徑。授權缺口不是流程未走完，是根本不存在授權。
2. **GEIPAN 從「快速候選」降為「需授權談判」** —— 本機研究可做，但與公開發布互斥，必須先決定這個專案要不要對外。
3. **GMN 是唯一可直接推進的來源** —— 但它補的是天文控制層，不是目擊事件。
4. **NARA 是取得影像資料最實際的路徑** —— 法律面最寬鬆，卡點是技術（API 金鑰與連接器），不是權利。

## 對「目擊事件」母庫的結論

本次審查涵蓋的三個第一手／聚合目擊來源（NUFORC、UFOSINT、GEIPAN）**沒有任何一個可在公開發布的前提下接入**。目擊事件層要成長，只剩兩條路：

- 逐一向來源持有者取得書面授權（NUFORC、CNES、MUFON 皆需個別談判）；
- 或改採本身即為公有領域的政府檔案（NARA、war.gov、巴西 SIAN、阿根廷 CIAE、智利 SEFAA），代價是這些多為文件掃描件而非結構化事件表，需要額外的擷取與正規化工作。

---

## 審查方法已框架化

本次審查的每一步都已抽成可重跑的工具 `source_rights_review.py`，避免下一個來源又靠一次性指令臨時判斷：

- `targets` — 離線列出各來源已宣告的審查目標與目前覆蓋率（目前 **6/23**）。
- `probe` — **只抓已宣告的授權／條款／套件中繼資料頁**，逐次寫出證據收據（HTTP 狀態、位元組數、內容 SHA-256、逐字條文）到 `data/rights_review/<source_id>/`。
- `report` — 把裁決與其證據收據並列輸出。

**結構性安全保證**：`assert_review_target()` 會比對 registry 中每個來源的資料端點，**拒絕抓取任何資料端點或其下層路徑**，並拒絕非 https。因此這支工具在設計上不可能被當成爬蟲使用，即使被指向資料網址也一樣。已有測試覆蓋此性質。

**裁決仍屬人的決定**：工具只負責蒐證與標記明顯訊號（`no_declared_license`、`access_blocked`），不會自行判定是否准入。

**條款排序**依決定性排列（限制條文優先於授權提及），因為審查者要先看到禁止或授予再利用的那一句。

`source_rights_targets.json` 記錄各來源的審查目標與裁決；尚未宣告審查目標的 17 個來源會在 `targets` 輸出的 `registered_without_review_targets` 中列出，覆蓋缺口不會被隱藏。
