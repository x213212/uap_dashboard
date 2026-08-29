# 本機資料完整性稽核（2026-08-13）

本報告只核對已存在於 `uap_lab/data/` 的 receipt 和 gzip 檔；**沒有發出網路請求，沒有修改或刪除資料。**

執行命令：

```bash
python3 uap_lab/audit_data.py audit
```

## 實測結果

| 項目 | 結果 |
| --- | ---: |
| 有效 receipt | 5 |
| hash／壓縮／canonical 計數錯誤 | 0 |
| 歷史 canonical row versions | 29,331 |
| 以 `source_id + source_record_id` 去重的目前 record | 29,322 |

| 來源 | 歷史 row versions | 唯一 record |
| --- | ---: | ---: |
| UAPDrop | 28,314 | 28,314 |
| UAP Observatory | 118 | 118 |
| NASA CNEOS fireballs | 881 | 881 |
| NASA Horizons 九大天體 | 18 | **9** |

## 九大行星控制組

2026-08-13 的本機 canonical receipt 各自完整包含：Mercury、Venus、Earth、Mars、Jupiter、Saturn、Uranus、Neptune、Pluto。稽核器確認兩個同日 snapshot 都是完整 9 顆，故保留它們作不可變取得證據，但標出同日重複警告。

這不是 18 顆天體，也不會成為 18 個現在地圖控制點：地圖層以 source record identity 選最新版本，故目前九大天體控制組仍是 **9**。

## 稽核保證與邊界

- 每個 raw gzip：檔案大小、壓縮 SHA-256、解壓後大小、原始 SHA-256 都重算。
- canonical JSONL gzip：同樣重算雜湊，並驗證 JSON 行數與 receipt 記錄數、每行 `source_id` 一致。
- 稽核器拒絕 receipt 的絕對路徑、`..` traversal、symlink artifact、無效 gzip 和超出安全上限的壓縮／解壓檔。
- 它只驗資料保全與計數，不宣稱目擊內容或「未解釋」狀態為外星生命證據。
