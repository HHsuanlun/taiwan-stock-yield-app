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

export default {fetch: createHandler("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>私人台股安全估值</title><style>\n:root{--navy:#17365d;--blue:#24618f;--green:#18764c;--red:#b33a3a;--line:#dbe3ea;--paper:#fff;--bg:#f3f7fa;--muted:#657384}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#243342;font:15px/1.55 system-ui,-apple-system,\"Noto Sans TC\",sans-serif}header{padding:18px 16px;background:var(--navy);color:#fff}header div,main{max-width:760px;margin:auto}h1{margin:0;font-size:20px}header p{margin:3px 0 0;opacity:.8;font-size:12px}main{padding:16px}.card{margin-bottom:12px;padding:16px;background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 2px 8px #17365d0a}.search{display:flex;gap:8px}.search input{min-width:0;flex:1;padding:12px;border:1px solid #afbdca;border-radius:9px;font-size:16px}.search button,.quick button,#refresh{padding:11px 14px;border:0;border-radius:9px;background:var(--blue);color:#fff;font-weight:750}.quick{display:flex;gap:6px;overflow:auto;margin-top:10px}.quick button{flex:none;padding:7px 10px;background:#eaf1f7;color:var(--blue)}#status{margin:10px 0 0;color:var(--muted);font-size:12px}.headline{display:flex;justify-content:space-between;gap:12px;align-items:start}.headline h2{margin:0;color:var(--navy)}.price{text-align:right}.price strong{display:block;font-size:26px;color:var(--navy)}.badge{display:inline-block;padding:5px 8px;border-radius:999px;font-size:11px;font-weight:800}.good{background:#e7f5ed;color:var(--green)}.bad{background:#fdecec;color:var(--red)}.scenarios{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.scenario{padding:12px;border:1px solid var(--line);border-radius:10px}.scenario span,.scenario small{display:block;color:var(--muted);font-size:11px}.scenario strong{display:block;margin:4px 0;color:var(--navy);font-size:21px}.scenario.base{border:2px solid var(--blue)}.checks{margin:0;padding:0;list-style:none}.checks li{padding:9px 0;border-bottom:1px solid #edf1f4}.checks b{color:var(--green)}.checks .fail b{color:var(--red)}.checks small{display:block;color:var(--muted)}.warning{padding:12px;border-radius:9px;background:#fdecec;color:#8c2929;font-weight:700}dl{margin:0}dl div{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #edf1f4}dt{color:var(--muted)}dd{margin:0;font-weight:700}.hidden{display:none!important}@media(max-width:540px){.scenarios{grid-template-columns:1fr}.search{flex-wrap:wrap}.search input{width:100%;flex-basis:100%}}\n</style></head><body><header><div><h1>私人台股安全估值</h1><p>資料未通過官方交叉核對時，不提供便宜／昂貴判斷</p></div></header><main>\n<section class=\"card\"><form id=\"form\" class=\"search\"><input id=\"code\" inputmode=\"numeric\" value=\"2880\" maxlength=\"4\" aria-label=\"股票代號\"><button>安全估值</button><button id=\"refresh\" type=\"button\">強制更新</button></form><div id=\"quick\" class=\"quick\"></div><p id=\"status\">請輸入股票代號。</p></section>\n<div id=\"result\" class=\"hidden\"><section class=\"card headline\"><div><span id=\"quality\" class=\"badge\"></span><h2><span id=\"name\"></span> <small id=\"ticker\"></small></h2><small id=\"date\"></small></div><div class=\"price\"><span>官方核對股價</span><strong id=\"price\"></strong></div></section><section id=\"blocked\" class=\"card warning hidden\"></section><section id=\"scenarioCard\" class=\"card\"><div class=\"scenarios\"><div class=\"scenario\"><span>保守</span><strong id=\"bear\"></strong><small id=\"bearIn\"></small></div><div class=\"scenario base\"><span>中性</span><strong id=\"base\"></strong><small id=\"baseIn\"></small></div><div class=\"scenario\"><span>樂觀</span><strong id=\"bull\"></strong><small id=\"bullIn\"></small></div></div></section><section class=\"card\"><h3>資料品質檢查</h3><ul id=\"checks\" class=\"checks\"></ul></section><section class=\"card\"><h3>模型摘要</h3><dl><div><dt>目前股價</dt><dd id=\"modelPrice\"></dd></div><div><dt>中性合理價</dt><dd id=\"fair\"></dd></div><div><dt>合理價差</dt><dd id=\"gap\"></dd></div><div><dt>歷史完整年度</dt><dd id=\"years\"></dd></div><div><dt>模型版本</dt><dd id=\"version\"></dd></div></dl></section></div></main><script>\nconst $=id=>document.getElementById(id),money=v=>`NT$ ${Number(v).toFixed(2)}`;let lastForce=false;\nasync function common(){const d=await fetch('/api/common').then(r=>r.json());Object.entries(d).forEach(([code,name])=>{const b=document.createElement('button');b.type='button';b.textContent=name;b.onclick=()=>{$('code').value=code;load(false)};$('quick').append(b)})}\nfunction render(payload){const {data:d,quality:q}=payload,a=d.assumptions;$('result').classList.remove('hidden');$('quality').textContent=q.safe?'資料驗證通過':'停止估值判斷';$('quality').className='badge '+(q.safe?'good':'bad');$('name').textContent=d.company_name;$('ticker').textContent=d.ticker;$('date').textContent=`${q.official.market} ${q.official.date}`;$('price').textContent=money(q.official.price);$('checks').innerHTML=q.checks.map(c=>`<li class=\"${c.ok?'':'fail'}\"><b>${c.ok?'✓':'✕'} ${c.name}</b><small>${c.message}</small></li>`).join('');$('blocked').classList.toggle('hidden',q.safe);$('scenarioCard').classList.toggle('hidden',!q.safe);if(!q.safe)$('blocked').textContent='資料未通過驗證，本次不顯示便宜／昂貴結論：'+q.fatal.join('；');for(const k of ['bear','base','bull']){const s=a.scenarios[k];$(k).textContent=money(s.composite_value);$(k+'In').textContent=`P/E ${money(s.pe_value)}｜P/B ${money(s.pb_value)}`}$('modelPrice').textContent=money(d.current_price);$('fair').textContent=q.safe?money(d.fair_value):'已封鎖';$('gap').textContent=q.safe?`${d.upside_pct>=0?'+':''}${d.upside_pct.toFixed(1)}% ${d.classification}`:'不判斷';$('years').textContent=`${d.historical.length} 年`;$('version').textContent=d.model_version}\nasync function load(force){const code=$('code').value.trim();$('status').textContent=force?'正在強制更新並驗證…':'正在取得並驗證資料…';try{const r=await fetch(`/api/valuation?code=${encodeURIComponent(code)}${force?'&refresh=1':''}`);const d=await r.json();if(!r.ok&& !d.quality)throw new Error(d.detail||d.error);render(d);$('status').textContent=d.quality.safe?'資料已通過官方交叉核對。':'資料異常，本次估值已停止。'}catch(e){$('status').textContent=e.message;$('result').classList.add('hidden')}}$('form').onsubmit=e=>{e.preventDefault();load(false)};$('refresh').onclick=()=>load(true);common();load(false);\n</script></body></html>\n")};
