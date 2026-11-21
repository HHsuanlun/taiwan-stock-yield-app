const SOURCE = "https://taiwan-stock-valuation.onrender.com";
const common = {2880:"華南金",2881:"富邦金",2882:"國泰金",2883:"凱基金",2884:"玉山金",2885:"元大金",2886:"兆豐金",2887:"台新新光金",2890:"永豐金",2891:"中信金",2892:"第一金",5880:"合庫金"};
const cache = new Map();
const num = value => { const n=Number(String(value??"").replaceAll(",","")); return Number.isFinite(n)&&n>0?n:null; };
const taipeiDay = () => new Intl.DateTimeFormat("sv-SE",{timeZone:"Asia/Taipei"}).format(new Date());
const rocDay = value => { const m=String(value).match(/(\d+)年(\d+)月(\d+)日/); return m?`${Number(m[1])+1911}-${m[2].padStart(2,"0")}-${m[3].padStart(2,"0")}`:null; };
async function json(url, timeout=15000){
  const response=await fetch(url,{headers:{"user-agent":"PrivateTaiwanValuation/1.0"},signal:AbortSignal.timeout(timeout)});
  const text=await response.text(); if(!response.ok||!text.trim()) throw new Error(`來源回應失敗 HTTP ${response.status}`);
  try{return JSON.parse(text);}catch{throw new Error("來源回應格式錯誤");}
}
async function twseOfficial(code,today){
  const month=today.slice(0,7).replace("-","")+"01";
  const [prices,multiples]=await Promise.all([
    json(`https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=${month}&stockNo=${code}`),
    json(`https://www.twse.com.tw/exchangeReport/BWIBBU?response=json&date=${month}&stockNo=${code}`)
  ]);
  if(prices.stat!=="OK"||!prices.data?.length||multiples.stat!=="OK"||!multiples.data?.length) throw new Error("非上市股票");
  const p=prices.data.at(-1), fields=multiples.fields||[], m=multiples.data.at(-1);
  const peI=fields.indexOf("本益比"),pbI=fields.indexOf("股價淨值比");
  return {market:"TWSE",date:rocDay(p[0]),price:num(p[6]),pe:num(m[peI]),pb:num(m[pbI])};
}
async function tpexOfficial(code,today){
  const month=today.slice(0,7).replaceAll("-","/")+"/01";
  const priceBody=await json(`https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock?code=${code}&date=${month}&id=&response=json`);
  const target=new Date(today+"T00:00:00Z"); while(target.getUTCDay()===0||target.getUTCDay()===6)target.setUTCDate(target.getUTCDate()-1);
  const day=target.toISOString().slice(0,10).replaceAll("-","/");
  const multipleBody=await json(`https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date=${day}&id=&response=json`);
  const p=priceBody.tables?.[0]?.data?.at(-1), rows=multipleBody.tables?.[0]?.data||[], m=rows.find(row=>String(row[0]).trim()===code);
  if(!p||!m)throw new Error("官方找不到股票");
  const [y,mo,d]=p[0].split("/");
  return {market:"TPEx",date:`${Number(y)+1911}-${mo}-${d}`,price:num(p[6]),pe:num(m[2]),pb:num(m[6])};
}
async function official(code,today){try{return await twseOfficial(code,today);}catch{return await tpexOfficial(code,today);}}
function daysBetween(a,b){return Math.floor((Date.parse(a)-Date.parse(b))/86400000);}
function audit(data,officialRow,today){
  const checks=[],fatal=[];
  const add=(name,ok,message,hard=true)=>{checks.push({name,ok,message});if(!ok&&hard)fatal.push(message);};
  add("官方行情日期",!!officialRow.date&&daysBetween(today,officialRow.date)<=7,`官方行情日期 ${officialRow.date||"無"}`);
  const delta=officialRow.price&&data.current_price?Math.abs(data.current_price/officialRow.price-1):Infinity;
  add("股價交叉核對",delta<=0.02,`估值 ${Number(data.current_price).toFixed(2)}／官方 ${Number(officialRow.price).toFixed(2)}，差異 ${Number.isFinite(delta)?(delta*100).toFixed(1):"—"}%`);
  add("歷史樣本",Array.isArray(data.historical)&&data.historical.length>=5,`有效完整年度 ${data.historical?.length||0} 年`);
  const a=data.assumptions||{},w=a.model_weights||{};
  add("EPS／BPS",a.forecast_eps>0&&a.forecast_bps>0,`EPS ${a.forecast_eps??"—"}／BPS ${a.forecast_bps??"—"}`);
  add("模型權重",Math.abs((Number(w.pe)+Number(w.pb))-1)<0.002,`P/E ${((w.pe||0)*100).toFixed(1)}%／P/B ${((w.pb||0)*100).toFixed(1)}%`);
  for(const key of ["bear","base","bull"]){const s=a.scenarios?.[key];if(!s)continue;const rebuilt=s.pe_value*w.pe+s.pb_value*w.pb;add(`${key}情境重算`,Math.abs(rebuilt-s.composite_value)<=0.03,`API ${s.composite_value}／重算 ${rebuilt.toFixed(2)}`);}
  const oldest=data.historical?.[0]?.year,newest=data.historical?.at(-1)?.year;
  add("年度連續性",newest-oldest+1===data.historical?.length,`歷史區間 ${oldest||"—"}–${newest||"—"}`,false);
  return {safe:fatal.length===0,checks,fatal,official:officialRow,audited_at:new Date().toISOString()};
}
async function valuation(code,force=false){
  if(!/^\d{4}$/.test(code))throw new Error("請輸入四位數台股代號");
  const previous=cache.get(code);if(!force&&previous?.until>Date.now())return previous.data;
  const today=taipeiDay();
  const [data,officialRow]=await Promise.all([
    json(`${SOURCE}/api/stocks/${code}/valuation`,45000),official(code,today)
  ]);
  const quality=audit(data,officialRow,today);
  const result={data,quality};
  if(quality.safe)cache.set(code,{data:result,until:Date.now()+10*60*1000});
  return result;
}
export function createHandler(html){return async request=>{
  const url=new URL(request.url);
  if(url.pathname==="/")return new Response(html,{headers:{"content-type":"text/html; charset=utf-8","cache-control":"no-store"}});
  if(url.pathname==="/api/common")return Response.json(common);
  if(url.pathname!=="/api/valuation")return new Response(null,{status:404});
  try{const result=await valuation((url.searchParams.get("code")||"").trim(),url.searchParams.get("refresh")==="1");return Response.json(result,{status:result.quality.safe?200:409,headers:{"cache-control":"no-store"}});}
  catch(error){return Response.json({error:"無法完成安全估值",detail:error.message},{status:502,headers:{"cache-control":"no-store"}});}
};}
