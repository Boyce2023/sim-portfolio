// A股三进四盘感刷题机前端核心引擎
function initTrainerApp(DATA, TITLE, SKEY) {
  const K = (SKEY || 'astock2_3to4') + '_progress';
  let st = {}; try { st = JSON.parse(localStorage.getItem(K) || '{}'); } catch (e) {}
  let cur = 0, blind = false; const root = document.getElementById('main-app-container');
  const save = () => { try { localStorage.setItem(K, JSON.stringify(st)); } catch (e) {} };
  const col = v => v > 0 ? '#dc2626' : (v < 0 ? '#16a34a' : '#6b7280');
  const fmtP = v => (v > 0 ? '赚' : (v < 0 ? '亏' : '平')) + Math.abs(v).toFixed(2) + '%';
  const fmtPct = v => (v > 0 ? '涨' : (v < 0 ? '跌' : '平')) + Math.abs(v).toFixed(2) + '%';
  function stats() {
    let n = 0, ok = 0, my = 1.0, sy = 1.0;
    DATA.forEach(q => { const a = st[q.id]; if (!a) return; n++; if (a.pick === q.ans) ok++;
      const uret = a.pick === '挂单' ? q.user_ret : 0.0; my *= (1.0 + uret / 100.0); sy *= (1.0 + q.sys_ret / 100.0); });
    return { n, ok, my: (my - 1.0) * 100.0, sy: (sy - 1.0) * 100.0 };
  }
  function drawK(cv, ks, op, postKs, isAns) {
    if (!cv) return; const ctx = cv.getContext('2d'), W = cv.width, H = cv.height; ctx.clearRect(0, 0, W, H);
    const all = isAns && postKs && postKs.length ? ks.concat(postKs) : ks;
    let hi = -1e9, lo = 1e9; all.forEach(k => { hi = Math.max(hi, k[1]); lo = Math.min(lo, k[2]); });
    hi = Math.max(hi, op); lo = Math.min(lo, op); const y = v => H - 10 - (v - lo) / ((hi - lo) || 1) * (H - 20), w = W / (all.length + 1);
    all.forEach((k, i) => { const up = k[3] >= k[0], x = i * w + w / 2;
      ctx.strokeStyle = ctx.fillStyle = (i >= ks.length) ? '#2563eb' : (up ? '#dc2626' : '#16a34a');
      ctx.beginPath(); ctx.moveTo(x, y(k[1])); ctx.lineTo(x, y(k[2])); ctx.stroke();
      const t = y(Math.max(k[0], k[3])), b = y(Math.min(k[0], k[3]));
      ctx.fillRect(x - w * 0.35, t, w * 0.7, Math.max(1.5, b - t)); });
    if (!isAns) { const x = ks.length * w + w / 2; ctx.strokeStyle = '#2563eb'; ctx.beginPath();
      ctx.arc(x, y(op), 3.5, 0, 2 * Math.PI); ctx.fillStyle = '#2563eb'; ctx.fill(); }
  }
  function render() {
    const q = DATA[cur], a = st[q.id], s = stats();
    const nameStr = blind ? '标的' + String.fromCharCode(65 + cur % 26) : q.name;
    const codeStr = blind ? '******' : q.code;
    let h = `<header class="top-header"><div class="brand-title"><span class="brand-tag">量化主战</span><span>${TITLE || '三进四盘感刷题机'}</span></div>
      <div class="stats-summary"><div class="stat-pill"><span class="stat-label">已答关卡</span><span class="stat-val">${s.n}/${DATA.length}</span></div>
      <div class="stat-pill"><span class="stat-label">答对定式</span><span class="stat-val" style="color:#2563eb;">${s.ok}关</span></div>
      <div class="stat-pill"><span class="stat-label">你的累计</span><span class="stat-val" style="color:${col(s.my)}">${fmtP(s.my)}</span></div>
      <div class="stat-pill"><span class="stat-label">定式累计</span><span class="stat-val" style="color:${col(s.sy)}">${fmtP(s.sy)}</span></div>
      <button class="toolbar-btn" id="btn-reset" style="color:#dc2626;">清空重测</button></div></header>
      <div class="toolbar"><div class="toolbar-group"><button class="toolbar-btn" id="btn-blind">${blind ? '盲测开启中（隐藏代码）' : '盲测已关闭（点击开启）'}</button>
      <span style="color:#6b7280;font-size:11px;">快捷键：1或A挂单，2或B空仓，空格下一题，R重做本题</span></div>
      <div class="toolbar-group"><button class="toolbar-btn" id="btn-prev">← 上一关</button>
      <select id="jump-select" style="font-size:12px;padding:3px 6px;">${DATA.map((x, i) => `<option value="${i}"${i === cur ? ' selected' : ''}>第${x.id}关 ${x.date_fmt} ${st[x.id] ? '已作答' : '未练'}</option>`).join('')}</select>
      <button class="toolbar-btn primary" id="btn-next">下一关 →</button></div></div>
      <div class="case-banner"><div><div class="case-title">第 ${q.id} 关 · ${nameStr}（${codeStr}）· ${q.plate}</div>
      <div class="case-sub">买入日：${q.date_fmt}（${q.weekday_str}）· ${q.cal_window_str} · 09:25竞价刚定盘</div></div>
      <div style="font-weight:700;font-size:12px;color:#1e40af;background:#eff6ff;padding:4px 8px;border:1px solid #bfdbfe;">三进四接力博弈节点</div></div>
      <section class="section-card"><div class="section-header"><div><span class="module-tag">模块一</span><span>市场情绪环境与所属题材生态（09:25客观数据）</span></div></div>
      <div class="metric-grid"><div class="metric-box"><div class="metric-box-title">前日全场涨停 / 最高板</div><div class="metric-box-val">${q.mkt_zt_prev} 家 / ${q.mkt_max_board_prev} 板</div></div>
      <div class="metric-box"><div class="metric-box-title">沪深300 前日 / 近5日</div><div class="metric-box-val">${fmtPct(q.csi_1d_prev)} / ${fmtPct(q.csi_5d_prev)}</div></div>
      <div class="metric-box"><div class="metric-box-title">题材名称 / 题材热度</div><div class="metric-box-val">${q.plate} / ${q.p_elo.toFixed(1)}分</div></div>
      <div class="metric-box"><div class="metric-box-title">题材首板高开助攻 / 一字</div><div class="metric-box-val">${q.plate_fb_ho_cnt} 家 / ${q.plate_fb_yz_cnt} 家</div></div></div>
      <div class="metric-grid"><div class="metric-box"><div class="metric-box-title">题材队友竞价均幅</div><div class="metric-box-val">${fmtPct(q.plate_peers_open_avg)}</div></div>
      <div class="metric-box"><div class="metric-box-title">三板龙虎榜拉萨席位</div><div class="metric-box-val">${q.lhb_lh_cnt} 家</div></div>
      <div class="metric-box"><div class="metric-box-title">一日游砸盘席位</div><div class="metric-box-val" style="color:${q.surf_yz_buy ? '#dc2626' : '#16a34a'};">${q.surf_yz_buy ? '有上塘路等席位' : '无'}</div></div>
      <div class="metric-box"><div class="metric-box-title">交易所重点监控期</div><div class="metric-box-val" style="color:${q.has_ex_reg ? '#dc2626' : '#374151'};">${q.has_ex_reg ? '重点监控期' : '无'}</div></div></div></section>
      <section class="section-card"><div class="section-header"><div><span class="module-tag">模块二</span><span>标的个股三板特征与四板竞价结构（09:25可见）</span></div></div>
      <div class="metric-grid"><div class="metric-box"><div class="metric-box-title">三板收盘价 / 换手率</div><div class="metric-box-val">${q.px_d3.toFixed(2)} 元 / ${q.prev_to.toFixed(1)}%</div></div>
      <div class="metric-box"><div class="metric-box-title">三板首封时间 / 开板次数</div><div class="metric-box-val">${q.first_seal_time} / ${q.open_board_count} 次</div></div>
      <div class="metric-box"><div class="metric-box-title">前十股东锁仓 / 自由流通盘</div><div class="metric-box-val">${q.lock_top10.toFixed(1)}% / ${q.real_free_mcap.toFixed(1)} 亿元</div></div>
      <div class="metric-box"><div class="metric-box-title">四板竞价涨跌 / 三板名次</div><div class="metric-box-val" style="color:${col(q.open_pct)};">${fmtPct(q.open_pct)} / ${q.is_top1_3b_open ? '头名' : '非头名'}（共${q.b3_rival_cnt}只）</div></div></div>
      <div style="font-weight:700;font-size:12px;margin:8px 0 4px 0;">近20日K线（截至三板日，最右蓝点为今日四板竞价开盘价 ${q.open_px.toFixed(2)} 元）：</div>
      <canvas id="kline-canvas" width="1050" height="160" class="kline-canvas"></canvas></section>
      <div style="font-weight:700;font-size:13px;margin:12px 0 6px 0;">站在 09:25 集合竞价结束时点，你的决策是？</div>
      <div class="action-grid"><button class="action-btn hang${a && a.pick === '挂单' ? ' selected' : ''}" data-act="挂单">【挂突破条件单】触发价 ${q.trig_px.toFixed(2)} 元</button>
      <button class="action-btn empty${a && a.pick === '空仓' ? ' selected' : ''}" data-act="空仓">【放弃挂单，空仓防守】</button></div>`;
    if (a) {
      const isRight = (a.pick === q.ans);
      h += `<div class="result-card"><div class="result-status ${isRight ? 'correct' : 'wrong'}">${isRight ? '✔ 作答正确！与量化机械定式一致' : '✘ 与量化机械定式不符'} · 定式裁决：${q.ans === '挂单' ? '【挂突破条件单】' : '【放弃挂单，空仓防守】'}</div>
        <div class="result-detail-grid"><div class="metric-box"><div class="metric-box-title">策略打分 / 评级分档</div><div class="metric-box-val" style="color:${q.score >= 90 ? '#dc2626' : '#d97706'};">${q.score > 0 ? q.score + '分' : '未过骨架'} · ${q.tier}</div></div>
        <div class="metric-box"><div class="metric-box-title">盘中突破触发状态</div><div class="metric-box-val">${q.is_triggered ? '盘中触及突破价买入' : '11:30未触及撤单空仓'}</div></div>
        <div class="metric-box"><div class="metric-box-title">真实扣费收益率</div><div class="metric-box-val" style="color:${col(q.net_ret)};">${q.is_triggered ? fmtP(q.net_ret) : '0.00%（未触发）'}</div></div></div>
        <div class="breakdown-box"><b>打分与排雷细项：</b>${q.breakdown_str}</div>
        <div class="breakdown-box"><b>真实成交与卖点轨迹：</b>${q.exit_story} · <b>同期沪深300：</b>${fmtPct(q.csi300_ret)}</div>
        <div class="breakdown-box" style="background:#fffbeb;border-color:#f59e0b;"><b>第一性原理复盘：</b>${q.postmortem}</div></div>`;
    }
    root.innerHTML = h;
    drawK(document.getElementById('kline-canvas'), q.klines, q.open_px, q.post_klines, !!a);
    root.querySelectorAll('[data-act]').forEach(btn => {
      btn.onclick = () => { if (!st[q.id]) { st[q.id] = { pick: btn.dataset.act }; save(); render(); } };
    });
    document.getElementById('btn-prev').onclick = () => { if (cur > 0) { cur--; render(); } };
    document.getElementById('btn-next').onclick = () => { if (cur < DATA.length - 1) { cur++; render(); } };
    document.getElementById('jump-select').onchange = e => { cur = parseInt(e.target.value, 10); render(); };
    document.getElementById('btn-blind').onclick = () => { blind = !blind; render(); };
    document.getElementById('btn-reset').onclick = () => { if (confirm('确定清空本套题库的作答记录？')) { st = {}; save(); render(); } };
  }
  window.addEventListener('keydown', e => {
    const q = DATA[cur];
    if (e.key === '1' || e.key.toUpperCase() === 'A') { if (!st[q.id]) { st[q.id] = { pick: '挂单' }; save(); render(); } }
    else if (e.key === '2' || e.key.toUpperCase() === 'B') { if (!st[q.id]) { st[q.id] = { pick: '空仓' }; save(); render(); } }
    else if (e.key === ' ') { e.preventDefault(); if (cur < DATA.length - 1) { cur++; render(); } }
    else if (e.key.toUpperCase() === 'R') { delete st[q.id]; save(); render(); }
    else if (e.key.toUpperCase() === 'M') { blind = !blind; render(); }
  });
  render();
}
