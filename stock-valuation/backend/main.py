from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data.providers import FixtureProvider
from .models.schemas import HistoricalPoint, ValuationRequest, ValuationResult
from .valuation.valuation_engine import calculate

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
provider = FixtureProvider()
app = FastAPI(title="台股估值實驗室 API", version="1.0.0")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


def require_ticker(ticker: str) -> str:
    value = ticker.strip()
    if value != "2881":
        raise HTTPException(status_code=404, detail="MVP 目前僅提供 2881 富邦金固定測試資料")
    return value


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/stocks/{ticker}/snapshot")
def snapshot(ticker: str):
    return provider.get_snapshot(require_ticker(ticker))


@app.get("/api/stocks/{ticker}/history", response_model=list[HistoricalPoint])
def history(ticker: str):
    return provider.get_history(require_ticker(ticker))


@app.get("/api/stocks/{ticker}/valuation", response_model=ValuationResult)
def valuation(ticker: str):
    ticker = require_ticker(ticker)
    return calculate(provider.get_snapshot(ticker), provider.get_history(ticker), provider.get_forecasts(ticker), {})


@app.post("/api/valuation", response_model=ValuationResult)
def custom_valuation(request: ValuationRequest):
    ticker = require_ticker(request.ticker)
    return calculate(
        provider.get_snapshot(ticker),
        provider.get_history(ticker),
        provider.get_forecasts(ticker),
        request.model_dump(),
    )

