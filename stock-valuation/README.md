# 台股估值實驗室

以 2881 富邦金固定資料驗證可解釋的 P/E、P/B 與情境估值 MVP。現階段不連接即時資料，也不提供買賣建議。

## 執行

最快的預覽方式不需要安裝任何套件：

```powershell
cd stock-valuation
python run_local.py
```

接著用瀏覽器開啟 http://127.0.0.1:8000 。若要使用 FastAPI 開發伺服器：

```powershell
cd stock-valuation
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

## 測試

```powershell
python -m pytest
```

## API

- `GET /api/stocks/2881/snapshot`
- `GET /api/stocks/2881/history`
- `GET /api/stocks/2881/valuation`
- `POST /api/valuation`：可覆寫預估 EPS、BPS、估值權重與情境參數

資料層與估值數學已分離。新增即時來源時，請實作 `StockDataProvider`，不要將抓取邏輯放入估值模組。
