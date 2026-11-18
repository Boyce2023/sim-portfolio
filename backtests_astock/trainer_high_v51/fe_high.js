// 高标首阴 V5.1 盘感刷题机前端（客观冷峻诊断 + 严守 +/- 涨跌收益率符号）
function initTrainerApp(DATA) {
  const KEY = (window.HIGH_STATS_KEY || 'high_v51') + '_progress';
  let st = {}; try { st = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
  let cur = 0; const root = document.getElementById('high-app');
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} };
  const col = v => v > 0.005 ? '#dc2626' : (v < -0.005 ? '#16a34a' : '#6b7280');
  const fr = v => Math.abs(v) < 0.005 ? '0.00%' : ((v > 0 ? '+' : '-') + Math.abs(v).toFixed(2) + '%');
  function evalRank(myPct, syPct, ok, tot) {
    const ex = myPct - syPct, exS = (Math.abs(ex) < 0.005 ? '0.00' : ((ex > 0 ? '+' : '-') + Math.abs(ex).toFixed(2))) + 'pp';
    if (myPct < -5) return ['严重亏损（实盘禁入）', '#fef2f2', '#dc2626', '#991b1b', `累计净收益 ${fr(myPct)}，跑输量化基准 ${exS}，当前盘感严禁实盘下场。`];
    if (myPct < -0.005) return ['净值亏损（不及格）', '#fef2f2', '#ef4444', '#991b1b', `累计净收益 ${fr(myPct)}，跑输现金且较量化基准差 ${exS}，未达实盘要求。`];
    if (Math.abs(myPct) <= 0.005 && syPct <= 0.005) return ['空仓保本（仅防守及格）', '#f8fafc', '#64748b', '#1e293b', `累计净收益 0.00%，同期基准 ${fr(syPct)}，进攻能力尚待验证。`];
    if (ex < -0.05) return ['跑输机械基准（主观负超额）', '#fffbeb', '#d97706', '#92400e', `虽正收益 ${fr(myPct)}，但跑输量化机械定式 ${exS}，主观干预拉低收益。`];
    if (Math.abs(ex) <= 2.0) return ['持平机械基准（纪律及格）', '#f8fafc', '#334155', '#0f172a', `累计净收益 ${fr(myPct)}，同期基准 ${fr(syPct)}（超额 ${exS}），纪律基本达标。`];
    return ['跑赢机械基准（正超额）', '#f0fdf4', '#16a34a', '#166534', `累计净收益 ${fr(myPct)}，跑赢量化机械定式 ${exS}，规则一致率 ${(ok/tot*100).toFixed(1)}%。`];
  }
  function stats() {
    let n = 0, ok = 0, my = 1, sy = 1;
    DATA.forEach(q => { const a = st[q.id]; if (!a) return; n++; if (a.pick === q.ans) ok++;
      const c = q.cands.find(x => x.opt === a.pick); my *= 1 + (c ? c.ret : 0) / 100; sy *= 1 + q.sys_ret / 100; });
    return { n, ok, my, sy };
  }
  function drawK(cv, ks) {
    const ctx = cv.getContext('2d'), W = cv.width, H = cv.height; ctx.clearRect(0, 0, W, H);
    let hi = -1e9, lo = 1e9; ks.forEach(k => { hi = Math.max(hi, k[1]); lo = Math.min(lo, k[2]); });
    const y = v => H - 6 - (v - lo) / ((hi - lo) || 1) * (H - 12), w = W / ks.length;
    ks.forEach((k, i) => { const up = k[3] >= k[0], x = i * w + w / 2, last = i === ks.length - 1;
      ctx.strokeStyle = ctx.fillStyle = last ? '#2563eb' : (up ? '#dc2626' : '#16a34a');
      ctx.beginPath(); ctx.moveTo(x, y(k[1])); ctx.lineTo(x, y(k[2])); ctx.stroke();
      const t = y(Math.max(k[0], k[3])), b = y(Math.min(k[0], k[3]));
      ctx.fillRect(x - w * 0.35, t, w * 0.7, Math.max(1.5, b - t)); });
  }
  function render() {
    const q = DATA[cur], a = st[q.id], s = stats();
    const myPct = (s.my - 1) * 100, syPct = (s.sy - 1) * 100;
    let h = `<div class="hd-top"><b>${window.HIGH_TITLE || '高标首阴盘感刷题机'}</b>
      <span>已答 ${s.n}/${DATA.length}</span><span>与规则一致 ${s.ok}</span>
      <span>你的累计 <b style="color:${col(myPct)}">${fr(myPct)}</b></span>
      <span>量化规则累计 <b style="color:${col(syPct)}">${fr(syPct)}</b></span></div>
      <div class="hd-q"><h3>第${q.id}题 · ${q.title}</h3>
      <div class="hd-mk">昨日全场涨停 ${q.n_zt} 家 · 断板日全场最高连板 ${q.max_b} 板 · 沪深300近5日 ${q.csi5} · K线最右蓝线为今日开盘价</div>
      <div class="hd-tip">现在是 09:25 竞价刚结束。下面是今天断板首阴的高标，选择买入标的或空仓防守：</div>`;
    q.cands.forEach(c => {
      h += `<div class="hd-card"><div class="hd-name">${c.opt}. ${c.name} <small>${c.code}</small> · ${c.height}连板后首次断板</div>
        <canvas id="k_${c.opt}" width="520" height="150" class="hd-k"></canvas>
        <div class="hd-grid"><span>断板日收盘 ${c.d1}</span><span>断板日开盘 ${c.d1_open}</span><span>断板日换手 ${c.turn}</span>
        <span>十大股东锁仓 ${c.lock}</span><span>真实自由流通 ${c.fmcap}</span><span>今日竞价 <b>${c.auction}</b></span>
        <span>监管函：${c.reg ? '<b style="color:#dc2626">有</b>' : '无'}</span><span>龙虎榜拉萨席位 ${c.lhasa} 家</span></div>`;
      if (a) h += `<div class="hd-res" style="border-color:${col(c.ret)}">规则判断：${c.why}<br>
        实际结果：${c.filled || c.opt === q.ans ? c.exit + '，净收益 <b style="color:' + col(c.ret) + '">' + fr(c.ret) + '</b>（已扣手续费）' : c.exit}</div>`;
      h += `</div>`;
    });
    h += `<div class="hd-btns">` + q.cands.map(c => `<button class="toolbar-btn${a && a.pick === c.opt ? ' primary' : ''}" data-p="${c.opt}">买 ${c.opt}. ${c.name}</button>`).join('') +
      `<button class="toolbar-btn${a && a.pick === '空仓' ? ' primary' : ''}" data-p="空仓">空仓不买</button></div>`;
    if (a) {
      const ac = q.ans === '空仓' ? '空仓' : q.ans + '. ' + q.cands.find(c => c.opt === q.ans).name;
      h += `<div class="hd-ans ${a.pick === q.ans ? 'ok' : 'bad'}">${a.pick === q.ans ? '与规则一致' : '与规则不符'}。高标 V5.1 规则裁决：<b>${ac}</b>，规则当题收益 <b style="color:${col(q.sys_ret)}">${fr(q.sys_ret)}</b></div>`;
    }
    h += `</div><div class="hd-nav"><button class="toolbar-btn" id="hd-prev">上一题</button>
      <select id="hd-jump">${DATA.map((x, i) => `<option value="${i}"${i === cur ? ' selected' : ''}>第${x.id}题 ${x.date}${st[x.id] ? ' 已答' : ''}</option>`).join('')}</select>
      <button class="toolbar-btn" id="hd-next">下一题</button><button class="toolbar-btn" id="hd-reset">清空记录</button></div>`;
    if (s.n === DATA.length) {
      const ev = evalRank(myPct, syPct, s.ok, DATA.length);
      h += `<div style="border:2px solid ${ev[2]};background:${ev[1]};padding:12px 14px;margin:10px 0;"><div style="font-weight:800;font-size:15px;color:#111827;">全卷客观评估（${DATA.length} 题已答完）：<span style="color:${ev[3]}">${ev[0]}</span></div><div style="font-size:13px;color:#374151;margin-top:4px;">${ev[4]} | 与规则一致：<b>${s.ok}/${DATA.length}</b></div></div>`;
    }
    root.innerHTML = h;
    q.cands.forEach(c => drawK(document.getElementById('k_' + c.opt), c.klines));
    root.querySelectorAll('[data-p]').forEach(b => b.onclick = () => { if (!st[q.id]) { st[q.id] = { pick: b.dataset.p }; save(); render(); } });
    document.getElementById('hd-prev').onclick = () => { if (cur > 0) { cur--; render(); } };
    document.getElementById('hd-next').onclick = () => { if (cur < DATA.length - 1) { cur++; render(); } };
    document.getElementById('hd-jump').onchange = e => { cur = +e.target.value; render(); };
    document.getElementById('hd-reset').onclick = () => { if (confirm('确定清空全部答题记录？')) { st = {}; save(); render(); } };
  }
  render();
}
