from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data.providers import FixtureProvider, LiveStockProvider
from .models.schemas import HistoricalPoint, ValuationRequest, ValuationResult
from .valuation.valuation_engine import calculate

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
provider = LiveStockProvider()
fixture_provider = FixtureProvider()
app = FastAPI(title="台股估值實驗室 API", version="1.0.0")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


def require_ticker(ticker: str) -> str:
    try:
        return provider.resolve(ticker)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def stock_data(query: str):
    ticker = require_ticker(query)
    try:
        return ticker, provider.get_snapshot(ticker), provider.get_history(ticker), provider.get_forecasts(ticker)
    except Exception as error:
        if ticker == "2881":
            return ticker, fixture_provider.get_snapshot(ticker), fixture_provider.get_history(ticker), fixture_provider.get_forecasts(ticker)
        raise HTTPException(status_code=422, detail=f"{ticker} 資料不足，暫時無法完成估值：{error}") from error


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/stocks/{ticker}/snapshot")
def snapshot(ticker: str):
    return stock_data(ticker)[1]


@app.get("/api/stocks/{ticker}/history", response_model=list[HistoricalPoint])
def history(ticker: str):
    return stock_data(ticker)[2]


@app.get("/api/stocks/{ticker}/valuation", response_model=ValuationResult)
def valuation(ticker: str):
    _, snapshot_data, history_data, forecast_data = stock_data(ticker)
    return calculate(snapshot_data, history_data, forecast_data, {})


@app.post("/api/valuation", response_model=ValuationResult)
def custom_valuation(request: ValuationRequest):
    ticker, snapshot_data, history_data, forecast_data = stock_data(request.ticker)
    return calculate(
        snapshot_data,
        history_data,
        forecast_data,
        request.model_dump(),
    )
