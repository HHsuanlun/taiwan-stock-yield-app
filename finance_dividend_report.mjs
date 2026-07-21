/**
 * 台灣金融股歷年股利與殖利率報表
 * 資料來源：Goodinfo! 台灣股市資訊網
 *
 * 執行：node finance_dividend_report.mjs
 * 產出：outputs/financial_dividend/台灣金融股_股利殖利率.xlsx
 *
 * 注意：請遵守資料來源的服務條款並控制更新頻率；本程式每一檔間隔 1.5 秒。
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(ROOT, "outputs", "financial_dividend");
const OUT_FILE = path.join(OUTPUT_DIR, "台灣金融股_股利殖利率.xlsx");

// 可自行增減；此版本先放四檔具代表性的金融股。
const STOCKS = [
  { id: "2891", name: "中信金" },
  { id: "5880", name: "合庫金" },
];
const SOURCE_BASE = "https://goodinfo.tw/tw/StockDividendPolicy.asp?STOCK_ID=";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// 網路受限時仍可建立可檢視的初始報表；下次可連網執行時會以即時擷取資料取代。
// 欄位：發放年、所屬年、現金股利、股票股利、除息前年價、年均價、成交價。
const FALLBACK = {
  "2891": [[2026,2025,2.5,0,69.9,56.9,63],[2025,2024,2.3,0,43.85,41.9,50.2],[2024,2023,1.8,0,40.2,34.4,39.1],[2023,2022,1,0,26.15,24.3,28.35],[2022,2021,1.25,0,23.45,24.7,22.1],[2021,2020,1.05,0,22.8,22.5,25.95],[2020,2019,1,0,20.9,19.8,19.7],[2019,2018,1,0,21.6,21,22.4],[2018,2017,1.08,0,21.5,21.3,20.2],[2017,2016,1,0,20.7,19.2,20.5],[2016,2015,0.81,0.8,18.4,17,17.65],[2015,2014,0.81,0.81,23.95,20.4,16.9],[2014,2013,0.38,0.37,20.05,20.1,20.55],[2013,2012,0.71,0.7,19.25,18.6,20.35],[2012,2011,0.4,0.88,17.3,17.8,17.15]],
  "5880": [[2026,2025,0.8,0.25,25.15,23.6,25.15],[2025,2024,0.7,0.3,25.95,24.4,24.3],[2024,2023,0.65,0.35,26.45,25.8,24.3],[2023,2022,0.5,0.5,29.35,26.8,26.7],[2022,2021,1,0.3,28.5,26.9,26],[2021,2020,0.85,0.2,22.15,21.7,25.45],[2020,2019,0.85,0.3,21.85,20.2,20.35],[2019,2018,0.75,0.3,20.7,20.1,20.75],[2018,2017,0.75,0.3,18.9,17.7,17.65],[2017,2016,0.75,0.3,16.45,15.7,16.6],[2016,2015,0.3,0.7,15.15,14.1,14.05],[2015,2014,0.5,0.5,15.65,15.3,13.75],[2014,2013,0.5,0.5,17.45,16.5,16.3],[2013,2012,0.4,0.6,16.95,16.6,16.3],[2012,2011,0.5,0.5,18.3,17.2,16.35]],
};
function fallbackRows(stock) {
  return FALLBACK[stock.id].map(([issueYear, fiscalYear, cashDividend, stockDividend, beforeExPrice, averagePrice, currentPrice]) => ({
    stockId: stock.id, stockName: stock.name, issueYear, fiscalYear, cashDividend, stockDividend,
    totalDividend: cashDividend + stockDividend, exDate: "", beforeExPrice,
    exCashYield: beforeExPrice ? cashDividend / beforeExPrice * 100 : null, averagePrice,
    averageCashYield: averagePrice ? cashDividend / averagePrice * 100 : null, currentPrice,
    currentCashYield: currentPrice ? cashDividend / currentPrice * 100 : null,
    highPrice: null, highCashYield: null, lowPrice: null, lowCashYield: null,
    sourceUrl: `${SOURCE_BASE}${stock.id}`,
  }));
}

function cleanHtml(value) {
  return value
    .replace(/<br\s*\/?\s*>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&mdash;|&#8212;/gi, "-")
    .replace(/\s+/g, " ")
    .trim();
}
function numberOrNull(value) {
  const normalized = String(value).replace(/,/g, "").trim();
  if (!normalized || normalized === "-" || normalized === "--") return null;
  const n = Number(normalized.replace(/%$/, ""));
  return Number.isFinite(n) ? n : null;
}

function parseDetailRows(html, stock) {
  const tables = [...html.matchAll(/<table\b[^>]*>[\s\S]*?<\/table>/gi)].map((m) => m[0]);
  const detail = tables.find((table) => cleanHtml(table).includes("歷年股利分派詳細資料"));
  if (!detail) throw new Error("找不到『歷年股利分派詳細資料』表格，可能是網站版面已調整。");

  const results = [];
  for (const tr of detail.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...tr[1].matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)].map((m) => cleanHtml(m[1]));
    if (cells.length < 20 || !/^20\d{2}$/.test(cells[0])) continue;
    // Goodinfo 明細欄位：發放年、所屬年、現金(盈餘/公積/合計)、股票(盈餘/公積/合計)、股利合計、...
    results.push({
      stockId: stock.id, stockName: stock.name, issueYear: Number(cells[0]), fiscalYear: Number(cells[1]),
      cashDividend: numberOrNull(cells[4]), stockDividend: numberOrNull(cells[7]), totalDividend: numberOrNull(cells[8]),
      exDate: cells[11] || "", beforeExPrice: numberOrNull(cells[12]), exCashYield: numberOrNull(cells[13]),
      averagePrice: numberOrNull(cells[14]), averageCashYield: numberOrNull(cells[15]),
      currentPrice: numberOrNull(cells[16]), currentCashYield: numberOrNull(cells[17]),
      highPrice: numberOrNull(cells[18]), highCashYield: numberOrNull(cells[19]),
      lowPrice: numberOrNull(cells[20]), lowCashYield: numberOrNull(cells[21]),
      sourceUrl: `${SOURCE_BASE}${stock.id}`,
    });
  }
  if (!results.length) throw new Error("明細表中沒有可辨識的年度資料。");
  return results;
}

async function fetchStock(stock) {
  const aborter = new AbortController();
  const timeout = setTimeout(() => aborter.abort(), 12000);
  const response = await fetch(`${SOURCE_BASE}${stock.id}`, {
    headers: { "User-Agent": "Mozilla/5.0 (compatible; FinanceDividendReport/1.0)" },
    signal: aborter.signal,
  });
  clearTimeout(timeout);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return parseDetailRows(await response.text(), stock);
}

function style(sheet, range, fill, color = "#FFFFFF") {
  sheet.getRange(range).format = { fill, font: { bold: true, color }, verticalAlignment: "center" };
}

async function buildWorkbook(rows, runAt, failures) {
  const wb = Workbook.create();
  const summary = wb.worksheets.add("總覽");
  const history = wb.worksheets.add("歷年股利");
  const sources = wb.worksheets.add("資料來源與說明");
  for (const sheet of [summary, history, sources]) sheet.showGridLines = false;

  summary.getRange("A1:I1").merge();
  summary.getRange("A1").values = [["台灣金融股｜股利與殖利率追蹤"]];
  style(summary, "A1:I1", "#17365D"); summary.getRange("A1:I1").format.font = { bold: true, color: "#FFFFFF", size: 16 };
  summary.getRange("A2").values = [["更新時間"]]; summary.getRange("B2").values = [[runAt]]; summary.getRange("B2").format.numberFormat = "yyyy-mm-dd hh:mm";
  summary.getRange("A4:I4").values = [["代號", "公司", "最新發放年", "最新現金股利", "參考現價", "目前預估殖利率", "近 5 年平均現金殖利率", "資料狀態", "Goodinfo 來源"]];
  style(summary, "A4:I4", "#1F4E78");
  const names = [...new Map(rows.map((r) => [r.stockId, r.stockName])).entries()];
  const latestIssueYear = new Map(names.map(([id]) => [id, Math.max(...rows.filter((r) => r.stockId === id).map((r) => r.issueYear))]));
  const output = names.map(([id, name], i) => {
    const r = i + 5;
    return [id, name, latestIssueYear.get(id), `=SUMIFS('歷年股利'!$E$2:$E$200,'歷年股利'!$A$2:$A$200,A${r},'歷年股利'!$C$2:$C$200,C${r})`, `=SUMIFS('歷年股利'!$L$2:$L$200,'歷年股利'!$A$2:$A$200,A${r},'歷年股利'!$C$2:$C$200,C${r})`, `=IFERROR(D${r}/E${r},"")`, `=IFERROR(SUMIFS('歷年股利'!$N$2:$N$200,'歷年股利'!$A$2:$A$200,A${r},'歷年股利'!$C$2:$C$200,">="&C${r}-4)/COUNTIFS('歷年股利'!$A$2:$A$200,A${r},'歷年股利'!$C$2:$C$200,">="&C${r}-4),"")`, failures.includes(id) ? "離線初始資料" : "已更新", `${SOURCE_BASE}${id}`];
  });
  if (output.length) summary.getRange(`A5:I${4 + output.length}`).formulas = output.map((r) => r.map((x, i) => (i === 0 || i === 1 || i === 2 || i === 7 || i === 8 ? null : x)));
  // 將非公式欄補入值，保持公式與資料型態正確。
  output.forEach((r, i) => summary.getRange(`A${i + 5}:C${i + 5}`).values = [[r[0], r[1], r[2]]]);
  output.forEach((r, i) => summary.getRange(`H${i + 5}:I${i + 5}`).values = [[r[7], r[8]]]);
  summary.getRange(`D5:G${4 + output.length}`).format.numberFormat = "0.00;[Red](0.00);-";
  summary.getRange(`F5:G${4 + output.length}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  summary.getRange(`A4:I${4 + output.length}`).format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
  summary.getRange("A11:I13").merge(); summary.getRange("A11").values = [["預估殖利率 = 最新已公告「現金股利」÷ 參考現價。它是依最新公告股利與抓取當下價格的推估，非公司保證、亦不含股票股利；請於交易前自行確認除權息及公告。"]];
  summary.getRange("A11:I13").format = { fill: "#FFF2CC", wrapText: true, verticalAlignment: "center", borders: { preset: "outside", style: "thin", color: "#C9B458" } };
  summary.freezePanes.freezeRows(4);
  [12, 12, 13, 15, 13, 18, 22, 16, 60].forEach((w, i) => summary.getRangeByIndexes(0, i, 1, 1).format.columnWidth = w);

  history.getRange("A1:P1").values = [["代號", "公司", "股利發放年度", "股利所屬年度", "現金股利", "股票股利", "股利合計", "除權息日", "除息前年價", "除息現金殖利率", "全年平均價", "參考現價", "目前現金殖利率", "年均價現金殖利率", "資料來源", "備註"]];
  style(history, "A1:P1", "#1F4E78");
  const values = rows.sort((a, b) => a.stockId.localeCompare(b.stockId) || b.issueYear - a.issueYear).map((r) => [r.stockId, r.stockName, r.issueYear, r.fiscalYear, r.cashDividend, r.stockDividend, r.totalDividend, r.exDate, r.beforeExPrice, r.exCashYield == null ? null : r.exCashYield / 100, r.averagePrice, r.currentPrice, r.currentCashYield == null ? null : r.currentCashYield / 100, r.averageCashYield == null ? null : r.averageCashYield / 100, r.sourceUrl, ""]);
  if (values.length) history.getRange(`A2:P${values.length + 1}`).values = values;
  history.getRange(`E2:G${values.length + 1}`).format.numberFormat = "0.00;[Red](0.00);-";
  history.getRange(`I2:I${values.length + 1}`).format.numberFormat = "0.00;[Red](0.00);-";
  history.getRange(`K2:L${values.length + 1}`).format.numberFormat = "0.00;[Red](0.00);-";
  history.getRange(`J2:J${values.length + 1}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  history.getRange(`M2:N${values.length + 1}`).format.numberFormat = "0.0%;[Red](0.0%);-";
  history.getRange(`A1:P${values.length + 1}`).format.borders = { preset: "inside", style: "thin", color: "#E7E6E6" };
  history.freezePanes.freezeRows(1);
  [10, 12, 14, 14, 12, 12, 12, 14, 13, 15, 13, 13, 15, 16, 62, 18].forEach((w, i) => history.getRangeByIndexes(0, i, 1, 1).format.columnWidth = w);

  sources.getRange("A1:D1").merge(); sources.getRange("A1").values = [["資料來源與使用說明"]]; style(sources, "A1:D1", "#17365D");
  sources.getRange("A3:D3").values = [["項目", "內容", "來源", "備註"]]; style(sources, "A3:D3", "#1F4E78");
  sources.getRange("A4:D8").values = [
    ["歷年股利／歷史殖利率", "Goodinfo 個股股利政策頁的年度明細", SOURCE_BASE, "股利發放年度依除權息日或董事會決議日認定。"],
    ["參考現價", "Goodinfo 網頁於程式更新時顯示之成交價／表內成交價", SOURCE_BASE, "非即時報價；交易前請另行確認。"],
    ["預估殖利率", "最新已公告現金股利 ÷ 參考現價", "Excel 總覽公式", "不包含股票股利；非保證收益率。"],
    ["更新方法", "執行 finance_dividend_report.mjs", "本機程式", "請遵守 Goodinfo 服務條款與合理更新頻率。"],
    ["離線初始資料", "若程式無法連線，會保留本版本內建的中信金、合庫金歷史快照", "Goodinfo 頁面快照（2026-07-17）", "狀態欄會標示「離線初始資料」；成功抓取後即自動取代。"],
  ];
  sources.getRange("A3:D8").format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
  sources.getRange("A4:D8").format.wrapText = true;
  [22, 44, 64, 42].forEach((w, i) => sources.getRangeByIndexes(0, i, 1, 1).format.columnWidth = w);
  sources.getRange("A4:D8").format.rowHeight = 42;

  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  const xlsx = await SpreadsheetFile.exportXlsx(wb);
  await xlsx.save(OUT_FILE);
  return { wb, outFile: OUT_FILE };
}

const allRows = [];
const failures = [];
const inputPosition = process.argv.indexOf("--input");
if (inputPosition >= 0) {
  const payloadPath = process.argv[inputPosition + 1];
  if (!payloadPath) throw new Error("--input 後必須提供 JSON 檔案路徑。");
  const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
  allRows.push(...(payload.rows ?? []));
  failures.push(...(payload.failures ?? []));
  for (const stock of STOCKS) {
    if (!allRows.some((row) => row.stockId === stock.id)) {
      allRows.push(...fallbackRows(stock));
      if (!failures.includes(stock.id)) failures.push(stock.id);
    }
  }
} else {
  for (const stock of STOCKS) {
    try { allRows.push(...await fetchStock(stock)); }
    catch (error) { failures.push(stock.id); allRows.push(...fallbackRows(stock)); console.warn(`${stock.id} ${stock.name}：${error.message}（改用內建初始資料）`); }
    await sleep(1500);
  }
}
const { wb, outFile } = await buildWorkbook(allRows, new Date(), failures);
const check = await wb.inspect({ kind: "table", range: "總覽!A1:I13", include: "values,formulas", tableMaxRows: 13, tableMaxCols: 9 });
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 } });
console.log(check.ndjson);
console.log(errors.ndjson);
console.log(`已建立：${outFile}`);
