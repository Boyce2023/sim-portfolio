// 高标首阴 V5.1 盘感刷题机前端（独立文件，复用 astock2 样式与口令外壳）
function initTrainerApp(DATA) {
  const KEY = (window.HIGH_STATS_KEY || 'high_v51') + '_progress';
  let st = {}; try { st = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
  let cur = 0; const root = document.getElementById('high-app');
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} };
  const col = v => v > 0 ? '#dc2626' : (v < 0 ? '#16a34a' : '#6b7280');
  const fr = v => (v > 0 ? '涨' : (v < 0 ? '跌' : '')) + Math.abs(v).toFixed(2) + '%';
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
    let h = `<div class="hd-top"><b>${window.HIGH_TITLE || '高标首阴盘感刷题机'}</b>
      <span>已答 ${s.n}/${DATA.length}</span><span>答对 ${s.ok}</span>
      <span>你的累计 <b style="color:${col(s.my - 1)}">${fr((s.my - 1) * 100)}</b></span>
      <span>量化规则累计 <b style="color:${col(s.sy - 1)}">${fr((s.sy - 1) * 100)}</b></span></div>
      <div class="hd-q"><h3>第${q.id}题 · ${q.title}</h3>
      <div class="hd-mk">昨日全场涨停 ${q.n_zt} 家 · 断板日全场最高连板 ${q.max_b} 板 · 沪深300近5日${q.csi5} · K线最右蓝线为今日开盘价</div>
      <div class="hd-tip">现在是09:25竞价刚结束。下面是今天断板首阴的高标，你买哪只，还是空仓？</div>`;
    q.cands.forEach(c => {
      h += `<div class="hd-card"><div class="hd-name">${c.opt}. ${c.name} <small>${c.code}</small> · ${c.height}连板后首次断板</div>
        <canvas id="k_${c.opt}" width="520" height="150" class="hd-k"></canvas>
        <div class="hd-grid"><span>断板日收${c.d1}</span><span>断板日开盘${c.d1_open}</span><span>断板日换手${c.turn}</span>
        <span>十大股东锁仓${c.lock}</span><span>真实自由流通${c.fmcap}</span><span>今日竞价<b>${c.auction}</b></span>
        <span>监管函：${c.reg ? '<b style="color:#dc2626">有</b>' : '无'}</span><span>龙虎榜拉萨席位${c.lhasa}家</span></div>`;
      if (a) h += `<div class="hd-res" style="border-color:${col(c.ret)}">规则判断：${c.why}<br>
        实际结果：${c.filled || c.opt === q.ans ? c.exit + '，净收益 <b style="color:' + col(c.ret) + '">' + fr(c.ret) + '</b>（扣千分之二手续费）' : c.exit}</div>`;
      h += `</div>`;
    });
    h += `<div class="hd-btns">` + q.cands.map(c => `<button class="toolbar-btn${a && a.pick === c.opt ? ' primary' : ''}" data-p="${c.opt}">买 ${c.opt}. ${c.name}</button>`).join('') +
      `<button class="toolbar-btn${a && a.pick === '空仓' ? ' primary' : ''}" data-p="空仓">空仓不买</button></div>`;
    if (a) {
      const ac = q.ans === '空仓' ? '空仓' : q.ans + '. ' + q.cands.find(c => c.opt === q.ans).name;
      h += `<div class="hd-ans ${a.pick === q.ans ? 'ok' : 'bad'}">${a.pick === q.ans ? '答对了' : '和规则不一样'}。高标 V5.1 规则的选择：<b>${ac}</b>，规则当天收益 <b style="color:${col(q.sys_ret)}">${fr(q.sys_ret)}</b></div>`;
    }
    h += `</div><div class="hd-nav"><button class="toolbar-btn" id="hd-prev">上一题</button>
      <select id="hd-jump">${DATA.map((x, i) => `<option value="${i}"${i === cur ? ' selected' : ''}>第${x.id}题 ${x.date}${st[x.id] ? ' 已答' : ''}</option>`).join('')}</select>
      <button class="toolbar-btn" id="hd-next">下一题</button><button class="toolbar-btn" id="hd-reset">清空记录</button></div>`;
    if (s.n === DATA.length) h += `<div class="hd-ans ok">全部答完：你答对 ${s.ok}/${DATA.length}，你的累计 ${fr((s.my - 1) * 100)}，规则累计 ${fr((s.sy - 1) * 100)}。</div>`;
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
