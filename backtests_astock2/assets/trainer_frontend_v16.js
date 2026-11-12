// trainer_frontend_v16.js
// A股「一进二」量化机械定式盘感刷题机前端核心业务引擎

let allCases = [];
let currentFilterMode = 'all';
let filteredIndices = [];
let activePointer = 0;
let isBlindMode = false;
let currentSelectedThemeIdx = 0;
window.showSysRank = true; // 量化综合排名参考默认开启

// 本地统计与历史存档
const STATS_KEY = 'astock2_trainer_stats_5y';
let userStats = {
    totalAnswered: 0,
    correctCount: 0,
    avoidTrapCount: 0,
    beatSystemCount: 0,
    cumNav: 1.0,
    systemNav: 1.0,
    history: {},
    wrongCaseIds: []
};

function loadStats() {
    try {
        const raw = localStorage.getItem(STATS_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            userStats = Object.assign(userStats, parsed);
        }
    } catch (e) {
        console.warn('Failed to load stats from localStorage:', e);
    }
}

function saveStats() {
    try {
        localStorage.setItem(STATS_KEY, JSON.stringify(userStats));
    } catch (e) {
        console.warn('Failed to save stats to localStorage:', e);
    }
}

function updateStatsUI() {
    const totalEl = document.getElementById('stat-total');
    if (totalEl) totalEl.textContent = userStats.totalAnswered;
    const acc = userStats.totalAnswered > 0 ? (userStats.correctCount / userStats.totalAnswered * 100).toFixed(1) : '0.0';
    const accEl = document.getElementById('stat-acc');
    if (accEl) accEl.textContent = `${acc}%`;
    const navEl = document.getElementById('stat-nav');
    if (navEl) {
        navEl.textContent = `${((userStats.cumNav - 1.0) * 100).toFixed(2)}%`;
        if (userStats.cumNav >= 1.0) {
            navEl.style.color = '#dc2626';
        } else {
            navEl.style.color = '#16a34a';
        }
    }
    const sysNavEl = document.getElementById('stat-sys-nav');
    if (sysNavEl) sysNavEl.textContent = `${((userStats.systemNav - 1.0) * 100).toFixed(2)}%`;
    const beatsEl = document.getElementById('stat-beats');
    if (beatsEl) beatsEl.textContent = `${userStats.beatSystemCount} 次`;
}

function recomputeStatsFromHistory() {
    const caseMap = {};
    allCases.forEach(item => { caseMap[item.id] = item; });
    let total = 0, correct = 0, avoid = 0, beats = 0;
    let cNav = 1.0, sNav = 1.0;
    const wrongs = [];
    Object.keys(userStats.history).map(k => parseInt(k, 10)).sort((a, b) => a - b).forEach(cid => {
        const h = userStats.history[cid];
        const cs = caseMap[cid];
        if (!h || !cs) return;
        total++;
        let uProf = 0.0;
        let isCorr = false;
        if (h.choice === 'E') {
            uProf = 0.0;
            isCorr = (cs.market_ans === 'E');
        } else {
            const tIdx = h.themeIdx || 0;
            const thObj = cs.themes[tIdx];
            const picked = thObj ? thObj.cands.find(cd => cd.opt === h.choice) : null;
            if (picked) {
                uProf = (picked.net_ret || 0.0) / 100.0;
                isCorr = (tIdx === cs.market_best_theme_idx && h.choice === cs.market_ans);
            }
        }
        h.userProfit = uProf;
        h.isCorrect = isCorr;
        const sProf = (cs.sys_ret || 0.0) / 100.0;
        if (isCorr) {
            correct++;
            avoid++;
        } else {
            wrongs.push(cid);
        }
        if (uProf > sProf) beats++;
        cNav *= (1.0 + uProf);
        sNav *= (1.0 + sProf);
    });
    userStats.totalAnswered = total;
    userStats.correctCount = correct;
    userStats.avoidTrapCount = avoid;
    userStats.beatSystemCount = beats;
    userStats.cumNav = cNav;
    userStats.systemNav = sNav;
    userStats.wrongCaseIds = wrongs;
}

function resetCurrentCase() {
    if (filteredIndices.length === 0) return;
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c) return;
    stopVoiceExplain();
    if (userStats.history[c.id]) {
        delete userStats.history[c.id];
        recomputeStatsFromHistory();
        saveStats();
        updateStatsUI();
    }
    renderCurrentCase();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetStats() {
    if (confirm('确认清空所有作答记录、累计净值和错题本？清空后将从第 1 关重新开始。')) {
        stopVoiceExplain();
        localStorage.removeItem(STATS_KEY);
        userStats = {
            totalAnswered: 0,
            correctCount: 0,
            avoidTrapCount: 0,
            beatSystemCount: 0,
            cumNav: 1.0,
            systemNav: 1.0,
            history: {},
            wrongCaseIds: []
        };
        updateStatsUI();
        applyFilterMode('all');
    }
}


// ============================================================================
// 原生 SpeechSynthesis 普通话语音讲题控制器 [V]（盘前审题 + 盘后复盘）
// ============================================================================
let isVoiceSpeaking = false;
let currentUtterance = null;

function stopVoiceExplain() {
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    isVoiceSpeaking = false;
    updateVoiceButtonUI(false);
}

function updateVoiceButtonUI(speaking) {
    const btnTop = document.getElementById('btn-tts');
    const btnResult = document.getElementById('btn-tts-result');
    if (btnTop) {
        if (speaking) {
            btnTop.textContent = '⏹ 停止讲题 [V]';
            btnTop.style.background = '#fee2e2';
            btnTop.style.borderColor = '#ef4444';
            btnTop.style.color = '#b91c1c';
        } else {
            btnTop.textContent = '🔊 语音讲题 [V]';
            btnTop.style.background = '#fef3c7';
            btnTop.style.borderColor = '#f59e0b';
            btnTop.style.color = '#92400e';
        }
    }
    if (btnResult) {
        if (speaking) {
            btnResult.textContent = '⏹ 停止复盘';
            btnResult.style.background = '#fee2e2';
            btnResult.style.borderColor = '#ef4444';
            btnResult.style.color = '#b91c1c';
        } else {
            btnResult.textContent = '🔊 语音复盘本题';
            btnResult.style.background = '#ffffff';
            btnResult.style.borderColor = '#d97706';
            btnResult.style.color = '#92400e';
        }
    }
}

function toggleVoiceExplain() {
    if (!('speechSynthesis' in window)) {
        alert('当前浏览器未启用语音合成服务，请在现代浏览器中尝试。');
        return;
    }
    
    if (window.speechSynthesis.speaking || isVoiceSpeaking) {
        stopVoiceExplain();
        return;
    }
    
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c) return;
    
    const hasAnswered = (userStats.history[c.id] !== undefined);
    let speechText = '';
    
    if (!hasAnswered) {
        // 100% 零剧透盘前审题播报（深度紧扣周几、封板率、近5日自然晋级率、总盘子、首封与炸板、竞价排名与领先差距）
        const weekStr = c.weekday_str ? `${c.weekday_str}` : '';
        const dateStr = isBlindMode ? `当前为盲测决战切面，交易日为${weekStr || '周内交易日'}` : `决战日为 ${c.date} ${weekStr} 集合竞价切面`;
        const sent = c.sent || [];
        const th0 = c.themes[0] ? c.themes[0].name : '';
        const th1 = c.themes[1] ? c.themes[1].name : '';
        const th2 = c.themes[2] ? c.themes[2].name : '';
        
        const promoStr = sent[3] ? `，一进二封板率${sent[3]}` : '';
        const rawMa5 = c.promo_ma5_raw || String(c.promo_ma5_str || '').split(' ')[0];
        const promoMa5Str = rawMa5 ? `，近5日自然晋级率${rawMa5}` : '';
        const yiziStr = (c.mkt_yizi_cnt !== undefined) ? `，全场一字二板${c.mkt_yizi_cnt}家` : '';
        
        let candsDesc = '';
        const curTh = c.themes[currentSelectedThemeIdx];
        if (curTh && curTh.cands) {
            candsDesc = `当前锁定【${curTh.name}】题材。旗下候选首板股盘面特征为：`;
            curTh.cands.forEach(cd => {
                const namePart = isBlindMode ? `标的${cd.opt}` : `标的${cd.opt}，${cd.name}`;
                const mcapPart = `总盘子${cd.mcap}亿`;
                const sealPart = cd.raw_d1_board ? `，前一日${cd.raw_d1_board}` : '';
                const openPart = `，竞价涨幅${cd.o_pct >= 0 ? '+' : ''}${cd.o_pct.toFixed(1)}%`;
                const rkArr = cd.raw_rk || cd.rk;
                const rkPart = rkArr ? `，板块竞价第${rkArr[0]}名，全场第${rkArr[1]}名` : '';
                const leadVal = (cd.raw_lead !== undefined) ? cd.raw_lead : cd.lead;
                const leadPart = (leadVal !== undefined) ? `，较前序差幅${leadVal >= 0 ? '+' : ''}${leadVal.toFixed(1)}%` : '';
                candsDesc += `${namePart}，${mcapPart}${sealPart}${openPart}${rkPart}${leadPart}。`;
            });
        }
        
        const thBrief = c.themes.map(th => {
            const pAvg = (th.d1_plate_avg_pct !== undefined) ? `，前一日板块收盘均幅${th.d1_plate_avg_pct >= 0 ? '+' : ''}${th.d1_plate_avg_pct.toFixed(2)}%` : '';
            return `【${th.name}】（题材分第${th.elo_rank}名${th.elo_score}分${pAvg}）`;
        }).join('、');
        
        speechText = `${dateStr}。昨日投机情绪：涨停${sent[0] || 0}家，跌停${sent[1] || 0}家，首板${sent[2] || 0}家${promoStr}${promoMa5Str}，连板高度${sent[4] || 0}板${yiziStr}。今日聚焦三大主线战场：${thBrief}。${candsDesc}请根据点火确认条件与全场风偏，果断下达狙击指令或选择全场空仓避险。`;
    } else {
        // 深度盘后复盘讲题播报
        const histRec = userStats.history[c.id];
        const userChoice = histRec ? histRec.choice : '未作答';
        const isCorrect = histRec ? histRec.isCorrect : false;
        
        let verdictSpeech = '';
        if (isCorrect) {
            verdictSpeech = `你的选择是选项${userChoice}，恭喜你精准锁定全场最优决策！`;
        } else {
            verdictSpeech = `你的选择是选项${userChoice}，未能捕捉到全场最佳机会。`;
        }
        
        let marketResultSpeech = '';
        if (c.market_ans === 'E') {
            marketResultSpeech = `今日全场冲高回落，所有首板标的均缺乏持续晋级动能。最佳策略是【选择 E 全场空仓防守】，空仓保住本金也是顶尖盘感！`;
        } else {
            const bestTh = c.themes[c.market_best_theme_idx];
            const thName = bestTh ? bestTh.name : '';
            marketResultSpeech = `今日全场胜出的真龙主线为【${thName}】，市场最优标的是【选项 ${c.market_ans} ${c.best_stock_name}】，次日开盘兑现净收益高达百分之${c.market_best_ret.toFixed(2)}！`;
        }
        
        let sysSpeech = `量化机械定式今日动作：${c.sys_cand_name}，实现净收益百分之${c.sys_ret.toFixed(2)}。`;
        if (c.sys_beat) {
            sysSpeech += '你在本题成功击败了量化机械定式！';
        } else {
            sysSpeech += '量化定式保持稳健防守。';
        }
        
        let candsExplain = '';
        const curTh = c.themes[currentSelectedThemeIdx];
        if (curTh && curTh.cands) {
            candsExplain = `当前题材候选股成败归因：`;
            curTh.cands.forEach(cd => {
                candsExplain += `标的${cd.opt}${cd.name}：${cd.pm_comment || cd.exit_reason || ''}。`;
            });
        }
        
        speechText = `深度复盘讲解：${verdictSpeech}${marketResultSpeech}${sysSpeech}${candsExplain}`;
    }
    
    const utterance = new SpeechSynthesisUtterance(speechText);
    utterance.rate = 1.08;
    utterance.pitch = 1.0;
    
    const voices = window.speechSynthesis.getVoices();
    let zhVoice = voices.find(v => v.lang && v.lang.startsWith('zh') && (v.name.includes('Tingting') || v.name.includes('Meijia') || v.name.includes('Xiaoxiao') || v.name.includes('Sinji')));
    if (!zhVoice) {
        zhVoice = voices.find(v => v.lang && v.lang.startsWith('zh'));
    }
    if (zhVoice) {
        utterance.voice = zhVoice;
    }
    
    utterance.onstart = () => {
        isVoiceSpeaking = true;
        updateVoiceButtonUI(true);
    };
    utterance.onend = () => {
        isVoiceSpeaking = false;
        updateVoiceButtonUI(false);
    };
    utterance.onerror = () => {
        isVoiceSpeaking = false;
        updateVoiceButtonUI(false);
    };
    
    currentUtterance = utterance;
    window.speechSynthesis.speak(utterance);
}


// 极速 SVG K 线渲染器（基于紧凑五元组 [open, high, low, close, volume]）
function renderCompactKLine(containerId, bars, d2Bar, d3Bar, isIndex = false) {
    const el = document.getElementById(containerId);
    if (!el || !bars || bars.length === 0) return;
    
    const allBars = [...bars];
    if (d2Bar) allBars.push(d2Bar);
    if (d3Bar) allBars.push(d3Bar);
    
    const width = el.clientWidth || (isIndex ? 720 : 310);
    const height = isIndex ? 240 : 185;
    const padding = { top: 20, right: isIndex ? 45 : 35, bottom: isIndex ? 22 : 25, left: 10 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;
    const klineH = chartH * 0.72;
    const volH = chartH * 0.22;
    const volTop = padding.top + klineH + chartH * 0.06;
    
    let ma5Vals = [];
    let ma20Vals = [];
    let minP = Infinity, maxP = -Infinity, maxVol = 0;
    
    allBars.forEach((b, idx) => {
        if (b[1] > maxP) maxP = b[1];
        if (b[2] < minP) minP = b[2];
        if (b[4] > maxVol) maxVol = b[4];
        
        if (isIndex) {
            if (idx >= 4) {
                const s = allBars.slice(idx - 4, idx + 1).reduce((acc, x) => acc + x[3], 0) / 5;
                ma5Vals.push(s);
                if (s > maxP) maxP = s;
                if (s < minP) minP = s;
            } else {
                ma5Vals.push(null);
            }
            if (idx >= 19) {
                const s = allBars.slice(idx - 19, idx + 1).reduce((acc, x) => acc + x[3], 0) / 20;
                ma20Vals.push(s);
                if (s > maxP) maxP = s;
                if (s < minP) minP = s;
            } else {
                ma20Vals.push(null);
            }
        }
    });
    
    minP *= 0.994;
    maxP *= 1.006;
    if (maxVol <= 0) maxVol = 1;
    
    const n = allBars.length;
    const barW = Math.max(2.5, chartW / n - (isIndex ? 2 : 1.5));
    
    function yP(p) { return padding.top + klineH - ((p - minP) / (maxP - minP)) * klineH; }
    function yV(v) { return volTop + volH - (v / maxVol) * volH; }
    
    let svg = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" style="background:#ffffff;display:block;">`;
    
    const gridRows = isIndex ? 3 : 2;
    for (let i = 0; i <= gridRows; i++) {
        const p = minP + (maxP - minP) * (i / gridRows);
        const y = yP(p);
        svg += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#f3f4f6" stroke-width="1"/>`;
        svg += `<text x="${width - padding.right + 3}" y="${y + 3}" font-size="${isIndex ? 10 : 9}" fill="#9ca3af" font-family="monospace">${p.toFixed(isIndex ? 0 : 2)}</text>`;
    }
    
    let ma5Path = '';
    let ma20Path = '';
    
    allBars.forEach((b, idx) => {
        const x = padding.left + (idx + 0.5) * (chartW / n);
        const isUp = b[3] >= b[0];
        const isD2 = (idx === bars.length);
        const isD3 = (idx === bars.length + 1);
        
        let color = isUp ? '#dc2626' : '#16a34a';
        let strokeW = 1;
        if (isD2 || isD3) {
            color = isUp ? '#b91c1c' : '#047857';
            strokeW = 1.8;
        }
        
        const topY = yP(Math.max(b[0], b[3]));
        const botY = yP(Math.min(b[0], b[3]));
        const bodyH = Math.max(1.2, botY - topY);
        const highY = yP(b[1]);
        const lowY = yP(b[2]);
        
        svg += `<line x1="${x}" y1="${highY}" x2="${x}" y2="${lowY}" stroke="${color}" stroke-width="${strokeW}"/>`;
        svg += `<rect x="${x - barW/2}" y="${topY}" width="${barW}" height="${bodyH}" fill="${color}"/>`;
        
        const vy = yV(b[4]);
        const vH = Math.max(1, volTop + volH - vy);
        svg += `<rect x="${x - barW/2}" y="${vy}" width="${barW}" height="${vH}" fill="${color}" opacity="0.8"/>`;
        
        if (isIndex) {
            if (ma5Vals[idx] !== null) {
                const my5 = yP(ma5Vals[idx]);
                ma5Path += `${ma5Path ? 'L' : 'M'} ${x.toFixed(1)} ${my5.toFixed(1)} `;
            }
            if (ma20Vals[idx] !== null) {
                const my20 = yP(ma20Vals[idx]);
                ma20Path += `${ma20Path ? 'L' : 'M'} ${x.toFixed(1)} ${my20.toFixed(1)} `;
            }
        }
        
        if (isD2) {
            svg += `<line x1="${x - barW}" y1="${padding.top}" x2="${x - barW}" y2="${height - padding.bottom}" stroke="#d97706" stroke-width="1.2" stroke-dasharray="2,2"/>`;
            svg += `<text x="${x}" y="${padding.top - 5}" font-size="9" fill="#d97706" font-weight="700">D2揭晓</text>`;
        }
        if (isD3) {
            svg += `<text x="${x}" y="${padding.top - 5}" font-size="9" fill="#d97706" font-weight="700">D3</text>`;
        }
    });
    
    if (isIndex) {
        if (ma5Path) svg += `<path d="${ma5Path}" fill="none" stroke="#f59e0b" stroke-width="1.5"/>`;
        if (ma20Path) svg += `<path d="${ma20Path}" fill="none" stroke="#3b82f6" stroke-width="1.5"/>`;
        svg += `<text x="${padding.left + 5}" y="${padding.top - 6}" font-size="11" fill="#f59e0b" font-weight="700">MA5</text>`;
        svg += `<text x="${padding.left + 45}" y="${padding.top - 6}" font-size="11" fill="#3b82f6" font-weight="700">MA20</text>`;
        svg += `<text x="${padding.left + 90}" y="${padding.top - 6}" font-size="10" fill="#6b7280">（真实红绿蜡烛 + 均线 + 成交量）</text>`;
    }
    
    svg += `</svg>`;
    el.innerHTML = svg;
}

// 上证指数前 6 个月（约 125 交易日）大势日 K 线绘制引擎（MA20蓝线 + MA60紫线 + 顶底点位标注）
function renderIndex6MKLine(containerId, bars125, d2Bar = null) {
    const el = document.getElementById(containerId);
    if (!el || !bars125 || bars125.length === 0) return;
    
    const allBars = d2Bar ? [...bars125, d2Bar] : [...bars125];
    const width = el.clientWidth || 520;
    const height = 230;
    const padding = { top: 22, right: 38, bottom: 22, left: 8 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;
    const klineH = chartH * 0.72;
    const volH = chartH * 0.22;
    const volTop = padding.top + klineH + chartH * 0.06;
    
    let minP = Infinity, maxP = -Infinity, maxVol = 0;
    let highP = -Infinity, lowP = Infinity;
    
    allBars.forEach(b => {
        const h = b[2], l = b[3], ma20 = b[7], ma60 = b[8], v = b[5];
        if (h > highP) highP = h;
        if (l < lowP) lowP = l;
        if (h > maxP) maxP = h;
        if (l < minP) minP = l;
        if (ma20 !== null && ma20 !== undefined) {
            if (ma20 > maxP) maxP = ma20;
            if (ma20 < minP) minP = ma20;
        }
        if (ma60 !== null && ma60 !== undefined) {
            if (ma60 > maxP) maxP = ma60;
            if (ma60 < minP) minP = ma60;
        }
        if (v > maxVol) maxVol = v;
    });
    
    minP *= 0.994;
    maxP *= 1.006;
    if (maxVol <= 0) maxVol = 1;
    
    const rangeEl = document.getElementById('sh-halfyear-range');
    if (rangeEl && highP > -Infinity && lowP < Infinity) {
        rangeEl.textContent = `高 ${Math.round(highP)} / 低 ${Math.round(lowP)}`;
    }
    
    const n = allBars.length;
    const barW = Math.max(1.8, (chartW / n) - 1.2);
    
    function yP(p) { return padding.top + klineH - ((p - minP) / (maxP - minP)) * klineH; }
    function yV(v) { return volTop + volH - (v / maxVol) * volH; }
    
    let svg = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" style="background:#ffffff;display:block;">`;
    
    for (let i = 0; i <= 3; i++) {
        const p = minP + (maxP - minP) * (i / 3);
        const y = yP(p);
        svg += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#f3f4f6" stroke-width="1"/>`;
        svg += `<text x="${width - padding.right + 3}" y="${y + 3}" font-size="9" fill="#9ca3af" font-family="monospace">${p.toFixed(0)}</text>`;
    }
    
    let ma20Path = '';
    let ma60Path = '';
    
    allBars.forEach((b, idx) => {
        const x = padding.left + (idx + 0.5) * (chartW / n);
        const o = b[1], h = b[2], l = b[3], c = b[4], v = b[5], ma20 = b[7], ma60 = b[8];
        const isUp = c >= o;
        const isD2 = (idx === bars125.length);
        
        let color = isUp ? '#dc2626' : '#16a34a';
        let strokeW = 1;
        if (isD2) {
            color = isUp ? '#b91c1c' : '#047857';
            strokeW = 1.6;
        }
        
        const topY = yP(Math.max(o, c));
        const botY = yP(Math.min(o, c));
        const bodyH = Math.max(1.0, botY - topY);
        const highY = yP(h);
        const lowY = yP(l);
        
        svg += `<line x1="${x.toFixed(1)}" y1="${highY.toFixed(1)}" x2="${x.toFixed(1)}" y2="${lowY.toFixed(1)}" stroke="${color}" stroke-width="${strokeW}"/>`;
        svg += `<rect x="${(x - barW/2).toFixed(1)}" y="${topY.toFixed(1)}" width="${barW.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}"/>`;
        
        const vy = yV(v);
        const vH = Math.max(1, volTop + volH - vy);
        svg += `<rect x="${(x - barW/2).toFixed(1)}" y="${vy.toFixed(1)}" width="${barW.toFixed(1)}" height="${vH.toFixed(1)}" fill="${color}" opacity="0.75"/>`;
        
        if (ma20 !== null && ma20 !== undefined) {
            const my20 = yP(ma20);
            ma20Path += `${ma20Path ? 'L' : 'M'} ${x.toFixed(1)} ${my20.toFixed(1)} `;
        }
        if (ma60 !== null && ma60 !== undefined) {
            const my60 = yP(ma60);
            ma60Path += `${ma60Path ? 'L' : 'M'} ${x.toFixed(1)} ${my60.toFixed(1)} `;
        }
        
        if (isD2) {
            svg += `<line x1="${(x - barW).toFixed(1)}" y1="${padding.top}" x2="${(x - barW).toFixed(1)}" y2="${height - padding.bottom}" stroke="#d97706" stroke-width="1.2" stroke-dasharray="2,2"/>`;
            svg += `<text x="${x.toFixed(1)}" y="${padding.top - 5}" font-size="9" fill="#d97706" font-weight="700">D2</text>`;
        }
        
        if (idx === 0) {
            svg += `<text x="${x.toFixed(1)}" y="${height - 6}" font-size="9" fill="#9ca3af">${b[0].slice(2, 7)}</text>`;
        } else if (idx === Math.floor(bars125.length / 2)) {
            svg += `<text x="${x.toFixed(1)}" y="${height - 6}" font-size="9" fill="#9ca3af" text-anchor="middle">${b[0].slice(2, 7)}</text>`;
        } else if (idx === bars125.length - 1) {
            svg += `<text x="${x.toFixed(1)}" y="${height - 6}" font-size="9" fill="#4b5563" font-weight="700" text-anchor="end">${b[0].slice(5)}</text>`;
        }
    });
    
    if (ma20Path) svg += `<path d="${ma20Path}" fill="none" stroke="#3b82f6" stroke-width="1.3"/>`;
    if (ma60Path) svg += `<path d="${ma60Path}" fill="none" stroke="#9333ea" stroke-width="1.3"/>`;
    
    svg += `<text x="${padding.left + 5}" y="${padding.top - 7}" font-size="10" fill="#3b82f6" font-weight="700">MA20</text>`;
    svg += `<text x="${padding.left + 42}" y="${padding.top - 7}" font-size="10" fill="#9333ea" font-weight="700">MA60</text>`;
    svg += `<text x="${padding.left + 80}" y="${padding.top - 7}" font-size="10" fill="#dc2626" font-weight="700">半年高点 ${Math.round(highP)}</text>`;
    svg += `<text x="${padding.left + 160}" y="${padding.top - 7}" font-size="10" fill="#16a34a" font-weight="700">半年低点 ${Math.round(lowP)}</text>`;
    
    svg += `</svg>`;
    el.innerHTML = svg;
}

// 上证指数前 30 日短线日 K 线绘制引擎（MA5橙线 + MA20蓝线 + 虚线后作答揭晓）
function renderIndex30DKLine(containerId, bars30, d2Bar = null) {
    const el = document.getElementById(containerId);
    if (!el || !bars30 || bars30.length === 0) return;
    
    const allBars = d2Bar ? [...bars30, d2Bar] : [...bars30];
    const width = el.clientWidth || 490;
    const height = 230;
    const padding = { top: 22, right: 38, bottom: 22, left: 8 };
    const chartW = width - padding.left - padding.right;
    const chartH = height - padding.top - padding.bottom;
    const klineH = chartH * 0.72;
    const volH = chartH * 0.22;
    const volTop = padding.top + klineH + chartH * 0.06;
    
    let minP = Infinity, maxP = -Infinity, maxVol = 0;
    
    allBars.forEach(b => {
        const h = b[2], l = b[3], ma5 = b[6], ma20 = b[7], v = b[5];
        if (h > maxP) maxP = h;
        if (l < minP) minP = l;
        if (ma5 !== null && ma5 !== undefined) {
            if (ma5 > maxP) maxP = ma5;
            if (ma5 < minP) minP = ma5;
        }
        if (ma20 !== null && ma20 !== undefined) {
            if (ma20 > maxP) maxP = ma20;
            if (ma20 < minP) minP = ma20;
        }
        if (v > maxVol) maxVol = v;
    });
    
    minP *= 0.994;
    maxP *= 1.006;
    if (maxVol <= 0) maxVol = 1;
    
    const n = allBars.length;
    const barW = Math.max(3.2, (chartW / n) - 2.2);
    
    function yP(p) { return padding.top + klineH - ((p - minP) / (maxP - minP)) * klineH; }
    function yV(v) { return volTop + volH - (v / maxVol) * volH; }
    
    let svg = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" style="background:#ffffff;display:block;">`;
    
    for (let i = 0; i <= 3; i++) {
        const p = minP + (maxP - minP) * (i / 3);
        const y = yP(p);
        svg += `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="#f3f4f6" stroke-width="1"/>`;
        svg += `<text x="${width - padding.right + 3}" y="${y + 3}" font-size="9" fill="#9ca3af" font-family="monospace">${p.toFixed(0)}</text>`;
    }
    
    let ma5Path = '';
    let ma20Path = '';
    
    allBars.forEach((b, idx) => {
        const x = padding.left + (idx + 0.5) * (chartW / n);
        const o = b[1], h = b[2], l = b[3], c = b[4], v = b[5], ma5 = b[6], ma20 = b[7];
        const isUp = c >= o;
        const isD2 = (idx === bars30.length);
        
        let color = isUp ? '#dc2626' : '#16a34a';
        let strokeW = 1;
        if (isD2) {
            color = isUp ? '#b91c1c' : '#047857';
            strokeW = 1.8;
        }
        
        const topY = yP(Math.max(o, c));
        const botY = yP(Math.min(o, c));
        const bodyH = Math.max(1.2, botY - topY);
        const highY = yP(h);
        const lowY = yP(l);
        
        svg += `<line x1="${x.toFixed(1)}" y1="${highY.toFixed(1)}" x2="${x.toFixed(1)}" y2="${lowY.toFixed(1)}" stroke="${color}" stroke-width="${strokeW}"/>`;
        svg += `<rect x="${(x - barW/2).toFixed(1)}" y="${topY.toFixed(1)}" width="${barW.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}"/>`;
        
        const vy = yV(v);
        const vH = Math.max(1, volTop + volH - vy);
        svg += `<rect x="${(x - barW/2).toFixed(1)}" y="${vy.toFixed(1)}" width="${barW.toFixed(1)}" height="${vH.toFixed(1)}" fill="${color}" opacity="0.8"/>`;
        
        if (ma5 !== null && ma5 !== undefined) {
            const my5 = yP(ma5);
            ma5Path += `${ma5Path ? 'L' : 'M'} ${x.toFixed(1)} ${my5.toFixed(1)} `;
        }
        if (ma20 !== null && ma20 !== undefined) {
            const my20 = yP(ma20);
            ma20Path += `${ma20Path ? 'L' : 'M'} ${x.toFixed(1)} ${my20.toFixed(1)} `;
        }
        
        if (isD2) {
            svg += `<line x1="${(x - barW).toFixed(1)}" y1="${padding.top}" x2="${(x - barW).toFixed(1)}" y2="${height - padding.bottom}" stroke="#d97706" stroke-width="1.2" stroke-dasharray="2,2"/>`;
            svg += `<text x="${x.toFixed(1)}" y="${padding.top - 5}" font-size="9" fill="#d97706" font-weight="700">D2揭晓</text>`;
        }
        
        if (idx === 0) {
            svg += `<text x="${x.toFixed(1)}" y="${height - 6}" font-size="9" fill="#9ca3af">${b[0].slice(5)}</text>`;
        } else if (idx === Math.floor(bars30.length / 2)) {
            svg += `<text x="${x.toFixed(1)}" y="${height - 6}" font-size="9" fill="#9ca3af" text-anchor="middle">${b[0].slice(5)}</text>`;
        } else if (idx === bars30.length - 1) {
            svg += `<text x="${x.toFixed(1)}" y="${height - 6}" font-size="9" fill="#4b5563" font-weight="700" text-anchor="end">${b[0].slice(5)}</text>`;
        }
    });
    
    if (ma5Path) svg += `<path d="${ma5Path}" fill="none" stroke="#f59e0b" stroke-width="1.4"/>`;
    if (ma20Path) svg += `<path d="${ma20Path}" fill="none" stroke="#3b82f6" stroke-width="1.4"/>`;
    
    svg += `<text x="${padding.left + 5}" y="${padding.top - 7}" font-size="10" fill="#f59e0b" font-weight="700">MA5</text>`;
    svg += `<text x="${padding.left + 40}" y="${padding.top - 7}" font-size="10" fill="#3b82f6" font-weight="700">MA20</text>`;
    svg += `<text x="${padding.left + 78}" y="${padding.top - 7}" font-size="10" fill="#6b7280">（近30日 · 虚线后作答揭晓）</text>`;
    
    svg += `</svg>`;
    el.innerHTML = svg;
}

function renderMiniHeat(containerId, bars) {
    const el = document.getElementById(containerId);
    if (!el || !bars) return;
    const maxV = Math.max(...bars, 1);
    let svg = `<svg viewBox="0 0 100 22" width="100%" height="22" style="display:block;">`;
    bars.forEach((v, idx) => {
        const x = idx * 10 + 1;
        const h = Math.max(2, (v / maxV) * 18);
        const y = 20 - h;
        const color = (idx === bars.length - 1) ? '#dc2626' : '#9ca3af';
        svg += `<rect x="${x}" y="${y}" width="8" height="${h}" fill="${color}"/>`;
    });
    svg += `</svg>`;
    el.innerHTML = svg;
}

// 截止 D1 收盘大盘趋势客观数学判断胶囊（100% 零未来数据）
function updateIndexTrendCapsule(idxBars) {
    const el = document.getElementById('case-phase');
    if (!el || !idxBars || idxBars.length === 0) return;
    const n = idxBars.length;
    const getClose = (b) => (b.length >= 6 ? b[4] : b[3]);
    const lastBar = idxBars[n - 1]; // 截止 D1 收盘
    const closeD1 = getClose(lastBar);
    
    const ma5Slice = idxBars.slice(Math.max(0, n - 5));
    const ma5 = ma5Slice.reduce((sum, b) => sum + getClose(b), 0) / ma5Slice.length;
    
    const ma20Slice = idxBars.slice(Math.max(0, n - 20));
    const ma20 = ma20Slice.reduce((sum, b) => sum + getClose(b), 0) / ma20Slice.length;
    
    const baseBar = n >= 6 ? idxBars[n - 6] : idxBars[0];
    const chg5 = ((closeD1 - getClose(baseBar)) / getClose(baseBar)) * 100;
    const chgStr = Math.abs(chg5).toFixed(1) + '%';
    
    let trendDesc = '';
    let pillStyle = '';
    if (closeD1 >= ma5 && closeD1 >= ma20) {
        if (ma5 >= ma20) {
            trendDesc = '多头排列（站稳 5日与20日均线）';
        } else {
            trendDesc = '金叉突破（站上 5日与20日均线）';
        }
        pillStyle = 'background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;';
    } else if (closeD1 < ma5 && closeD1 < ma20) {
        trendDesc = `空头寻底（跌破双均线，近5日跌 ${chgStr}）`;
        pillStyle = 'background:#f0fdf4;border:1px solid #bbf7d0;color:#15803d;';
    } else if (closeD1 >= ma20 && closeD1 < ma5) {
        trendDesc = '均线拉锯（回踩 5日线守住 20日线）';
        pillStyle = 'background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;';
    } else {
        trendDesc = `震荡反弹（站上 5日线受制 20日线，近5日${chg5 >= 0 ? '涨' : '跌'} ${chgStr}）`;
        pillStyle = 'background:#fffbeb;border:1px solid #fde68a;color:#b45309;';
    }
    
    el.textContent = `大盘昨收 ${Math.round(closeD1)} 点 · ${trendDesc}`;
    if (pillStyle) {
        el.style.cssText = pillStyle;
    }
}


// 筛选模式控制
function applyFilterMode(mode) {
    currentFilterMode = mode;
    filteredIndices = [];
    
    allCases.forEach((c, idx) => {
        if (mode === 'all') {
            filteredIndices.push(idx);
        } else if (mode === 'dragon' && c.type === 'dragon') {
            filteredIndices.push(idx);
        } else if (mode === 'empty' && c.type === 'empty') {
            filteredIndices.push(idx);
        } else if (mode === 'wrong') {
            if (userStats.wrongCaseIds.includes(c.id)) filteredIndices.push(idx);
        } else if (['2021', '2022', '2023', '2024', '2025', '2026'].includes(mode)) {
            if (c.date && c.date.startsWith(mode)) filteredIndices.push(idx);
        }
    });
    
    const modeSel = document.getElementById('mode-select');
    if (modeSel && modeSel.value !== mode) modeSel.value = mode;
    
    const countBadge = document.getElementById('filter-count-badge');
    if (countBadge) countBadge.textContent = `${filteredIndices.length} 道真实历史关卡`;
    
    if (filteredIndices.length === 0) {
        alert('当前分类下暂无题目（如错题本为空）！自动切回全量题库。');
        applyFilterMode('all');
        return;
    }
    
    activePointer = 0;
    renderCurrentCase();
}

function prevCase() {
    if (activePointer > 0) {
        activePointer--;
        renderCurrentCase();
    }
}

function nextCase() {
    if (activePointer < filteredIndices.length - 1) {
        activePointer++;
        renderCurrentCase();
    }
}

function randomCase() {
    if (filteredIndices.length > 0) {
        activePointer = Math.floor(Math.random() * filteredIndices.length);
        renderCurrentCase();
    }
}

function jumpToCaseNumber(num) {
    const targetId = parseInt(num, 10);
    const foundIdx = filteredIndices.findIndex(i => allCases[i].id === targetId);
    if (foundIdx >= 0) {
        activePointer = foundIdx;
        renderCurrentCase();
    } else {
        alert(`未在当前分类中找到第 ${targetId} 关，请检查题号！`);
    }
}

function toggleBlindMode() {
    isBlindMode = !isBlindMode;
    const btn = document.getElementById('btn-blind');
    if (btn) {
        if (isBlindMode) {
            btn.textContent = '盲测模式：开启（隐去代码与名称）';
            btn.style.background = '#fffbeb';
            btn.style.color = '#b45309';
            btn.style.borderColor = '#fde68a';
        } else {
            btn.textContent = '盲测模式：关闭（显示真实股票名）';
            btn.style.background = '#f3f4f6';
            btn.style.color = '#4b5563';
            btn.style.borderColor = '#d1d5db';
        }
    }
    renderCurrentCase();
}

function toggleSysRank() {
    window.showSysRank = !window.showSysRank;
    const btn = document.getElementById('btn-toggle-sysrank');
    if (btn) {
        if (window.showSysRank) {
            btn.textContent = '量化个股排名：已开启（点击隐藏）';
            btn.style.background = '#eff6ff';
            btn.style.borderColor = '#93c5fd';
            btn.style.color = '#1d4ed8';
        } else {
            btn.textContent = '量化个股排名：已隐藏（点击查看）';
            btn.style.background = '#f3f4f6';
            btn.style.borderColor = '#d1d5db';
            btn.style.color = '#4b5563';
        }
    }
    const savedTheme = currentSelectedThemeIdx;
    renderCurrentCase(savedTheme);
}

function selectThemeIndex(tIdx) {
    currentSelectedThemeIdx = tIdx;
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c || !c.themes[tIdx]) return;
    
    document.querySelectorAll('.theme-card').forEach((card, idx) => {
        card.classList.remove('selected');
        const badge = card.querySelector('.theme-status-tag');
        if (idx === tIdx) {
            card.classList.add('selected');
            if (badge) {
                badge.textContent = '✓ 当前锁定题材';
                badge.style.background = '#111827';
                badge.style.color = '#fde68a';
            }
        } else {
            if (badge) {
                badge.textContent = `点击查看 ${c.themes[idx].cands.length} 只候选首板股`;
                badge.style.background = '#f3f4f6';
                badge.style.color = '#4b5563';
            }
        }
    });
    
    renderThemeCands(tIdx);
}

function getPlateBadge(code) {
    if (!code) return '';
    const s = code.trim();
    if (s.startsWith('600') || s.startsWith('601') || s.startsWith('603') || s.startsWith('605') || s.startsWith('60')) {
        return '<span class="plate-badge plate-sh">沪主板10%</span>';
    } else if (s.startsWith('000') || s.startsWith('001') || s.startsWith('002') || s.startsWith('003') || s.startsWith('00')) {
        return '<span class="plate-badge plate-sz">深主板10%</span>';
    } else if (s.startsWith('300') || s.startsWith('301') || s.startsWith('30')) {
        return '<span class="plate-badge plate-cyb">创业板20%</span>';
    } else if (s.startsWith('688') || s.startsWith('689') || s.startsWith('68')) {
        return '<span class="plate-badge plate-kcb">科创板20%</span>';
    } else if (s.startsWith('8') || s.startsWith('4') || s.startsWith('92')) {
        return '<span class="plate-badge plate-bj">北交所30%</span>';
    }
    return '';
}

function formatDescWithBadges(desc, showQuant) {
    if (!desc) return '';
    if (!showQuant) return desc;
    let html = desc;
    html = html.replace(/【([^】]*(?:传统主业|风险|业绩公告|扣|未达|拦截)[^】]*)】/g, '<span style="display:inline-block;margin:1px 2px;background:#fee2e2;border:1px solid #fca5a5;color:#b91c1c;padding:1px 5px;font-weight:700;font-size:11px;">$1</span>');
    html = html.replace(/【([^】]*(?:合同|并购|机构调研|首现|新高|加)[^】]*)】/g, '<span style="display:inline-block;margin:1px 2px;background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;padding:1px 5px;font-weight:700;font-size:11px;">$1</span>');
    return html;
}

// 关卡主渲染（量化部分仅常驻保留题材分、按开关显示个股量化排名，其余全客观盘面事实）
function renderCurrentCase(preserveThemeIdx = 0) {
    stopVoiceExplain();
    if (filteredIndices.length === 0) return;
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c) return;
    
    // 1. 关卡抬头横幅（纯客观日期与周几）
    if (isBlindMode) {
        document.getElementById('case-title').textContent = `关卡 ${c.id}：真实历史早盘切面（年份已隐去）`;
        document.getElementById('case-sub').textContent = `盲测决战切面：${c.weekday_str || '交易日'} 09:25:05`;
    } else {
        document.getElementById('case-title').textContent = `关卡 ${c.id}：${c.title}`;
        const d1W = c.d1_weekday_str ? ` ${c.d1_weekday_str}` : '';
        const d2W = c.weekday_str ? ` ${c.weekday_str}` : '';
        document.getElementById('case-sub').textContent = `决战日：${c.date}${d2W} 09:25:05（首板日：${c.d1_date}${d1W}）`;
    }
    
    const jumpInput = document.getElementById('jump-input');
    if (jumpInput) jumpInput.value = c.id;
    const progText = document.getElementById('progress-text');
    if (progText) progText.textContent = `${activePointer + 1} / ${filteredIndices.length}`;
    
    // 2. 切割上证指数数据
    let bars125 = [];
    let bars30 = [];
    if (typeof SH_DATE_INDEX !== 'undefined') {
        const dIdx = SH_DATE_INDEX[c.d1_date];
        if (dIdx !== undefined) {
            bars125 = SH_INDEX_SERIES.slice(Math.max(0, dIdx - 124), dIdx + 1);
            bars30 = SH_INDEX_SERIES.slice(Math.max(0, dIdx - 29), dIdx + 1);
        }
    }
    updateIndexTrendCapsule(bars30.length > 0 ? bars30 : c.idx_bars);
    
    // 3. 模块一：客观盘面情绪表（纯原始数字）
    const sent = c.sent || [];
    const ztDtEl = document.getElementById('sent-zt-dt');
    if (ztDtEl) {
        ztDtEl.innerHTML = `<span style="color:#dc2626;font-weight:700;">${sent[0] || 0} 家</span> / <span style="color:#16a34a;font-weight:700;">${sent[1] || 0} 家</span>`;
    }
    const sentFirst = document.getElementById('sent-first');
    if (sentFirst) sentFirst.textContent = `${sent[2] || 0} 家`;
    
    const sentPromo = document.getElementById('sent-promo');
    if (sentPromo) {
        sentPromo.innerHTML = `<span style="color:#111827;font-weight:700;">${sent[3] || '--'}</span>`;
    }
    
    const promoMa5El = document.getElementById('sent-promo-ma5');
    if (promoMa5El) {
        const rawMa5 = c.promo_ma5_raw || String(c.promo_ma5_str || '--').split(' ')[0];
        promoMa5El.textContent = rawMa5;
        promoMa5El.style.color = '#111827';
        promoMa5El.style.fontWeight = '700';
    }
    
    const sentHeight = document.getElementById('sent-height');
    if (sentHeight) sentHeight.textContent = sent[4] || '--';
    
    const sentOpen = document.getElementById('sent-open');
    if (sentOpen) {
        const rawOpen = String(sent[5] || '--').split(' ')[0];
        sentOpen.textContent = rawOpen;
        sentOpen.style.color = (rawOpen.startsWith('+')) ? '#dc2626' : (rawOpen.startsWith('-') ? '#16a34a' : '#111827');
        sentOpen.style.fontWeight = '700';
    }
    
    const yiziEl = document.getElementById('sent-yizi');
    if (yiziEl) {
        const rawYzCnt = (c.mkt_yizi_cnt !== undefined) ? c.mkt_yizi_cnt : parseInt(String(c.mkt_yizi_str || '0'), 10);
        yiziEl.textContent = `${rawYzCnt} 家`;
    }
    
    setTimeout(() => {
        if (bars125.length > 0) {
            renderIndex6MKLine('index-kline-6m', bars125, null);
        }
        if (bars30.length > 0) {
            renderIndex30DKLine('index-kline-30d', bars30, null);
        } else if (c.idx_bars) {
            renderCompactKLine('index-kline-30d', c.idx_bars, null, null, true);
        }
    }, 10);
    
    // 4. 模块二：3 张题材卡（常驻直接显示量化题材分 + 板块前一日收盘均幅 + 纯客观盘面指标）
    const safeThemeIdx = (preserveThemeIdx >= 0 && preserveThemeIdx < c.themes.length) ? preserveThemeIdx : 0;
    const themesEl = document.getElementById('themes-container');
    let thHtml = '';
    c.themes.forEach((th, tIdx) => {
        const isCurrent = (tIdx === safeThemeIdx);
        const topBadgeHtml = `<span class="theme-badge" style="background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;font-weight:700;font-size:11px;padding:2px 6px;">量化题材分：第 ${th.elo_rank} 名 (${th.elo_score}分)</span>`;
        const termDisplay = th.raw_term_type || `同细分分支最多 ${th.sub_cluster_cnt || 1} 只`;
        const yzCnt = th.plate_yizi_cnt || 0;
        const flcCnt = th.front_lock_cnt || 0;
        const overWinCnt = Math.max(0, flcCnt - yzCnt);
        const escortDisplay = th.raw_escort || `今一字 ${yzCnt} 只 · 高开超买窗 ${overWinCnt} 只`;
        const d1AvgPct = (th.d1_plate_avg_pct !== undefined) ? th.d1_plate_avg_pct : 0;
        const d1AvgStr = th.d1_plate_avg_str || '--';
        thHtml += `
            <div class="theme-card ${isCurrent ? 'selected' : ''}" onclick="selectThemeIndex(${tIdx})">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:2px;">
                        ${topBadgeHtml}
                    </div>
                    <span class="theme-status-tag" style="font-size:10px;padding:2px 6px;font-weight:700;${isCurrent ? 'background:#111827;color:#fde68a;' : 'background:#f3f4f6;color:#4b5563;'}">${isCurrent ? '✓ 当前锁定题材' : `点击查看 ${th.cands.length} 只候选首板股`}</span>
                </div>
                <div class="theme-name" style="font-size:16px;font-weight:800;color:#111827;margin-bottom:6px;">${th.name}</div>
                <div class="theme-stat-row" style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                    <span style="color:#6b7280;">细分分支共振度</span>
                    <strong>${termDisplay}</strong>
                </div>
                <div class="theme-stat-row" style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                    <span style="color:#6b7280;">昨日板块涨停数</span>
                    <strong>${th.p_sz || th.first_boards} 家</strong>
                </div>
                <div class="theme-stat-row" style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                    <span style="color:#6b7280;">板块前一日收盘均幅</span>
                    <strong style="color:${d1AvgPct >= 0 ? '#dc2626' : '#16a34a'}">${d1AvgStr}</strong>
                </div>
                <div class="theme-stat-row" style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;">
                    <span style="color:#6b7280;">今日一字与高开</span>
                    <strong>${escortDisplay}</strong>
                </div>
                <div class="theme-stat-row" style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
                    <span style="color:#6b7280;">板块首板竞价均幅</span>
                    <strong style="color:${(th.avg_open && th.avg_open.startsWith('+')) ? '#dc2626' : '#16a34a'}">${th.avg_open}</strong>
                </div>
                <div id="theme-heat-${tIdx}" class="theme-heat-chart" style="margin-top:6px;"></div>
            </div>
        `;
    });
    themesEl.innerHTML = thHtml;
    setTimeout(() => {
        c.themes.forEach((th, tIdx) => {
            renderMiniHeat(`theme-heat-${tIdx}`, th.heat_bars);
        });
    }, 10);
    
    currentSelectedThemeIdx = safeThemeIdx;
    renderThemeCands(safeThemeIdx);
    
    const resultCard = document.getElementById('result-reveal-card');
    if (resultCard) resultCard.style.display = 'none';
    document.querySelectorAll('.choice-btn').forEach(b => b.classList.remove('selected-choice'));
    
    if (userStats.history[c.id]) {
        restoreAnswer(userStats.history[c.id]);
    }
}


// 动态渲染当前选中题材下的首板候选股
function renderThemeCands(tIdx) {
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c || !c.themes[tIdx]) return;
    
    const th = c.themes[tIdx];
    const cands = th.cands || [];
    
    const headerTitle = document.getElementById('module3-title');
    if (headerTitle) {
        headerTitle.innerHTML = `当前查看：【<strong style="color:#d97706;">${th.name}</strong>】旗下的 ${cands.length} 只候选首板股（点击上方其他题材卡可随时换题材）`;
    }
    
    // 1. 4 张独立 K 线卡片
    const klineGrid = document.getElementById('stock-kline-grid');
    let klHtml = '';
    cands.forEach((cand) => {
        const displayName = isBlindMode ? `标的 ${cand.opt} ${getPlateBadge(cand.code)}` : `${cand.name} (${cand.code.slice(0,6)}) ${getPlateBadge(cand.code)}`;
        
        let klRankBadge = '';
        if (window.showSysRank) {
            const rk = cand.sys_rank;
            let rkStyle = 'background:#f3f4f6;color:#374151;border:1px solid #d1d5db;';
            let rkLabel = `综合第 ${rk} 名`;
            if (rk === 1) {
                rkStyle = 'background:#fef3c7;color:#92400e;font-weight:700;border:1px solid #f59e0b;';
            } else if (rk === 2) {
                rkStyle = 'background:#e0f2fe;color:#0369a1;border:1px solid #38bdf8;';
            } else if (rk === 3) {
                rkStyle = 'background:#ecfdf5;color:#047857;border:1px solid #34d399;';
            }
            klRankBadge = `<span style="font-size:10px;padding:2px 6px;margin-left:6px;${rkStyle}">${rkLabel}</span>`;
        }
        
        klHtml += `
            <div class="stock-kline-card">
                <div class="stock-kline-header" style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid #e5e7eb;">
                    <div style="display:flex;align-items:center;">
                        <span class="stock-code-tag">${cand.opt}</span>
                        <span class="stock-name-title" id="kline-title-${cand.opt}" style="font-weight:700;margin-left:6px;">${displayName}</span>
                        ${klRankBadge}
                    </div>
                    <div class="stock-sub-info" style="font-size:11px;color:#6b7280;">${th.name.split('/')[0]}</div>
                </div>
                <div id="stock-kline-${cand.opt}" style="width:100%;height:185px;"></div>
            </div>
        `;
    });
    klineGrid.innerHTML = klHtml;
    setTimeout(() => {
        cands.forEach((cand) => {
            renderCompactKLine(`stock-kline-${cand.opt}`, cand.klines, null, null, false);
        });
    }, 10);
    
    // 2. 候选首板股全景对比表（精确 12 列，仅列 2 受量化个股排名开关控制）
    const tableBody = document.getElementById('stocks-table-body');
    let tbHtml = '';
    cands.forEach((cand) => {
        const displayName = isBlindMode ? `标的 ${cand.opt} ${getPlateBadge(cand.code)}` : `${cand.name} <span style="color:#6b7280;font-size:11px;">${cand.code}</span> ${getPlateBadge(cand.code)}`;
        
        // 列 2：量化个股排名
        let rankBadge = '';
        if (window.showSysRank) {
            const rk = cand.sys_rank;
            let rkStyle = 'background:#f3f4f6;color:#374151;border:1px solid #d1d5db;';
            let rkLabel = `综合第 ${rk} 名`;
            if (rk === 1) {
                rkStyle = 'background:#fef3c7;color:#92400e;border:1px solid #f59e0b;font-weight:800;';
            } else if (rk === 2) {
                rkStyle = 'background:#e0f2fe;color:#0369a1;border:1px solid #38bdf8;font-weight:700;';
            } else if (rk === 3) {
                rkStyle = 'background:#ecfdf5;color:#047857;border:1px solid #34d399;font-weight:700;';
            }
            rankBadge = `<span style="padding:2px 6px;font-size:11px;${rkStyle}">${rkLabel}</span>`;
        } else {
            rankBadge = `<span style="color:#9ca3af;font-size:11px;">[已隐藏]</span>`;
        }
        
        // 列 4：主业与催化（纯客观主业与公开公告事实）
        const formattedDesc = isBlindMode ? (cand.raw_blind_desc || cand.blind_desc || cand.desc || '') : (cand.raw_desc || cand.desc || '');
        
        // 列 7：前一日炸板与封单（纯客观首封时间、开板次数与封单额）
        const d1BoardStr = cand.raw_d1_board || cand.seal || '--';
        const d1SealStr = cand.raw_d1_seal || '';
        
        // 列 8：20日回撤 / 位置 / 前1日
        const preD1Color = (cand.pre_d1 <= -1.0) ? '#16a34a' : ((cand.pre_d1 > 3.0) ? '#dc2626' : '#4b5563');
        const posStr = (cand.pos20_pct !== undefined) ? `${cand.pos20_pct}%` : '--';
        const zt20Str = (cand.zt20 !== undefined) ? `${cand.zt20}板` : '';
        
        // 列 9：09:25竞价（纯客观开盘涨幅）
        const openColor = (cand.o_pct >= 0) ? '#dc2626' : '#16a34a';
        
        // 列 10：竞价题材内 / 全场第几（纯客观非一字排名）
        const rkStr = cand.raw_rk_str || (cand.rk ? `板块第 ${cand.rk[0]} 名 / 全场第 ${cand.rk[1]} 名` : '--');
        
        // 列 11：相比第2名差多少（纯客观差幅）
        let leadStr = cand.raw_lead_str;
        if (!leadStr) {
            const lv = (cand.raw_lead !== undefined) ? cand.raw_lead : cand.lead;
            if (lv !== undefined) {
                leadStr = (lv > 0) ? `+${lv.toFixed(2)}%` : `${lv.toFixed(2)}%`;
            } else {
                leadStr = '--';
            }
        }
        const leadValForColor = (cand.raw_lead !== undefined) ? cand.raw_lead : cand.lead;
        const leadColor = (leadValForColor > 0) ? '#dc2626' : ((leadValForColor < 0) ? '#16a34a' : '#374151');
        const trigDisplay = cand.raw_trig_str || cand.trig_str || '--';
        
        tbHtml += `
            <tr>
                <td style="font-weight:700;"><span class="stock-code-tag">${cand.opt}</span></td>
                <td>${rankBadge}</td>
                <td style="font-weight:700;" id="table-name-${cand.opt}">${displayName}</td>
                <td style="max-width:240px;white-space:normal;">${formattedDesc}</td>
                <td style="font-family:monospace;">${cand.mcap} 亿<br/><span style="font-size:11px;color:#6b7280;">股价 ${(cand.close_d1 || 0).toFixed(2)}元</span></td>
                <td style="font-family:monospace;">${cand.d1_amt}亿 / ${(cand.d1_turn || 0).toFixed(1)}%<br/><span style="font-size:11px;color:#6b7280;">量比 ${cand.vr || '--'}</span></td>
                <td style="font-family:monospace;">
                    <span style="font-weight:700;color:#374151;">${d1BoardStr}</span><br/>
                    <span style="font-size:11px;color:#6b7280;">${d1SealStr}</span>
                </td>
                <td style="font-family:monospace;">
                    回撤 ${cand.dd20}% · 位置 ${posStr}<br/>
                    前1日 <span style="color:${preD1Color};">${cand.pre_d1 >= 0 ? '+' : ''}${cand.pre_d1}%</span> · 20日${zt20Str}
                </td>
                <td style="font-family:monospace;font-weight:700;color:${openColor};">
                    ${cand.o_pct >= 0 ? '+' : ''}${cand.o_pct.toFixed(2)}%
                </td>
                <td style="font-family:monospace;font-weight:700;">${rkStr}</td>
                <td style="font-family:monospace;font-weight:700;color:${leadColor};">${leadStr}</td>
                <td style="font-size:11px;font-weight:700;color:#d97706;">${trigDisplay}</td>
            </tr>
        `;
    });
    tableBody.innerHTML = tbHtml;
    
    // 3. 动态更新模块四按钮组
    const actionGroup = document.getElementById('action-buttons-group');
    if (actionGroup) {
        let btnHtml = '';
        cands.forEach(cand => {
            btnHtml += `<button class="choice-btn" data-option="${cand.opt}" onclick="handleChoice('${cand.opt}')">【选择标的 ${cand.opt}】<span style="font-size:11px;color:#6b7280;font-weight:normal;">(按 ${cand.opt})</span></button>`;
        });
        btnHtml += `<button class="choice-btn btn-empty" data-option="E" onclick="handleChoice('E')">【选择标的 E 今日全场空仓】<span style="font-size:11px;color:#92400e;font-weight:normal;">(按 E 或 0)</span></button>`;
        actionGroup.innerHTML = btnHtml;
    }
}


// 用户作答与判定
function handleChoice(option) {
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c) return;
    
    document.querySelectorAll('.choice-btn').forEach(b => {
        b.classList.remove('selected-choice');
        if (b.dataset.option === option) b.classList.add('selected-choice');
    });
    
    let isThemeCorrect = false;
    let isCorrect = false;
    let userProfit = 0.0;
    let pickedCand = null;
    
    if (option === 'E') {
        if (c.market_ans === 'E') {
            isCorrect = true;
            isThemeCorrect = true;
            userProfit = 0.0;
        } else {
            isCorrect = false;
            userProfit = 0.0;
        }
    } else {
        const currentTheme = c.themes[currentSelectedThemeIdx];
        if (currentTheme && currentTheme.cands) {
            pickedCand = currentTheme.cands.find(cd => cd.opt === option);
        }
        if (pickedCand) {
            userProfit = (pickedCand.net_ret || 0.0) / 100.0;
            isThemeCorrect = (currentSelectedThemeIdx === c.market_best_theme_idx);
            isCorrect = (isThemeCorrect && option === c.market_ans);
        }
    }
    
    const sysProfit = (c.sys_ret || 0.0) / 100.0;
    const isBeatSystem = (userProfit > sysProfit);
    
    if (!userStats.history[c.id]) {
        userStats.totalAnswered++;
        if (isCorrect) userStats.correctCount++;
        if (c.market_ans === 'E' && option === 'E') userStats.avoidTrapCount++;
        else if (isCorrect) userStats.avoidTrapCount++;
        if (isBeatSystem) userStats.beatSystemCount++;
        
        userStats.cumNav *= (1.0 + userProfit);
        userStats.systemNav *= (1.0 + sysProfit);
        userStats.history[c.id] = { choice: option, themeIdx: currentSelectedThemeIdx, isCorrect: isCorrect, userProfit: userProfit };
        
        if (!isCorrect) {
            if (!userStats.wrongCaseIds.includes(c.id)) userStats.wrongCaseIds.push(c.id);
        } else {
            userStats.wrongCaseIds = userStats.wrongCaseIds.filter(id => id !== c.id);
        }
        
        saveStats();
        updateStatsUI();
    }
    
    revealResult(option, currentSelectedThemeIdx, isThemeCorrect, isCorrect, userProfit, pickedCand, c, isBeatSystem, true);
}

function restoreAnswer(hist) {
    const realIdx = filteredIndices[activePointer];
    const c = allCases[realIdx];
    if (!c) return;
    
    const option = hist.choice;
    const tIdx = hist.themeIdx || 0;
    currentSelectedThemeIdx = tIdx;
    selectThemeIndex(tIdx);
    
    document.querySelectorAll('.choice-btn').forEach(b => {
        if (b.dataset.option === option) b.classList.add('selected-choice');
    });
    
    const isThemeCorrect = (c.market_best_theme_idx === -1) ? (option === 'E') : (tIdx === c.market_best_theme_idx);
    const isCorrect = hist.isCorrect;
    const userProfit = hist.userProfit || 0.0;
    let pickedCand = null;
    if (option !== 'E' && c.themes[tIdx]) {
        pickedCand = c.themes[tIdx].cands.find(cd => cd.opt === option);
    }
    const isBeatSystem = (userProfit > ((c.sys_ret || 0.0) / 100.0));
    revealResult(option, tIdx, isThemeCorrect, isCorrect, userProfit, pickedCand, c, isBeatSystem, false);
}

function revealResult(option, themeIdx, isThemeCorrect, isCorrect, userProfit, pickedCand, c, isBeatSystem, animate = true) {
    // 揭晓后标题显示完整公历日期与周几（纯客观）
    const d1W = c.d1_weekday_str ? ` ${c.d1_weekday_str}` : '';
    const d2W = c.weekday_str ? ` ${c.weekday_str}` : '';
    document.getElementById('case-title').textContent = `关卡 ${c.id}：${c.title}`;
    document.getElementById('case-sub').textContent = `决战日：${c.date}${d2W} 09:25:05（首板日：${c.d1_date}${d1W}）`;
    
    const th = c.themes[themeIdx];
    if (th && th.cands) {
        th.cands.forEach(cand => {
            const klineTitle = document.getElementById(`kline-title-${cand.opt}`);
            if (klineTitle) klineTitle.innerHTML = `${cand.name} (${cand.code.slice(0,6)}) ${getPlateBadge(cand.code)}`;
            const tableName = document.getElementById(`table-name-${cand.opt}`);
            if (tableName) tableName.innerHTML = `${cand.name} <span style="color:#6b7280;font-size:11px;">${cand.code}</span> ${getPlateBadge(cand.code)}`;
            renderCompactKLine(`stock-kline-${cand.opt}`, cand.klines, cand.d2, cand.d3, false);
        });
    }
    if (typeof SH_DATE_INDEX !== 'undefined') {
        const dIdx = SH_DATE_INDEX[c.d1_date];
        const d2Idx = SH_DATE_INDEX[c.date];
        const d2Bar = (d2Idx !== undefined) ? SH_INDEX_SERIES[d2Idx] : null;
        if (dIdx !== undefined) {
            const bars125 = SH_INDEX_SERIES.slice(Math.max(0, dIdx - 124), dIdx + 1);
            const bars30 = SH_INDEX_SERIES.slice(Math.max(0, dIdx - 29), dIdx + 1);
            renderIndex6MKLine('index-kline-6m', bars125, d2Bar);
            renderIndex30DKLine('index-kline-30d', bars30, d2Bar);
        }
    } else if (c.idx_bars) {
        renderCompactKLine('index-kline-30d', c.idx_bars, c.idx_d2, null, true);
    }
    
    const resultCard = document.getElementById('result-reveal-card');
    const headerBar = document.getElementById('result-header-bar');
    const headerTitle = document.getElementById('result-header-title');
    const verdictText = document.getElementById('result-verdict-text');
    
    if (resultCard) {
        resultCard.style.display = 'block';
        if (animate) {
            resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
    
    let headerBg = '#fee2e2';
    let headerBorder = '#ef4444';
    let headerColor = '#991b1b';
    let headerTitleText = '❌ 狙击失败 / 未选出全场最优解';
    
    if (isCorrect) {
        headerBg = '#dcfce7';
        headerBorder = '#22c55e';
        headerColor = '#166534';
        headerTitleText = (option === 'E') ? '🛡️ 完美空仓避险！守住全部本金' : '🎯 绝佳狙击！成功抓获全场主线最高收益真龙';
    }
    
    if (headerBar) {
        headerBar.style.background = headerBg;
        headerBar.style.borderBottom = `2px solid ${headerBorder}`;
    }
    if (headerTitle) {
        headerTitle.style.color = headerColor;
        headerTitle.textContent = headerTitleText;
    }
    
    let thVerdictHtml = '';
    if (c.market_ans === 'E') {
        thVerdictHtml = `<div style="margin-bottom:8px;"><strong>【题材战场裁决】</strong>今日全场 3 个题材均无标的封死二板，全场呈现大冰点退潮，空仓（E）为唯一正确防守策略。</div>`;
    } else {
        const bestTh = c.themes[c.market_best_theme_idx];
        const bestThName = bestTh ? bestTh.name : '主线题材';
        thVerdictHtml = `<div style="margin-bottom:8px;"><strong>【题材战场裁决】</strong>今日全场胜出主线为【<strong>${bestThName}</strong>】，全场真实收益最高标的为选项【<strong>${c.market_ans}：${c.best_stock_name}</strong>】（净收益 +${c.market_best_ret.toFixed(2)}%）。</div>`;
    }
    
    let pkHtml = '';
    if (isBeatSystem) {
        pkHtml = `<div style="padding:10px 14px;background:#ecfdf5;border:1px solid #10b981;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
            <div style="font-size:12px;color:#065f46;">
                <strong>🏆【人机PK：你击败了量化定式！】</strong>量化机械定式首推【${c.sys_cand_name}】（收益 ${c.sys_ret > 0 ? '+' : ''}${c.sys_ret.toFixed(2)}%），而你凭借卓越盘感实现了收益 ${(userProfit*100).toFixed(2)}%，成功战胜系统！
            </div>
            <span style="background:#059669;color:#fff;padding:2px 8px;font-weight:700;font-size:11px;">击败模型</span>
        </div>`;
    } else {
        pkHtml = `<div style="padding:8px 12px;background:#f9fafb;border:1px solid #e5e7eb;margin-bottom:12px;font-size:12px;">
            <strong>【人机收益对比】</strong>你的收益：<strong>${(userProfit*100) > 0 ? '+' : ''}${(userProfit*100).toFixed(2)}%</strong> | 量化综合第 1 名【${c.sys_cand_name}】收益：<strong>${c.sys_ret > 0 ? '+' : ''}${c.sys_ret.toFixed(2)}%</strong>
        </div>`;
    }
    
    if (verdictText) verdictText.innerHTML = thVerdictHtml + pkHtml;
    
    const postmortemGrid = document.getElementById('postmortem-grid');
    if (postmortemGrid && th && th.cands) {
        let pmHtml = '';
        th.cands.forEach(cand => {
            const isWin = (cand.opt === c.market_ans && isThemeCorrect);
            const boxClass = isWin ? 'postmortem-item is-correct' : 'postmortem-item is-trap';
            
            let execBadge = '';
            if (cand.executed) {
                execBadge = `<span style="background:${cand.net_ret > 0 ? '#dcfce7' : '#fee2e2'};color:${cand.net_ret > 0 ? '#15803d' : '#b91c1c'};padding:2px 6px;font-size:11px;font-weight:700;">净收益 ${cand.net_ret > 0 ? '+' : ''}${cand.net_ret.toFixed(2)}%</span>`;
            } else {
                execBadge = `<span style="background:#f3f4f6;color:#4b5563;padding:2px 6px;font-size:11px;font-weight:700;">未成交·收益 0.00%</span>`;
            }
            
            pmHtml += `
                <div class="${boxClass}" style="border:1px solid ${isWin ? '#22c55e' : '#e5e7eb'};padding:10px;background:#ffffff;">
                    <div class="postmortem-stock-title" style="display:flex;justify-content:space-between;margin-bottom:6px;">
                        <span style="font-weight:700;">选项 ${cand.opt}：${cand.name}</span>
                        <span style="color:${isWin ? '#15803d' : '#b91c1c'};font-weight:700;">${isWin ? '【市场真解】' : '【陪跑/避险】'}</span>
                    </div>
                    <div style="font-size:11px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
                        <span style="color:#6b7280;">D2开盘 ${cand.o_pct >= 0 ? '+' : ''}${cand.o_pct.toFixed(2)}%</span>
                        ${execBadge}
                    </div>
                    <div style="font-size:11px;background:#f9fafb;border:1px solid #e5e7eb;padding:6px;margin-bottom:6px;font-family:monospace;line-height:1.6;">
                        <strong>买卖点仿真：</strong>买入 ${(cand.buy_price || 0).toFixed(2)}元 &rarr; 卖出 ${(cand.sell_price || 0).toFixed(2)}元<br/>
                        <strong>离场逻辑：</strong>${cand.exit_reason || '--'}<br/>
                        <strong>复盘点评：</strong>${cand.pm_comment || ''}
                    </div>
                </div>
            `;
        });
        
        const emptyBoxClass = (c.market_ans === 'E') ? 'postmortem-item is-correct' : 'postmortem-item';
        pmHtml += `
            <div class="${emptyBoxClass}" style="grid-column: span 4; border:1px solid #e5e7eb; border-top: 2px solid #111827; background:#fffbeb; padding:10px;">
                <div class="postmortem-stock-title" style="display:flex;justify-content:space-between;margin-bottom:6px;">
                    <span style="font-weight:700;">选项 E：今日全场空仓放弃（防守决策评价）</span>
                    <span style="font-weight:700;color:${c.market_ans === 'E' ? '#15803d' : '#b45309'};">${c.market_ans === 'E' ? '【市场唯一正解】' : '【防守考量】'}</span>
                </div>
                <div class="postmortem-text" style="font-size:12px;color:#4b5563;line-height:1.6;">${c.market_ans === 'E' ? '今日全场无任何主线标的封死二板，所有可成交股票全部冲高炸板跳水！选择空仓成功保住全部本金，空仓也是顶尖盘感！' : '今日市场走出二板晋级总龙头，选择空仓虽保住本金，但错失了核心主线的真龙大肉。'}</div>
            </div>
        `;
        postmortemGrid.innerHTML = pmHtml;
    }
}

// 快捷键监听
window.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    
    const key = e.key.toUpperCase();
    if (['A', '1'].includes(key)) {
        handleChoice('A');
    } else if (['B', '2'].includes(key)) {
        handleChoice('B');
    } else if (['C', '3'].includes(key)) {
        handleChoice('C');
    } else if (['D', '4'].includes(key)) {
        handleChoice('D');
    } else if (['E', '0'].includes(key)) {
        handleChoice('E');
    } else if ([' ', 'ARROWRIGHT', 'ENTER'].includes(key)) {
        e.preventDefault();
        nextCase();
    } else if (['ARROWLEFT'].includes(key)) {
        e.preventDefault();
        prevCase();
    } else if (key === 'M') {
        toggleBlindMode();
    } else if (key === 'V') {
        toggleVoiceExplain();
    } else if (key === 'R') {
        resetCurrentCase();
    }
});

function initTrainerApp(data) {
    allCases = data;
    loadStats();
    recomputeStatsFromHistory();
    saveStats();
    updateStatsUI();
    applyFilterMode('all');
}
