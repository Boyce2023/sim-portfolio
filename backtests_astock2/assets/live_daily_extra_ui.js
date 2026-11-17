// live_daily_extra_ui.js
// 当日题目全梯队标准化渲染引擎（100%对齐一进二 CSS 设计规范：白底黑线、零圆角、标准红绿灰金四色、统一11列透视表与复盘卡）

(function() {
    function pctColor(v) {
        if (v === null || v === undefined || isNaN(v)) return '#d97706';
        if (v > 0.005) return '#dc2626';
        if (v < -0.005) return '#16a34a';
        return '#374151';
    }

    function rankBadgeHtml(rk) {
        if (!window.showSysRank) return '<span style="color:#9ca3af;font-size:11px;">[已隐藏]</span>';
        let st = 'background:#f3f4f6;color:#374151;border:1px solid #d1d5db;';
        if (rk === 1) st = 'background:#fef3c7;color:#92400e;border:1px solid #f59e0b;font-weight:800;';
        else if (rk === 2) st = 'background:#e0f2fe;color:#0369a1;border:1px solid #38bdf8;font-weight:700;';
        else if (rk === 3) st = 'background:#ecfdf5;color:#047857;border:1px solid #34d399;font-weight:700;';
        return `<span style="padding:2px 6px;font-size:11px;display:inline-block;${st}">综合第 ${rk} 名</span>`;
    }

    function drawSparkKline(cvId, ks) {
        const cv = document.getElementById(cvId);
        if (!cv || !ks || !ks.length) return;
        const ctx = cv.getContext('2d'), W = cv.width, H = cv.height;
        ctx.clearRect(0, 0, W, H);
        let hi = -1e9, lo = 1e9;
        ks.forEach(k => { hi = Math.max(hi, k[1]); lo = Math.min(lo, k[2]); });
        const sp = (hi - lo) > 1e-4 ? (hi - lo) : 1.0;
        const y = v => H - 2 - ((v - lo) / sp) * (H - 4), st = W / ks.length;
        ks.forEach((k, i) => {
            const isTd = (ks.length > 20 && i === ks.length - 1);
            const col = isTd ? '#1d4ed8' : (k[3] >= k[0] ? '#dc2626' : '#16a34a');
            const x = i * st + st * 0.5;
            ctx.strokeStyle = ctx.fillStyle = col;
            ctx.beginPath(); ctx.moveTo(x, y(k[1])); ctx.lineTo(x, y(k[2])); ctx.stroke();
            const t = y(Math.max(k[0], k[3])), b = y(Math.min(k[0], k[3]));
            ctx.fillRect(x - Math.max(1.4, st * 0.3), t, Math.max(2, st * 0.6), Math.max(1.2, b - t));
        });
    }

    function renderWatchlistCompact(wl) {
        const host = document.getElementById('live-watchlist-host');
        if (!host || !wl || !wl.rows) return;
        const rowsHtml = wl.rows.map((r, i) => {
            const capStyle = r.near_cap ? 'color:#dc2626;font-weight:800;' : 'color:#111827;font-weight:700;';
            const aCol = pctColor(r.auc_pct_num), r20Col = pctColor(r.ret20_num);
            const pinTag = r.in_ths ? '<span style="color:#1d4ed8;font-weight:800;margin-right:3px;">★</span>' : '';
            return `<tr>
                <td style="padding:4px 7px;font-weight:700;white-space:nowrap;">${pinTag}${r.name} <span style="color:#6b7280;font-size:11px;font-family:monospace;">${r.c6}</span> ${getPlateBadge(r.code)}</td>
                <td style="padding:4px 7px;font-family:monospace;color:#111827;white-space:nowrap;">${r.mcap_s}</td>
                <td style="padding:4px 7px;color:#374151;font-weight:600;white-space:nowrap;">${r.theme}</td>
                <td style="padding:4px 7px;font-weight:700;color:#111827;white-space:nowrap;">${r.board_s}</td>
                <td style="padding:4px 7px;font-family:monospace;white-space:nowrap;"><span style="${capStyle}">${r.to_cap_s}</span> <span style="color:#6b7280;font-size:11px;">(${r.to_sub_s})</span></td>
                <td style="padding:3px 7px;white-space:nowrap;"><div style="display:flex;align-items:center;gap:6px;"><canvas id="wlk_${i}" width="96" height="20" style="border:1px solid #e5e7eb;background:#ffffff;"></canvas><span style="font-family:monospace;font-size:11px;color:${r20Col};font-weight:700;">${r.trend_s}</span></div></td>
                <td style="padding:4px 7px;font-family:monospace;white-space:nowrap;"><strong style="color:${aCol};">${r.auc_s}</strong> <span style="color:#6b7280;font-size:11px;">${r.cur_s}</span></td>
                <td style="padding:4px 7px;font-family:monospace;color:#111827;white-space:nowrap;"><strong>${r.dd_s}</strong> <span style="color:#6b7280;font-size:11px;">(${r.max_dd_s})</span></td>
            </tr>`;
        }).join('');

        host.innerHTML = `
        <div class="toolbar" style="padding:8px 16px;margin-bottom:12px;">
            <div class="toolbar-group" style="flex-wrap:wrap;">
                <span style="font-weight:800;font-size:12px;color:#111827;">今日全梯队战区导航：</span>
                <a class="toolbar-btn" style="text-decoration:none;" href="#live-watchlist-host">置顶关注池 (${wl.rows.length})</a>
                <a class="toolbar-btn" style="text-decoration:none;" href="#zone-1to2-anchor">战区一：一进二</a>
                <a class="toolbar-btn" style="text-decoration:none;" href="#live-tier-2to3-host">战区二：二进三</a>
                <a class="toolbar-btn" style="text-decoration:none;" href="#live-tier-3to4-host">战区三：三进四</a>
                <a class="toolbar-btn" style="text-decoration:none;" href="#live-tier-high-host">战区四：唯一高标</a>
            </div>
            <span style="font-size:11px;color:#6b7280;">同花顺「置顶」每 1 小时自动同步新票 · 换手上限 = 100% 扣十大流通锁仓</span>
        </div>
        <section class="section-card" style="padding:10px 14px;margin-bottom:14px;">
            <div class="section-header" style="padding-bottom:6px;margin-bottom:8px;">
                <div style="display:flex;align-items:center;gap:8px;"><span class="module-tag">置顶关注池</span><span>我的关注名单全景监控台（★ 为同花顺当前置顶 · 蓝柱为今日最新K线）</span></div>
                <button class="toolbar-btn" onclick="var b=document.getElementById('wl-body-wrap');b.style.display=b.style.display==='none'?'block':'none';" style="font-size:11px;padding:2px 8px;">收起 / 展开</button>
            </div>
            <div id="wl-body-wrap" style="overflow-x:auto;">
                <table class="stocks-table">
                    <thead><tr>
                        <th style="padding:5px 7px;">标的代码与名称</th><th style="padding:5px 7px;">市值 (流/真流/总)</th><th style="padding:5px 7px;">核心题材</th>
                        <th style="padding:5px 7px;">连板与多日多板</th><th style="padding:5px 7px;">换手上限 (扣十大锁仓)</th>
                        <th style="padding:5px 7px;">过去20日走势</th><th style="padding:5px 7px;">09:25竞价</th><th style="padding:5px 7px;">过去20日回撤</th>
                    </tr></thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            </div>
        </section>`;
        wl.rows.forEach((r, i) => drawSparkKline('wlk_' + i, r.klines));
    }

    function buildStandardCandsBlock(prefix, cands, subLabel, pick, onResetAttr) {
        const cols = cands.length === 1 ? 'minmax(320px, 560px)' : `repeat(${Math.min(4, cands.length)}, 1fr)`;
        const klHtml = cands.map(c => {
            const nameHtml = isBlindMode ? `标的 ${c.opt} ${getPlateBadge(c.code)}` : `${c.name} (${c.c6}) ${getPlateBadge(c.code)}`;
            return `<div class="stock-kline-card">
                <div class="stock-kline-header" style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid #e5e7eb;">
                    <div style="display:flex;align-items:center;"><span class="stock-code-tag">${c.opt}</span><span style="font-weight:700;margin-left:6px;color:#111827;">${nameHtml}</span></div>
                    <div style="font-size:11px;color:#6b7280;">${subLabel}</div>
                </div>
                <div id="${prefix}_kl_${c.c6}" style="width:100%;height:185px;"></div>
            </div>`;
        }).join('');

        const tbRows = cands.map(c => {
            const nameHtml = isBlindMode ? `标的 ${c.opt} ${getPlateBadge(c.code)}` : `${c.name} <span style="color:#6b7280;font-size:11px;">${c.code}</span> ${getPlateBadge(c.code)}`;
            return `<tr>
                <td style="font-weight:700;"><span class="stock-code-tag">${c.opt}</span></td>
                <td>${rankBadgeHtml(c.sys_rank)}</td>
                <td style="font-weight:700;color:#111827;">${nameHtml}</td>
                <td style="color:#111827;max-width:220px;white-space:normal;">${c.theme_desc}</td>
                <td style="font-family:monospace;color:#111827;">${c.mcap_main}<br/><span style="font-size:11px;color:#6b7280;">${c.mcap_sub}</span></td>
                <td style="font-family:monospace;color:#111827;"><strong>${c.to_main}</strong><br/><span style="font-size:11px;color:#6b7280;">${c.to_sub}</span></td>
                <td style="font-family:monospace;"><span style="font-weight:700;color:#374151;">${c.tape_main}</span><br/><span style="font-size:11px;color:#6b7280;">${c.tape_sub}</span></td>
                <td style="font-family:monospace;color:#111827;">${c.dd_main}<br/><span style="font-size:11px;color:#6b7280;">${c.dd_sub}</span></td>
                <td style="font-family:monospace;font-weight:700;color:${pctColor(c.o_pct_num)};">${c.auc_s}<br/><span style="font-size:11px;color:#6b7280;font-weight:400;">${c.auc_sub}</span></td>
                <td style="font-family:monospace;color:#374151;font-weight:700;">${c.peer_main}<br/><span style="font-size:11px;color:#6b7280;font-weight:400;">${c.peer_sub}</span></td>
                <td style="font-size:11px;font-weight:700;color:#d97706;">${c.trig_s}</td>
            </tr>`;
        }).join('');

        return `<div class="kline-grid" style="grid-template-columns:${cols};">${klHtml}</div>
            <div style="overflow-x:auto;"><table class="stocks-table"><thead><tr>
                <th style="width:38px;">选项</th><th>量化个股排名</th><th>标的代码与名称</th><th>题材分支与身位</th><th>流通盘 / 昨收锁仓</th>
                <th>换手上限 / 昨换手</th><th>前一日盘口特征</th><th>20日回撤与位置</th><th>09:25竞价</th><th>板块环境与买窗</th><th style="color:#d97706;">执行买点条件</th>
            </tr></thead><tbody>${tbRows}</tbody></table></div>`;
    }

    function buildStandardRevealCard(pick, tierObj, allCands) {
        if (!pick) return '';
        const sameSys = (pick.c6 === 'EMPTY' && !tierObj.sys_c6) || (pick.c6 === tierObj.sys_c6);
        const hBg = sameSys ? '#dcfce7' : '#eff6ff', hBd = sameSys ? '#22c55e' : '#3b82f6', hCol = sameSys ? '#166534' : '#1e40af';
        const pmCols = `repeat(${Math.min(4, Math.max(1, allCands.length))}, 1fr)`;
        const pmItems = allCands.map(x => {
            const isWin = Boolean(tierObj.sys_c6 && x.c6 === tierObj.sys_c6);
            return `<div style="border:1px solid ${isWin ? '#22c55e' : '#e5e7eb'};padding:10px;background:#ffffff;">
                <div style="display:flex;justify-content:space-between;margin-bottom:6px;font-weight:700;color:#111827;">
                    <span>${x.opt} · ${x.name} (${x.c6})</span>
                    <span style="color:${isWin ? '#15803d' : '#6b7280'};">${isWin ? '★ 量化锁定' : x.score_disp}</span>
                </div>
                <div style="font-size:11.5px;background:#f9fafb;border:1px solid #e5e7eb;padding:6px;font-family:monospace;color:#374151;line-height:1.6;">
                    <strong>评分结论：</strong>${x.score_disp}<br/><strong>规则细目：</strong>${x.why}<br/><strong>执行条件：</strong>${x.trig_s}
                </div>
            </div>`;
        }).join('');
        return `<section class="section-card result-card">
            <div class="result-header" style="background:${hBg};border-bottom:2px solid ${hBd};">
                <span style="font-size:15px;font-weight:800;color:${hCol};">${sameSys ? '🤝 人机共振：你的拍板与量化定式裁决一致' : '⚔️ 人机分歧对账卡：盘中实时跟踪'}</span>
                <button class="toolbar-btn" data-reset="1" style="background:#ffffff;border-color:#be123c;color:#be123c;font-weight:700;">🔄 重做本战区</button>
            </div>
            <div style="padding:14px;">
                <div style="font-size:13px;color:#111827;margin-bottom:8px;"><strong>【你的拍板指令】</strong><strong>${pick.label}</strong></div>
                <div style="padding:10px 12px;background:#f8fafc;border:1px solid #cbd5e1;font-size:12.5px;color:#111827;">
                    <strong>【量化定式 09:25 实时裁决】</strong><strong>${tierObj.sys_verdict}</strong><br/>
                    <span style="color:#475569;font-size:11.5px;">过线标准：${tierObj.thr_str}</span>
                </div>
                <div class="postmortem-grid" style="grid-template-columns:${pmCols};padding:12px 0 0 0;">${pmItems}</div>
            </div>
        </section>`;
    }

    function render2to3Section(t23, dateStr) {
        const host = document.getElementById('live-tier-2to3-host');
        if (!host || !t23) return;
        const themes = t23.themes || [];
        const sKey = 'astock2_live23_v3_' + dateStr;
        let curT = 0, pick = null;
        try { pick = JSON.parse(localStorage.getItem(sKey) || 'null'); } catch(e) {}

        function paint() {
            const thCols = `repeat(${Math.min(4, Math.max(1, themes.length))}, 1fr)`;
            const thCards = themes.map((th, idx) => {
                const sel = (idx === curT);
                return `<div class="theme-card ${sel ? 'selected' : ''}" data-tidx="${idx}">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;gap:4px;flex-wrap:wrap;">
                        <span style="background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;font-weight:700;font-size:11px;padding:2px 6px;">${th.elo_badge}</span>
                        <span style="font-size:10px;padding:2px 6px;font-weight:700;${sel ? 'background:#111827;color:#fde68a;' : 'background:#f3f4f6;color:#4b5563;'}">${sel ? '✓ 当前锁定题材' : '点击查看 ' + th.cands.length + ' 只二板股'}</span>
                    </div>
                    <div style="font-size:16px;font-weight:800;color:#111827;margin-bottom:6px;">${th.name}</div>
                    <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;"><span style="color:#6b7280;">题材阶段定位</span><strong style="color:#111827;">${th.stage_str}</strong></div>
                    <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;"><span style="color:#6b7280;">昨日板块涨停数</span><strong style="color:#111827;">${th.p_sz} 家</strong></div>
                    <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;"><span style="color:#6b7280;">同板块高标压制</span><strong style="color:#111827;">${th.p3b_str}</strong></div>
                    <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;"><span style="color:#6b7280;">板块二板竞价均幅</span><strong style="color:${pctColor(th.avg_open_num)};font-family:monospace;">${th.avg_open_str}</strong></div>
                    <div id="t23_heat_${idx}" style="margin-top:6px;"></div>
                </div>`;
            }).join('');

            const curTh = themes[curT] || { name: '无', cands: [] };
            const btnCols = `repeat(${Math.min(5, curTh.cands.length + 1)}, 1fr)`;
            const btns = curTh.cands.map(c => `<button class="choice-btn ${pick && pick.c6===c.c6 ? 'selected-choice' : ''}" data-c6="${c.c6}" data-lbl="选项 ${c.opt}：${c.name} (${curTh.name})">【选择标的 ${c.opt} · ${isBlindMode ? '盲测标的' : c.name}】</button>`).join('')
                + `<button class="choice-btn btn-empty ${pick && pick.c6==='EMPTY' ? 'selected-choice' : ''}" data-c6="EMPTY" data-lbl="选项 E：二进三空仓休息">【选择标的 E · 二进三空仓】</button>`;
            const allCands = themes.reduce((a, t) => a.concat(t.cands), []);

            host.innerHTML = `
            <div class="case-banner" style="margin-top:24px;">
                <div><div class="case-title">⚡ 战区二：${dateStr} 实时「二进三」早盘决战局</div><div class="case-sub">迷茫暗牌弱转强 V1.0 定式 · 聚焦温热板块(2至6家)/老主线二波回流/无三板压制 · 09:25 竞价直买</div></div>
                <div class="case-phase-pill">标准门槛 90 分 · 满 96 分重点提醒</div>
            </div>
            <section class="section-card"><div class="section-header"><span><span class="module-tag" style="margin-right:6px;">模块二</span>二进三题材战场分卡（点击哪张题材卡，下方即刻切换为该题材旗下的候选二板股）</span><span style="font-size:11px;color:#d97706;font-weight:700;">★ 题材左右顺序已随机洗牌</span></div><div class="themes-grid" style="grid-template-columns:${thCols};">${thCards}</div></section>
            <section class="section-card"><div class="section-header"><span><span class="module-tag" style="margin-right:6px;">模块三</span>当前查看：【<strong style="color:#d97706;">${curTh.name}</strong>】旗下的 ${curTh.cands.length} 只候选二板股全景对比</span><span style="font-size:11px;color:#6b7280;">买窗跌6.5%至+2.5% · 换手上限为扣十大锁仓后上限</span></div>${buildStandardCandsBlock('t23', curTh.cands, curTh.name, pick)}</section>
            <section class="section-card" style="border:2px solid #111827;background:#ffffff;"><div class="section-header" style="border-bottom:1px solid #111827;"><span style="font-size:14px;color:#111827;"><span class="module-tag" style="margin-right:6px;">模块四</span>二进三决策拍板（请下达唯一指令）</span><span style="font-size:12px;color:#4b5563;">09:25 竞价直买：未封三板次日高开不足0.5%竞价止损否则收盘清，封三板走次日13:45护利</span></div><div class="action-buttons" style="grid-template-columns:${btnCols};">${btns}</div></section>
            ${buildStandardRevealCard(pick, t23, allCands)}`;

            themes.forEach((th, idx) => renderMiniHeat('t23_heat_' + idx, th.heat_bars));
            curTh.cands.forEach(c => renderCompactKLine('t23_kl_' + c.c6, c.klines, c.d2_bar, null, false));
            host.querySelectorAll('.theme-card').forEach(el => { el.onclick = () => { curT = +el.getAttribute('data-tidx'); paint(); }; });
            host.querySelectorAll('.choice-btn').forEach(b => { b.onclick = () => { pick = { c6: b.getAttribute('data-c6'), label: b.getAttribute('data-lbl') }; try { localStorage.setItem(sKey, JSON.stringify(pick)); } catch(e) {} paint(); }; });
            const rb = host.querySelector('[data-reset]'); if (rb) rb.onclick = () => { pick = null; try { localStorage.removeItem(sKey); } catch(e) {} paint(); };
        }
        paint();
    }

    function renderDirectSection(hostId, prefix, zoneTitle, zoneSub, pillTxt, modTitle, execHint, emptyLbl, tierObj, sKey) {
        const host = document.getElementById(hostId);
        if (!host || !tierObj) return;
        const cands = tierObj.cands || [];
        let pick = null;
        try { pick = JSON.parse(localStorage.getItem(sKey) || 'null'); } catch(e) {}

        function paint() {
            const btnCols = `repeat(${Math.min(5, cands.length + 1)}, 1fr)`;
            const btns = cands.map(c => `<button class="choice-btn ${pick && pick.c6===c.c6 ? 'selected-choice' : ''}" data-c6="${c.c6}" data-lbl="选项 ${c.opt}：${c.name} (${c.c6})">【选择标的 ${c.opt} · ${isBlindMode ? '盲测标的' : c.name}】</button>`).join('')
                + `<button class="choice-btn btn-empty ${pick && pick.c6==='EMPTY' ? 'selected-choice' : ''}" data-c6="EMPTY" data-lbl="选项 E：${emptyLbl}">【选择标的 E · ${emptyLbl}】</button>`;

            host.innerHTML = `
            <div class="case-banner" style="margin-top:24px;">
                <div><div class="case-title">${zoneTitle}</div><div class="case-sub">${zoneSub}</div></div>
                <div class="case-phase-pill">${pillTxt}</div>
            </div>
            <section class="section-card"><div class="section-header"><span><span class="module-tag" style="margin-right:6px;">候选透视</span>${modTitle}</span><span style="font-size:11px;color:#6b7280;">换手上限 = 100% 扣十大流通锁仓股东</span></div>${cands.length ? buildStandardCandsBlock(prefix, cands, pillTxt, pick) : '<div style="padding:14px;color:#6b7280;font-weight:700;">今日全市场无该梯队候选标的，直接执行空仓休息。</div>'}</section>
            <section class="section-card" style="border:2px solid #111827;background:#ffffff;"><div class="section-header" style="border-bottom:1px solid #111827;"><span style="font-size:14px;color:#111827;"><span class="module-tag" style="margin-right:6px;">决策拍板</span>请下达本战区唯一指令</span><span style="font-size:12px;color:#4b5563;">${execHint}</span></div><div class="action-buttons" style="grid-template-columns:${btnCols};">${btns}</div></section>
            ${buildStandardRevealCard(pick, tierObj, cands)}`;

            cands.forEach(c => renderCompactKLine(prefix + '_kl_' + c.c6, c.klines, c.d2_bar, null, false));
            host.querySelectorAll('.choice-btn').forEach(b => { b.onclick = () => { pick = { c6: b.getAttribute('data-c6'), label: b.getAttribute('data-lbl') }; try { localStorage.setItem(sKey, JSON.stringify(pick)); } catch(e) {} paint(); }; });
            const rb = host.querySelector('[data-reset]'); if (rb) rb.onclick = () => { pick = null; try { localStorage.removeItem(sKey); } catch(e) {} paint(); };
        }
        paint();
    }

    const _origRenderCase = window.renderCurrentCase;
    window.renderCurrentCase = function(preserveThemeIdx) {
        _origRenderCase(preserveThemeIdx);
        if (!allCases || !allCases.length || !allCases[0].extra_live_sections) return;
        const cs = allCases[0], ex = cs.extra_live_sections;
        renderWatchlistCompact(ex.watchlist);
        render2to3Section(ex.tier_2to3, cs.date);
        renderDirectSection('live-tier-3to4-host', 't34', `⚡ 战区三：${cs.date} 实时「三进四」早盘决战局`, '全市场三连板候选一只不漏全量展示 · V3.4 实盘主战定式', '标准主力门槛 90 分', `全市场 ${ex.tier_3to4.cands.length} 只三连板候选全景对比`, '09:26 按 max(昨收×1.065, 今开) 预埋突破条件单 · 11:30 未触及午休撤单', '三进四空仓', ex.tier_3to4, 'astock2_live34_v3_' + cs.date);
        renderDirectSection('live-tier-high-host', 'thi', `👑 战区四：${cs.date} 实时「唯一高标」早盘决战局`, '严格只取全场唯一第 1 名最高标（跟风老二一律剔除） · 二选一盲测拍板', '高标首阴 88 分 / 四进五 120 分', '全场唯一第 1 名最高标全景透视', '高标首阴 V5.1 真阳承接或四进五甜区达标才出手 · 封板次日预埋 93% 异动止盈单', '高标空仓', ex.tier_high, 'astock2_livehi_v3_' + cs.date);
    };
})();
