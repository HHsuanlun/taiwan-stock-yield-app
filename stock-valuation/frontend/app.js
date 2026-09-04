const $ = (id) => document.getElementById(id);
let latest;

function money(value) { return Number(value).toFixed(1); }
function setText(id, value) { $(id).textContent = value; }

function drawScatter(data) {
  const svg = $("scatter"), w = 700, h = 330, pad = {l:52,r:25,t:22,b:42};
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  const points = data.historical.map(d => ({x:d.eps,y:d.pe,label:d.year}));
  points.push({x:data.assumptions.forecast_eps,y:data.fair_pe,label:"模型",forecast:true});
  const xs=points.map(p=>p.x), ys=points.map(p=>p.y), xmin=Math.min(...xs)-1, xmax=Math.max(...xs)+1, ymin=Math.min(...ys)-1, ymax=Math.max(...ys)+1;
  const sx=x=>pad.l+(x-xmin)/(xmax-xmin)*(w-pad.l-pad.r), sy=y=>h-pad.b-(y-ymin)/(ymax-ymin)*(h-pad.t-pad.b);
  let html="";
  for(let i=0;i<5;i++){const y=pad.t+i*(h-pad.t-pad.b)/4; const val=ymax-i*(ymax-ymin)/4; html+=`<line x1="${pad.l}" y1="${y}" x2="${w-pad.r}" y2="${y}" stroke="#dde1da"/><text x="${pad.l-10}" y="${y+4}" text-anchor="end" fill="#78817d" font-size="11">${val.toFixed(1)}x</text>`}
  html+=`<text x="${w/2}" y="${h-5}" text-anchor="middle" fill="#78817d" font-size="11">每股盈餘 EPS</text>`;
  points.forEach(p=>{const color=p.forecast?"#a94f36":"#1f5c48",r=p.forecast?8:5;html+=`<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="${r}" fill="${color}" opacity="${p.forecast?1:.82}"/><text x="${sx(p.x)}" y="${sy(p.y)-10}" text-anchor="middle" fill="${color}" font-size="10" font-weight="700">${p.label}</text>`});
  svg.innerHTML=html;
}

function render(data) {
  latest=data;
  const a=data.assumptions;
  setText("company",data.company_name);setText("stockCode",data.ticker);setText("currentPrice",money(data.current_price));setText("asOf",data.source_notes[0].as_of);
  setText("bearValue",money(data.bear_value));setText("fairValue",money(data.pe_target_price));setText("bullValue",money(data.bull_value));
  setText("upside",`${data.upside_pct>=0?"+":""}${data.upside_pct.toFixed(1)}%`);setText("classification",data.classification);setText("confidence",data.confidence);
  setText("bearInputs",`EPS ${a.scenarios.bear.eps.toFixed(2)} × P/E ${a.scenarios.bear.pe.toFixed(2)}`);
  setText("baseInputs",`EPS ${a.scenarios.base.eps.toFixed(2)} × P/E ${a.scenarios.base.pe.toFixed(2)}`);
  setText("bullInputs",`EPS ${a.scenarios.bull.eps.toFixed(2)} × P/E ${a.scenarios.bull.pe.toFixed(2)}`);
  const rr=a.rerating;const signed=v=>`${v>=0?"+":""}${v.toFixed(1)}%`;setText("peTarget",money(data.pe_target_price));setText("historicalFairPe",`${a.historical_fair_pe.toFixed(2)}x`);setText("currentRegimePe",rr.current_regime_pe==null?"資料不足":`${rr.current_regime_pe.toFixed(2)}x`);setText("fairPe",`${data.fair_pe.toFixed(2)}x`);setText("impliedPe",`${data.implied_forward_pe.toFixed(2)}x`);setText("historicalPremium",signed(a.premium_to_historical_pe_pct));setText("pePremium",signed(a.premium_to_fair_pe_pct));setText("historyPeStats",`${a.historical_median_pe.toFixed(2)}x／${a.historical_mean_pe.toFixed(2)}x`);setText("recentPe",`${a.recent_pe.toFixed(2)}x（3年）`);setText("regressionStats",`${a.regression_pe.toFixed(2)}x／${a.regression_r2.toFixed(3)}`);setText("rerating",`${rr.label} ${signed((rr.rerating_ratio-1)*100)}`);setText("regimeSource",rr.source?`${rr.source}（${rr.observation_count}筆）`:"資料不足");setText("regimeStats",rr.current_regime_pe==null?"—":`${rr.current_regime_pe.toFixed(2)}x／${rr.current_regime_mad.toFixed(2)}x`);setText("persistence",`${rr.persistence_count}／${rr.observation_count}（${(rr.persistence_score*100).toFixed(0)}%）`);setText("fundamentalConfirm",`${(rr.fundamental_score*100).toFixed(0)}%${rr.accounting_regime_change?" · 會計制度變更":""}`);setText("layerWeights",`歷史 ${(rr.historical_layer_weight*100).toFixed(0)}% · Regime ${(rr.effective_regime_weight*100).toFixed(0)}%`);setText("basePeAdjust",`${a.base_pe_before_rerating.toFixed(2)}x／${a.base_pe_after_rerating.toFixed(2)}x`);setText("spreadStats",`${a.pe_mad.toFixed(2)}x／${a.pe_spread.toFixed(2)}x`);setText("effectiveWeights",`迴歸 ${(a.pe_reference_weights[0]*100).toFixed(0)}% · 近期 ${(a.pe_reference_weights[1]*100).toFixed(0)}% · 長期 ${(a.pe_reference_weights[2]*100).toFixed(0)}%`);setText("confidenceScore",`${a.confidence_score.toFixed(3)}（${data.confidence}）`);
  const pb=a.pb_model.traditional,apb=a.pb_model.adjusted;setText("pbTarget",money(data.pb_target_price));setText("historicalFairPb",`${pb.historical_fair_pb.toFixed(2)}x`);setText("currentRegimePb",pb.current_regime_pb==null?"資料不足":`${pb.current_regime_pb.toFixed(2)}x`);setText("fairPb",`${data.fair_pb.toFixed(2)}x`);setText("pbScenarios",`${pb.bear_pb.toFixed(2)}／${pb.base_pb.toFixed(2)}／${pb.bull_pb.toFixed(2)}x`);setText("pbMedians",`${pb.historical_median.toFixed(2)}／${pb.recent_median.toFixed(2)}x`);setText("pbRegime",`${pb.regime_ratio.toFixed(2)}x／${(pb.persistence_score*100).toFixed(0)}%`);setText("pbScores",`${(pb.fundamental_score*100).toFixed(0)}%／${(pb.book_value_quality_score*100).toFixed(0)}%／${(pb.accounting_comparability_score*100).toFixed(0)}%`);setText("pbLayerWeights",`歷史 ${(pb.historical_weight*100).toFixed(0)}% · Regime ${(pb.regime_weight*100).toFixed(0)}%`);setText("pbSpread",`${pb.pb_mad.toFixed(2)}／${pb.spread.toFixed(2)}x`);setText("forecastBps",a.forecast_bps.toFixed(1));setText("currentPb",`${pb.current_pb.toFixed(2)}x`);setText("adjustedBps",a.adjusted_bps_reference.toFixed(1));setText("adjustedCurrentPb",`${apb.current_pb.toFixed(2)}x`);setText("adjustedPbStatus",apb.status);setText("pbPremiums",`${pb.premium_to_historical_pct>=0?"+":""}${pb.premium_to_historical_pct.toFixed(1)}%／${pb.premium_to_final_pct>=0?"+":""}${pb.premium_to_final_pct.toFixed(1)}%`);setText("requiredBps",`${pb.required_bps.toFixed(1)} 元`);setText("pbConfidence",`${pb.confidence_score.toFixed(3)}（${pb.confidence}）`);setText("version",data.model_version);
  setText("compositeValue",money(data.fair_value));setText("peFairValue",`NT$ ${money(data.pe_target_price)}`);setText("pbFairValue",`NT$ ${money(data.pb_target_price)}`);
  setText("modelWeights",`P/E ${(a.model_weights.pe*100).toFixed(0)}% · P/B ${(a.model_weights.pb*100).toFixed(0)}%`);setText("safetyMargin",`${a.safety_margin_pct.toFixed(1)}%`);
  setText("requiredEps",`${a.required_eps.toFixed(2)} 元 EPS`);setText("reversePrice",`NT$ ${money(data.current_price)}`);setText("reversePe",`${data.fair_pe.toFixed(2)}x`);setText("reverseEps",`${a.required_eps.toFixed(2)} 元`);
  const labels={bear:"悲觀",base:"中性",bull:"樂觀"};const pes=a.scenarios;
  $("matrixHead").innerHTML=`<tr><th>EPS 情境</th><th>悲觀 P/E<br>${pes.bear.pe.toFixed(2)}x</th><th>中性 P/E<br>${pes.base.pe.toFixed(2)}x</th><th>樂觀 P/E<br>${pes.bull.pe.toFixed(2)}x</th></tr>`;
  $("matrixBody").innerHTML=a.valuation_matrix.map(row=>`<tr><th>${labels[row.scenario]} EPS<br>${row.eps.toFixed(2)}</th><td>${money(row.prices.bear)}</td><td class="${row.scenario==='base'?'focus':''}">${money(row.prices.base)}</td><td>${money(row.prices.bull)}</td></tr>`).join("");
  const pbs=a.pb_model.pb_scenarios;$("pbMatrixHead").innerHTML=`<tr><th>BPS 情境</th><th>悲觀 P/B<br>${pbs.bear.toFixed(2)}x</th><th>中性 P/B<br>${pbs.base.toFixed(2)}x</th><th>樂觀 P/B<br>${pbs.bull.toFixed(2)}x</th></tr>`;$("pbMatrixBody").innerHTML=pb.valuation_matrix.map(row=>`<tr><th>${labels[row.scenario]} BPS<br>${row.bps.toFixed(2)}</th><td>${money(row.prices.bear)}</td><td class="${row.scenario==='base'?'focus':''}">${money(row.prices.base)}</td><td>${money(row.prices.bull)}</td></tr>`).join("");
  setText("sourceNote",data.source_notes.map(source=>`${source.name}（截至 ${source.as_of}）：${source.note}`).join("；")+"。");
  setText("epsMethod",a.forecast_method);
  setText("bpsMethod",a.bps_method);
  const direction=a.eps_pe_correlation<0?"負相關":"正相關";setText("correlationNote",`相關係數 ${a.eps_pe_correlation.toFixed(3)}（${direction}），R² ${a.regression_r2.toFixed(3)}。R² 會自動調整迴歸權重；未使用權重按 70%／30% 回補近期與長期中位數。`);
  $("historyRows").innerHTML=data.historical.map(d=>`<tr><td>${d.year}</td><td>${d.eps.toFixed(2)}</td><td>${d.pe.toFixed(1)}x</td><td>${d.bps.toFixed(1)}</td><td>${d.pb.toFixed(2)}x</td></tr>`).join("");
  drawScatter(data);
}

async function calculate() {
  const peWeight=Number($("peWeight").value)/100;
  const eps=Number($("eps").value);const payload={ticker:$("ticker").value.trim(),forecast_eps:eps,forecast_bps:Number($("bps").value),pe_weight:peWeight,pb_weight:1-peWeight};
  try{const res=await fetch("/api/valuation",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!res.ok)throw new Error((await res.json()).detail||"估值服務暫時無法使用");render(await res.json());$("searchHint").textContent="MVP 第一階段支援 2881 富邦金";$("searchHint").className=""}catch(err){$("searchHint").textContent=err.message;$("searchHint").className="error"}
}

function syncControls(){setText("epsOut",Number($("eps").value).toFixed(2));setText("bpsOut",Number($("bps").value).toFixed(1));const w=$("peWeight").value;setText("weightOut",`P/E ${w}% · P/B ${100-w}%`);calculate()}
let timer;["eps","bps","peWeight"].forEach(id=>$(id).addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(syncControls,80)}));
$("searchForm").addEventListener("submit",e=>{e.preventDefault();calculate()});
$("reset").addEventListener("click",()=>{$("eps").value=10.95;$("bps").value=83.7;$("peWeight").value=50;syncControls()});
$("toggleTable").addEventListener("click",()=>{const wrap=$("tableWrap");wrap.hidden=!wrap.hidden;$("toggleTable").textContent=wrap.hidden?"展開資料":"收合資料"});
calculate();
