"""純 Python 版：更新金融股股利與殖利率 Excel 報表。

直接在 Spyder 執行本檔即可；不需要 Microsoft Excel、Node.js 或額外 Python 套件。
資料來源：Goodinfo! 台灣股市資訊網。請遵守其服務條款並避免頻繁更新。
"""
from __future__ import annotations

import html
import json
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs" / "financial_dividend" / "台灣金融股_股利殖利率.xlsx"
SOURCE_BASE = "https://goodinfo.tw/tw/StockDividendPolicy.asp?STOCK_ID="  # 僅保留供舊離線資料註記
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"
FINMIND_SOURCE = "https://finmind.github.io/tutor/TaiwanMarket/Fundamental/"
STOCKS = (("2891", "中信金"), ("5880", "合庫金"), ("2880", "華南金"))

# 欄位：發放年、所屬年、現金股利、股票股利、除息前年價、年均價、參考現價。
FALLBACK = {
    "2891": [[2026,2025,2.5,0,69.9,56.9,63],[2025,2024,2.3,0,43.85,41.9,50.2],[2024,2023,1.8,0,40.2,34.4,39.1],[2023,2022,1,0,26.15,24.3,28.35],[2022,2021,1.25,0,23.45,24.7,22.1],[2021,2020,1.05,0,22.8,22.5,25.95],[2020,2019,1,0,20.9,19.8,19.7],[2019,2018,1,0,21.6,21,22.4],[2018,2017,1.08,0,21.5,21.3,20.2],[2017,2016,1,0,20.7,19.2,20.5],[2016,2015,0.81,0.8,18.4,17,17.65],[2015,2014,0.81,0.81,23.95,20.4,16.9],[2014,2013,0.38,0.37,20.05,20.1,20.55],[2013,2012,0.71,0.7,19.25,18.6,20.35],[2012,2011,0.4,0.88,17.3,17.8,17.15]],
    "5880": [[2026,2025,0.8,0.25,25.15,23.6,25.15],[2025,2024,0.7,0.3,25.95,24.4,24.3],[2024,2023,0.65,0.35,26.45,25.8,24.3],[2023,2022,0.5,0.5,29.35,26.8,26.7],[2022,2021,1,0.3,28.5,26.9,26],[2021,2020,0.85,0.2,22.15,21.7,25.45],[2020,2019,0.85,0.3,21.85,20.2,20.35],[2019,2018,0.75,0.3,20.7,20.1,20.75],[2018,2017,0.75,0.3,18.9,17.7,17.65],[2017,2016,0.75,0.3,16.45,15.7,16.6],[2016,2015,0.3,0.7,15.15,14.1,14.05],[2015,2014,0.5,0.5,15.65,15.3,13.75],[2014,2013,0.5,0.5,17.45,16.5,16.3],[2013,2012,0.4,0.6,16.95,16.6,16.3],[2012,2011,0.5,0.5,18.3,17.2,16.35]],
}


def clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?\s*>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("—", "-").split())


def number(value: str) -> float | None:
    value = value.replace(",", "").replace("%", "").strip()
    if value in {"", "-", "--"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def decode_page(raw: bytes, content_type: str) -> str:
    """依 HTTP / HTML 宣告解碼，避免 UTF-8 / Big5 造成表格名稱找不到。"""
    candidates = re.findall(r"charset=([\w-]+)", content_type, flags=re.I)
    head = raw[:2000].decode("latin-1", errors="ignore")
    candidates += re.findall(r"charset=[\"']?([\w-]+)", head, flags=re.I)
    for encoding in candidates + ["utf-8", "cp950", "big5"]:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def parse_rows(page: str, stock_id: str, stock_name: str) -> list[dict]:
    """從明細標題之後取年度列；可避開 Goodinfo 網頁的巢狀 table。"""
    marker = "歷年股利分派詳細資料"
    start = page.find(marker)
    if start < 0:
        title = clean_html(re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S).group(1)) if re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S) else "無標題"
        raise ValueError(f"回應不是預期股利明細頁（頁面標題：{title}）")
    rows: list[dict] = []
    for tr in re.findall(r"<tr\b[^>]*>([\s\S]*?)</tr>", page[start:], flags=re.I):
        cells = [clean_html(cell) for cell in re.findall(r"<t[dh]\b[^>]*>([\s\S]*?)</t[dh]>", tr, flags=re.I)]
        if len(cells) < 22 or not re.fullmatch(r"20\d{2}", cells[0]):
            continue
        rows.append({"stockId": stock_id, "stockName": stock_name, "issueYear": int(cells[0]), "fiscalYear": int(cells[1]),
                     "cashDividend": number(cells[4]), "stockDividend": number(cells[7]), "totalDividend": number(cells[8]),
                     "exDate": cells[11], "beforeExPrice": number(cells[12]), "exCashYield": number(cells[13]),
                     "averagePrice": number(cells[14]), "averageCashYield": number(cells[15]), "currentPrice": number(cells[16]),
                     "currentCashYield": number(cells[17]), "sourceUrl": f"{SOURCE_BASE}{stock_id}"})
    if not rows:
        raise ValueError("未找到可辨識的年度資料列")
    return rows


def fetch_rows(stock_id: str, stock_name: str) -> list[dict]:
    """使用 FinMind API 取得股利、除權息結果及每日收盤價，不再解析 Goodinfo 網頁。"""
    def api_data(dataset: str) -> list[dict]:
        query = urlencode({"dataset": dataset, "data_id": stock_id, "start_date": "2005-01-01"})
        request = Request(f"{FINMIND_API}?{query}", headers={"User-Agent": "FinanceDividendReport/2.0"})
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError(payload.get("msg", f"FinMind 未回傳 {dataset} 資料"))
        return data

    def amount(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    dividends = api_data("TaiwanStockDividend")
    dividend_results = {item.get("date"): item for item in api_data("TaiwanStockDividendResult")}
    prices = api_data("TaiwanStockPrice")
    stock_info = api_data("TaiwanStockInfo")
    display_name = stock_info[0].get("stock_name") or stock_name
    latest_price = amount(prices[-1].get("close"))
    yearly_prices: dict[int, list[float]] = {}
    for price in prices:
        try:
            yearly_prices.setdefault(int(price["date"][:4]), []).append(amount(price.get("close")))
        except (KeyError, TypeError, ValueError):
            continue

    grouped: dict[tuple[int, int], dict] = {}
    for dividend in dividends:
        ex_date = dividend.get("CashExDividendTradingDate") or dividend.get("StockExDividendTradingDate") or dividend.get("date")
        if not isinstance(ex_date, str) or len(ex_date) < 4:
            continue
        issue_year = int(ex_date[:4])
        year_text = str(dividend.get("year", ""))
        match = re.search(r"\d+", year_text)
        fiscal = int(match.group()) + 1911 if match and int(match.group()) < 1911 else (int(match.group()) if match else issue_year - 1)
        record = grouped.setdefault((issue_year, fiscal), {"cash": 0.0, "stock": 0.0, "exDate": ex_date})
        record["cash"] += amount(dividend.get("CashEarningsDistribution")) + amount(dividend.get("CashStatutorySurplus"))
        record["stock"] += amount(dividend.get("StockEarningsDistribution")) + amount(dividend.get("StockStatutorySurplus"))
        record["exDate"] = max(record["exDate"], ex_date)

    rows: list[dict] = []
    for (issue_year, fiscal), record in grouped.items():
        if record["cash"] == 0 and record["stock"] == 0:
            continue
        before_price = amount(dividend_results.get(record["exDate"], {}).get("before_price")) or None
        annual_prices = [value for value in yearly_prices.get(issue_year, []) if value]
        average_price = sum(annual_prices) / len(annual_prices) if annual_prices else None
        rows.append({"stockId": stock_id, "stockName": display_name, "issueYear": issue_year, "fiscalYear": fiscal,
                     "cashDividend": record["cash"], "stockDividend": record["stock"], "totalDividend": record["cash"] + record["stock"],
                     "exDate": record["exDate"], "beforeExPrice": before_price, "exCashYield": record["cash"] / before_price * 100 if before_price else None,
                     "averagePrice": average_price, "averageCashYield": record["cash"] / average_price * 100 if average_price else None,
                     "currentPrice": latest_price or None, "currentCashYield": record["cash"] / latest_price * 100 if latest_price else None,
                     "sourceUrl": FINMIND_SOURCE})
    if not rows:
        raise ValueError("FinMind 沒有可用股利資料")
    return rows
    
def fallback_rows(stock_id: str, stock_name: str) -> list[dict]:
    result = []
    for issue, fiscal, cash, stock, before, average, current in FALLBACK.get(stock_id, []):
        result.append({"stockId": stock_id, "stockName": stock_name, "issueYear": issue, "fiscalYear": fiscal,
                       "cashDividend": cash, "stockDividend": stock, "totalDividend": cash + stock, "exDate": "",
                       "beforeExPrice": before, "exCashYield": cash / before * 100, "averagePrice": average,
                       "averageCashYield": cash / average * 100, "currentPrice": current, "currentCashYield": cash / current * 100,
                       "sourceUrl": f"{SOURCE_BASE}{stock_id}"})
    return result


def col(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell(ref: str, value, style: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'


def sheet_xml(rows: list[list], widths: list[float], merges: list[str] = (), heights: dict[int, float] | None = None) -> str:
    heights = heights or {}
    body = []
    for row_num, row in enumerate(rows, 1):
        cells = "".join(cell(f"{col(column)}{row_num}", value, style) for column, (value, style) in enumerate(row, 1) if value is not None)
        height = f' ht="{heights[row_num]}" customHeight="1"' if row_num in heights else ""
        body.append(f'<row r="{row_num}"{height}>{cells}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>' for i, width in enumerate(widths, 1))
    merge_xml = "" if not merges else "<mergeCells count=\"%d\">%s</mergeCells>" % (len(merges), "".join(f'<mergeCell ref="{m}"/>' for m in merges))
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews><cols>{cols}</cols><sheetData>{"".join(body)}</sheetData>{merge_xml}</worksheet>'


STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="2"><numFmt numFmtId="164" formatCode="0.00"/><numFmt numFmtId="165" formatCode="0.0%"/></numFmts><fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><sz val="16"/><b/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17365D"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/></patternFill></fill></fills><borders count="2"><border><left/><right/><top/><bottom/></border><border><left style="thin"><color rgb="FFD9E2F3"/></left><right style="thin"><color rgb="FFD9E2F3"/></right><top style="thin"><color rgb="FFD9E2F3"/></top><bottom style="thin"><color rgb="FFD9E2F3"/></bottom></border></borders><cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="2" fillId="3" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="1" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="1" applyNumberFormat="1" applyBorder="1"/><xf numFmtId="0" fontId="0" fillId="4" borderId="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="1" applyBorder="1"/></cellXfs></styleSheet>'''


def create_workbook(rows: list[dict], offline: set[str]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda item: (item["stockId"], -item["issueYear"]))
    summary = [[("台灣金融股｜股利與殖利率追蹤", 1)] + [(None, 0)] * 8, [("更新時間", 0), (datetime.now().strftime("%Y-%m-%d %H:%M"), 0)] + [(None, 0)] * 7, [(None, 0)] * 9,
               [(x, 2) for x in ["代號", "公司", "最新發放年", "最新現金股利", "參考現價", "目前預估殖利率", "近 5 年平均現金殖利率", "資料狀態", "資料來源"]]]
    for stock_id, stock_name in STOCKS:
        stock_rows = [item for item in rows if item["stockId"] == stock_id]
        if not stock_rows:
            continue
        latest = max(stock_rows, key=lambda item: item["issueYear"])
        five_year = [item["averageCashYield"] / 100 for item in stock_rows if item["issueYear"] >= latest["issueYear"] - 4 and item["averageCashYield"] is not None]
        summary.append([(stock_id, 6), (stock_name, 6), (latest["issueYear"], 6), (latest["cashDividend"], 3), (latest["currentPrice"], 3), (latest["cashDividend"] / latest["currentPrice"] if latest["currentPrice"] else None, 4), (sum(five_year) / len(five_year) if five_year else None, 4), ("離線初始資料" if stock_id in offline else "已更新", 6), (latest["sourceUrl"], 6)])
    summary += [[(None, 0)] * 9] * 4
    summary.append([("預估殖利率 = 最新已公告「現金股利」÷ 參考現價。此為推估值，非保證收益，且不包含股票股利。", 5)] + [(None, 0)] * 8)

    history_headers = ["代號", "公司", "股利發放年度", "股利所屬年度", "現金股利", "股票股利", "股利合計", "除權息日", "除息前年價", "除息現金殖利率", "全年平均價", "參考現價", "目前現金殖利率", "年均價現金殖利率", "資料來源", "備註"]
    history = [[(header, 2) for header in history_headers]]
    for item in rows:
        history.append([(item["stockId"], 6), (item["stockName"], 6), (item["issueYear"], 6), (item["fiscalYear"], 6), (item["cashDividend"], 3), (item["stockDividend"], 3), (item["totalDividend"], 3), (item["exDate"], 6), (item["beforeExPrice"], 3), (item["exCashYield"] / 100 if item["exCashYield"] is not None else None, 4), (item["averagePrice"], 3), (item["currentPrice"], 3), (item["currentCashYield"] / 100 if item["currentCashYield"] is not None else None, 4), (item["averageCashYield"] / 100 if item["averageCashYield"] is not None else None, 4), (item["sourceUrl"], 6), ("", 6)])
    source = [[("資料來源與使用說明", 1)] + [(None, 0)] * 3, [(None, 0)] * 4, [(x, 2) for x in ["項目", "內容", "來源", "備註"]],
              [("歷年股利／歷史殖利率", 6), ("FinMind 股利政策、除權息結果與每日收盤價 API", 6), (FINMIND_SOURCE, 6), ("股利發放年度依除權息日認定。", 6)],
              [("參考現價", 6), ("FinMind 每日收盤價資料中的最新 close", 6), (FINMIND_SOURCE, 6), ("非即時報價；交易前請另行確認。", 6)],
              [("預估殖利率", 6), ("最新已公告現金股利 ÷ 參考現價", 6), ("本程式計算", 6), ("不包含股票股利；非保證收益率。", 6)],
              [("離線初始資料", 6), ("無法連線或 API 回傳失敗時，使用內建歷史快照", 6), ("內建資料（2026-07-17）", 6), ("狀態欄會標示「離線初始資料」。", 6)]]
    sheets = [sheet_xml(summary, [12,12,13,15,13,18,22,16,60], ["A1:I1", "A11:I13"], {1: 24, 11: 36}), sheet_xml(history, [10,12,14,14,12,12,12,14,13,15,13,13,15,16,62,18]), sheet_xml(source, [22,44,64,42], ["A1:D1"], {1: 24})]
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="總覽" sheetId="1" r:id="rId1"/><sheet name="歷年股利" sheetId="2" r:id="rId2"/><sheet name="資料來源與說明" sheetId="3" r:id="rId3"/></sheets></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as book:
        book.writestr("[Content_Types].xml", content_types); book.writestr("_rels/.rels", rels); book.writestr("xl/workbook.xml", workbook); book.writestr("xl/_rels/workbook.xml.rels", workbook_rels); book.writestr("xl/styles.xml", STYLES)
        for index, xml in enumerate(sheets, 1): book.writestr(f"xl/worksheets/sheet{index}.xml", xml)


def main() -> None:
    all_rows: list[dict] = []
    offline: set[str] = set()
    for stock_id, stock_name in STOCKS:
        try:
            records = fetch_rows(stock_id, stock_name)
            print(f"{stock_id} {stock_name}：已抓取 {len(records)} 筆年度資料")
        except (URLError, TimeoutError, ValueError, OSError) as error:
            records = fallback_rows(stock_id, stock_name); offline.add(stock_id)
            print(f"{stock_id} {stock_name}：抓取失敗（{error}）；改用離線初始資料。")
        all_rows.extend(records)
        time.sleep(1.0)
    create_workbook(all_rows, offline)
    print(f"已建立：{OUTPUT}")


if __name__ == "__main__":
    main()
    
