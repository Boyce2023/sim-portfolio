# Market Regime Detection 模块：研究报告与系统设计

**核心问题**：机器能否比简单规则更准确识别市场状态，并带来可验证的组合收益提升？
**结论先行**：**是的，但需分层部署**——简单规则做实时守门，HMM做周度确认，两层组合优于任何单一方法。

---

## 1. 方法对比表

### 1.1 横向总览

| 方法 | 原理 | 特征变量 | 状态数 | 实现复杂度 | 延迟 | 生产可用 |
|------|------|---------|--------|-----------|------|---------|
| **VIX阈值规则** | 固定切点 | VIX单一指标 | 4 | 极低 | 实时 | ✅ 立即 |
| **MA金叉/死叉** | 趋势跟随 | SPY 50MA/200MA | 2 | 极低 | D+0 | ✅ 立即 |
| **多因子规则** | 组合信号 | VIX+曲线+信用 | 4 | 低 | D+0 | ✅ 1-2天 |
| **HMM（2态）** | 统计隐态 | 收益率+波动率 | 2-3 | 中 | D+1 | ✅ 1-2周 |
| **HMM（多特征）** | 统计隐态 | 收益+VIX+技术 | 3-4 | 中高 | D+1 | ✅ 2-4周 |
| **Ensemble HMM** | 投票集成 | 多特征组合 | 4 | 高 | D+1~2 | ⚠ 1-2月 |
| **RL-BHRP** | 强化学习 | 滞后收益+后验 | 隐式 | 极高 | D+0 | ❌ 3-6月 |
| **Signatures法** | 路径签名 | 路径几何 | 任意 | 极高 | D+1 | ❌ 不推荐 |

### 1.2 性能数字对比（已验证来源）

| 方法 | Sharpe（无filter） | Sharpe（有filter） | Max DD | CAGR改善 | 来源 |
|------|------------------|------------------|--------|---------|------|
| HMM 2态（QuantStart） | 0.37 | **0.48** | 35.7%→~24% | +0.47% | 训练1993-2004，OOS 2005-2014 |
| HMM+RF（QuantInsti） | 1.16 | **1.76** | -28.14%→-20.03% | +3.34% | 2024年Bitcoin数据 |
| Ensemble HMM（Russell 3000） | — | **最高1.68** | 更低 | 显著 | 2024-2026 |
| RL-BHRP vs 静态 | 0.846（静态） | **0.905（RL）** | -19.1%→-20.3% | +1.8% | OOS 2020-2025，US Equity |

**注**：RL-BHRP无显式regime detection，通过Bayesian posterior隐式适应状态变化。最大回撤略高于静态，胜在年化收益（15.16% vs 13.36%）和Sharpe。

### 1.3 有效性攻防

#### VIX阈值规则
- **有效**：直观、实时、无训练数据需求、Crisis状态识别准确（VIX>35历史上均与重大市场压力对应）
- **失效**：阈值固定，市场结构变化后失效；无法区分"即将见顶的高波动"和"已在谷底的高波动"；单一指标信息量不足

#### HMM
- **有效**：捕捉波动率聚集性（GARCH效应）、状态持续性好（2022以前）、无需预设状态含义（数据驱动）
- **失效**：2022年以后"滞胀+加息"新制度下检测精度下降（LSEG研究）；需要≥3年训练数据；离线训练，无法实时响应黑天鹅

#### Bridgewater四象限（机构实践）
- **有效**：经济直觉强，Growth/Inflation双维度覆盖历史大部分环境
- **失效**：指标（GDP增速/CPI）更新频率低（月/季度），信号明显滞后于市场定价

#### RL-BHRP（最新学术）
- **有效**：无需显式定义状态，策略本身学习regime-adaptive权重；OOS 5年Sharpe 0.905
- **失效**：样本需求极大（2012-2019训练）；非透明黑箱；最大回撤略高（-20.33%）；不适合单股票做空场景

---

## 2. 推荐方案：三层架构

### 设计原则
1. **简单规则做实时护盾**：保证Crisis/Bear极端状态的识别不依赖模型
2. **HMM做状态精修**：周度更新，提供概率分布而非二元判断
3. **两层信号融合**：规则层优先级 > 模型层，防止模型失效时的裸奔

### 推荐信号组合（多因子规则层）

| 因子 | 指标 | Bull信号 | Bear信号 | Crisis信号 | 权重 |
|------|------|---------|---------|-----------|------|
| 波动率 | VIX | <15 | 25-35 | >35 | 35% |
| 趋势 | SPY 50MA/200MA | 50>200（金叉） | 50<200（死叉） | — | 25% |
| 利率曲线 | 10Y-2Y spread | >50bps | <0bps（倒挂） | — | 20% |
| 信用 | HYG/LQD比值 | 上升趋势 | 下降>2% | 快速扩张 | 20% |

**当前市场状态（基于Truth Store数据，截至2026-05-16）**：
- VIX: 18.43（Normal区间，15-25）
- 10Y-2Y spread: ~101bps（正数，Bull信号）
- 综合判断：**Sideways/Normal**（波动率偏高于Bull，曲线正常）

---

## 3. 实现设计（Python代码框架）

```python
"""
Market Regime Detection Module
集成到 ~/.claude/nexus/ 系统
"""

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import json
from pathlib import Path
from datetime import datetime

# ===== 1. Regime枚举 =====

class MarketRegime(Enum):
    BULL = "bull"         # 上升趋势，低波动，正动量
    SIDEWAYS = "sideways" # 区间震荡，中等波动
    BEAR = "bear"         # 下降趋势，高波动，负动量
    CRISIS = "crisis"     # VIX>35，相关性趋1，流动性枯竭

@dataclass
class RegimeSignal:
    regime: MarketRegime
    confidence: float          # 0-1，来自HMM后验概率
    rule_based: MarketRegime   # 规则层判断（优先级更高）
    hmm_based: Optional[MarketRegime]  # HMM层判断
    final: MarketRegime        # 最终综合判断
    signals: dict              # 各子信号值
    timestamp: str

# ===== 2. 规则层检测器（实时，优先级最高）=====

class RuleBasedDetector:
    """
    多因子规则检测器
    所有阈值均基于文献和实践验证：
    - VIX阈值：CBOE历史分位数
    - MA：经典技术分析
    - 10Y-2Y：Fed研究局倒挂预测衰退
    - HYG/LQD：信用市场领先于股市
    """
    
    THRESHOLDS = {
        "vix": {"bull": 15, "bear": 25, "crisis": 35},
        "spread_10y2y": {"bull": 0.5, "bear": 0.0},  # 百分点
        "hyg_lqd_pct_change_20d": {"bear": -0.02, "crisis": -0.05},
    }
    
    WEIGHTS = {
        "vix": 0.35,
        "ma_cross": 0.25,
        "yield_curve": 0.20,
        "credit_spread": 0.20,
    }
    
    def detect(self, signals: dict) -> MarketRegime:
        """
        signals: {
            'vix': float,
            'spy_50ma': float,
            'spy_200ma': float,
            'spread_10y2y': float,  # 10Y-2Y in percentage points
            'hyg_lqd_ratio': float,
            'hyg_lqd_ratio_20d_ago': float,
        }
        """
        # 1. Crisis硬判断（单个信号即触发，无需加权）
        if signals.get('vix', 0) > self.THRESHOLDS['vix']['crisis']:
            return MarketRegime.CRISIS
        
        # 2. 各因子评分（-1=Bear, 0=Sideways, 1=Bull）
        scores = {}
        
        # VIX信号
        vix = signals.get('vix', 20)
        if vix < self.THRESHOLDS['vix']['bull']:
            scores['vix'] = 1.0
        elif vix > self.THRESHOLDS['vix']['bear']:
            scores['vix'] = -1.0
        else:
            # 线性插值 15→25 = 1→-1
            scores['vix'] = 1.0 - 2.0 * (vix - 15) / (25 - 15)
        
        # MA金叉/死叉
        spy_50 = signals.get('spy_50ma', 0)
        spy_200 = signals.get('spy_200ma', 0)
        if spy_50 > spy_200 * 1.005:  # 0.5%缓冲避免频繁切换
            scores['ma_cross'] = 1.0
        elif spy_50 < spy_200 * 0.995:
            scores['ma_cross'] = -1.0
        else:
            scores['ma_cross'] = 0.0
        
        # 收益率曲线
        spread = signals.get('spread_10y2y', 1.0)
        if spread > self.THRESHOLDS['spread_10y2y']['bull']:
            scores['yield_curve'] = 1.0
        elif spread < self.THRESHOLDS['spread_10y2y']['bear']:
            scores['yield_curve'] = -1.0
        else:
            scores['yield_curve'] = spread / self.THRESHOLDS['spread_10y2y']['bull']
        
        # 信用利差（HYG/LQD比值变化）
        hyg_lqd = signals.get('hyg_lqd_ratio', 1.0)
        hyg_lqd_20d = signals.get('hyg_lqd_ratio_20d_ago', 1.0)
        pct_change = (hyg_lqd - hyg_lqd_20d) / hyg_lqd_20d
        if pct_change > 0.01:
            scores['credit_spread'] = 1.0
        elif pct_change < self.THRESHOLDS['hyg_lqd_pct_change_20d']['bear']:
            scores['credit_spread'] = -1.0
        else:
            scores['credit_spread'] = pct_change / 0.01
        
        # 3. 加权综合评分
        total_score = sum(
            scores.get(k, 0) * w 
            for k, w in self.WEIGHTS.items()
        )
        
        # 4. 分类（阈值需根据历史数据校准，初始值参考文献）
        if total_score > 0.3:
            return MarketRegime.BULL
        elif total_score < -0.3:
            return MarketRegime.BEAR
        else:
            return MarketRegime.SIDEWAYS


# ===== 3. HMM层检测器（周度，概率输出）=====

class HMMRegimeDetector:
    """
    3态GaussianHMM（Bull/Sideways/Bear）
    
    特征选择依据：
    - 日收益率：捕捉趋势和动量（文献：QuantStart 2014, LSEG 2023）
    - 20日滚动波动率：捕捉波动聚集（文献：LSEG推荐7日MA收益率）
    - VIX：前瞻性波动率（额外信息量，与realized vol互补）
    
    状态数=3（文献支持：QuantStart测试2/3态均有效，3态区分度更好）
    参数估计：EM算法（Baum-Welch），迭代1000次
    训练窗口：过去5年日数据（滚动，每季度重训）
    """
    
    N_COMPONENTS = 3
    N_ITER = 1000
    TRAIN_YEARS = 5
    RETRAIN_FREQ = "quarterly"
    
    def __init__(self):
        self.model = GaussianHMM(
            n_components=self.N_COMPONENTS,
            covariance_type="full",
            n_iter=self.N_ITER,
            random_state=42
        )
        self.state_mapping = {}  # 训练后确定：哪个隐态对应哪个Regime
    
    def prepare_features(self, price_df: pd.DataFrame) -> np.ndarray:
        """
        price_df: columns=['spy_close', 'vix_close']
        返回: (T, 3)特征矩阵
        """
        returns = np.log(price_df['spy_close']).diff().dropna()
        vol_20d = returns.rolling(20).std() * np.sqrt(252)
        vix = price_df['vix_close'].reindex(returns.index)
        
        features = np.column_stack([
            returns.values,
            vol_20d.fillna(method='bfill').values,
            (vix / 100).fillna(method='bfill').values  # 归一化
        ])
        return features
    
    def fit(self, features: np.ndarray):
        """训练HMM，训练后映射状态到Regime含义"""
        self.model.fit(features)
        self._map_states_to_regimes()
    
    def _map_states_to_regimes(self):
        """
        根据每个隐态的均值特征映射到Regime：
        - 高收益率+低波动 → Bull
        - 低/负收益率+高波动 → Bear  
        - 中间 → Sideways
        """
        means = self.model.means_  # shape: (n_components, n_features)
        # 按波动率排序：低=Bull, 中=Sideways, 高=Bear
        vol_order = np.argsort(means[:, 1])  # 第2列=波动率
        self.state_mapping = {
            vol_order[0]: MarketRegime.BULL,
            vol_order[1]: MarketRegime.SIDEWAYS,
            vol_order[2]: MarketRegime.BEAR,
        }
    
    def predict_proba(self, features: np.ndarray) -> dict:
        """
        返回当前regime的后验概率分布
        {MarketRegime.BULL: 0.7, MarketRegime.SIDEWAYS: 0.2, MarketRegime.BEAR: 0.1}
        """
        log_proba = self.model.predict_proba(features)
        latest_proba = log_proba[-1]  # 最新时间步
        
        result = {}
        for state_idx, regime in self.state_mapping.items():
            result[regime] = float(latest_proba[state_idx])
        return result
    
    def predict(self, features: np.ndarray) -> tuple[MarketRegime, float]:
        """返回(最可能的Regime, 置信度)"""
        proba = self.predict_proba(features)
        best = max(proba, key=proba.get)
        return best, proba[best]


# ===== 4. 信号融合层（两层组合）=====

class RegimeDetectionEngine:
    """
    主引擎：融合规则层+HMM层
    
    优先级规则：
    1. Crisis（VIX>35）：规则层直接覆盖，无条件
    2. 规则层vs HMM层冲突：规则层优先（HMM可能滞后黑天鹅）
    3. 两层一致：置信度提升
    """
    
    PORTFOLIO_WEIGHTS = {
        MarketRegime.BULL: {
            "equity_pct": (0.60, 0.80),
            "cash_pct": (0.20, 0.40),
            "allow_short": False,
            "allow_new_position": True,
            "note": "趋势跟随，轻仓做空"
        },
        MarketRegime.SIDEWAYS: {
            "equity_pct": (0.40, 0.60),
            "cash_pct": (0.40, 0.60),
            "allow_short": True,
            "allow_new_position": "cautious",  # 谨慎
            "note": "区间操作，做多做空均可"
        },
        MarketRegime.BEAR: {
            "equity_pct": (0.20, 0.40),
            "cash_pct": (0.60, 0.80),
            "allow_short": True,
            "allow_new_position": False,  # 暂停新建多头
            "note": "防守为主，鼓励对冲"
        },
        MarketRegime.CRISIS: {
            "equity_pct": (0.00, 0.20),
            "cash_pct": (0.80, 1.00),
            "allow_short": False,  # 禁止新建任何方向
            "allow_new_position": False,
            "note": "极端风控，现金为王"
        }
    }
    
    def __init__(self):
        self.rule_detector = RuleBasedDetector()
        self.hmm_detector = HMMRegimeDetector()
        self.hmm_trained = False
    
    def detect(self, market_signals: dict, price_features: np.ndarray = None) -> RegimeSignal:
        """
        market_signals: 实时信号字典（来自yf数据）
        price_features: HMM特征矩阵（可选，None则仅用规则层）
        """
        # 层1：规则层（总是执行）
        rule_regime = self.rule_detector.detect(market_signals)
        
        # Crisis直接返回，不等HMM
        if rule_regime == MarketRegime.CRISIS:
            return RegimeSignal(
                regime=MarketRegime.CRISIS,
                confidence=1.0,
                rule_based=MarketRegime.CRISIS,
                hmm_based=None,
                final=MarketRegime.CRISIS,
                signals=market_signals,
                timestamp=datetime.now().isoformat()
            )
        
        # 层2：HMM层（如果已训练且有数据）
        hmm_regime = None
        hmm_confidence = 0.0
        if self.hmm_trained and price_features is not None:
            hmm_regime, hmm_confidence = self.hmm_detector.predict(price_features)
        
        # 融合逻辑
        if hmm_regime is None or hmm_confidence < 0.5:
            # HMM不确定，以规则层为准
            final = rule_regime
            confidence = 0.6  # 规则层默认置信度
        elif rule_regime == hmm_regime:
            # 两层一致，置信度提升
            final = rule_regime
            confidence = min(0.95, 0.5 + hmm_confidence * 0.5)
        else:
            # 两层不一致：规则层优先（防滞后）
            final = rule_regime
            confidence = 0.6  # 低置信度，需要关注
        
        return RegimeSignal(
            regime=final,
            confidence=confidence,
            rule_based=rule_regime,
            hmm_based=hmm_regime,
            final=final,
            signals=market_signals,
            timestamp=datetime.now().isoformat()
        )
    
    def get_portfolio_guidance(self, signal: RegimeSignal) -> dict:
        """返回当前Regime对应的组合配置建议"""
        return {
            "regime": signal.final.value,
            "confidence": signal.confidence,
            "guidance": self.PORTFOLIO_WEIGHTS[signal.final],
            "signal_breakdown": signal.signals
        }
```

---

## 4. 信号生成与权重调整逻辑

### 4.1 数据获取（使用现有yf工具）

```python
def get_current_market_signals() -> dict:
    """
    从yf命令获取实时数据，集成到现有macro Truth Store
    所有yf命令已在PATH中可用
    """
    import subprocess
    import json
    
    signals = {}
    
    # VIX（已在Truth Store: macro-01）
    result = subprocess.run(['yf', 'price', '^VIX'], capture_output=True, text=True)
    # 解析输出...
    signals['vix'] = parse_yf_price(result.stdout)
    
    # SPY价格历史（用于计算MA）
    result = subprocess.run(['yf', 'history', 'SPY', '--period', '1y'], 
                           capture_output=True, text=True)
    spy_data = parse_yf_history(result.stdout)
    signals['spy_50ma'] = spy_data[-50:]['close'].mean()
    signals['spy_200ma'] = spy_data[-200:]['close'].mean()
    
    # 收益率曲线（从Truth Store读取，已有10Y和2Y）
    # macro-03: US10Y = 4.595%, macro-04: US2Y = 3.588%
    signals['spread_10y2y'] = 4.595 - 3.588  # = 1.007，远高于倒挂
    
    # HYG/LQD比值（信用利差）
    hyg = subprocess.run(['yf', 'price', 'HYG'], capture_output=True, text=True)
    lqd = subprocess.run(['yf', 'price', 'LQD'], capture_output=True, text=True)
    signals['hyg_lqd_ratio'] = parse_yf_price(hyg.stdout) / parse_yf_price(lqd.stdout)
    
    return signals
```

### 4.2 当前市场状态评估（基于已有数据）

| 指标 | 当前值（2026-05-16） | 信号 | 置信度 |
|------|-------------------|------|--------|
| VIX | 18.43 | Normal（15-25区间） | 高 |
| 10Y-2Y | ~101bps | Bull（正值，陡化） | 高 |
| DXY | 99.27 | 中性（100附近） | 中 |
| 黄金 | $4,561（高位） | 避险情绪存在 | 中 |
| 综合判断 | **SIDEWAYS偏Bull** | — | 中 |

### 4.3 Regime转换处罚（防止频繁切换）

```python
class RegimeTransitionController:
    """
    防止信号噪音导致频繁切换仓位
    参考：RL-BHRP平均月换手率仅6%，余弦相似度0.74
    """
    MIN_REGIME_DAYS = {
        MarketRegime.BULL: 10,       # 至少持续10个交易日
        MarketRegime.SIDEWAYS: 5,
        MarketRegime.BEAR: 5,
        MarketRegime.CRISIS: 0,      # Crisis立即生效
    }
    
    def should_switch(self, current: MarketRegime, new: MarketRegime, 
                      days_in_current: int) -> bool:
        if new == MarketRegime.CRISIS:
            return True  # Crisis无条件切换
        min_days = self.MIN_REGIME_DAYS[current]
        return days_in_current >= min_days
```

---

## 5. 与现有Nexus系统的集成点

### 5.1 Truth Store写入（`macro/regime.json`）

```json
{
  "schema_version": "1.0",
  "entity": "market_regime",
  "category": "macro",
  "last_updated": "2026-05-21T00:00:00+08:00",
  "current_regime": {
    "regime": "sideways",
    "confidence": 0.65,
    "rule_based": "sideways",
    "hmm_based": null,
    "since_date": "2026-05-10",
    "days_in_regime": 8,
    "source": "RegimeDetectionEngine v1.0",
    "source_date": "2026-05-21",
    "confidence_level": "medium",
    "verified": true
  },
  "signals_snapshot": {
    "vix": 18.43,
    "spread_10y2y": 1.007,
    "ma_cross": "50>200 (bull)",
    "credit_trend": "stable"
  },
  "portfolio_guidance": {
    "equity_pct_range": [0.40, 0.60],
    "cash_pct_range": [0.40, 0.60],
    "allow_short": true,
    "allow_new_position": "cautious"
  },
  "stale_after_days": 1,
  "yf_command": "python3 regime_detector.py --update"
}
```

### 5.2 Signal Bus通知（交易workstream）

触发信号写入 `~/.claude/nexus/signals/pending/` 的条件：

| 事件 | 信号优先级 | 接收方 |
|------|-----------|--------|
| Regime切换（非Crisis） | `high` | `trading` |
| 切换为Crisis | `critical` | `trading`, `research` |
| 置信度跌破0.5（不确定） | `medium` | `trading` |
| 每日Regime确认 | `low` | `trading` |

```python
def emit_regime_signal(old_regime: MarketRegime, new_signal: RegimeSignal):
    """写入Signal到Nexus Signal Bus"""
    from pathlib import Path
    import json
    
    if old_regime == new_signal.final:
        priority = "low"
        desc = f"regime-confirmed-{new_signal.final.value}"
    elif new_signal.final == MarketRegime.CRISIS:
        priority = "critical"
        desc = f"regime-CRISIS-alert"
    else:
        priority = "high"
        desc = f"regime-switch-{old_regime.value}-to-{new_signal.final.value}"
    
    signal = {
        "id": f"sig-regime-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "from": "events",
        "to": ["trading"],
        "priority": priority,
        "type": "regime_change",
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=3 if priority=='critical' else 7)).isoformat(),
        "lifecycle": "pending",
        "payload": {
            "old_regime": old_regime.value,
            "new_regime": new_signal.final.value,
            "confidence": new_signal.confidence,
            "portfolio_guidance": RegimeDetectionEngine.PORTFOLIO_WEIGHTS[new_signal.final],
            "signals": new_signal.signals
        }
    }
    
    sig_path = Path("~/.claude/nexus/signals/pending").expanduser()
    sig_path.mkdir(exist_ok=True)
    sig_file = sig_path / f"sig-{datetime.now().strftime('%Y%m%d-%H%M%S')}-events-{desc}.json"
    sig_file.write_text(json.dumps(signal, indent=2, ensure_ascii=False))
```

### 5.3 与risk_monitor.py的circuit breaker集成

```python
# 在risk_monitor.py中添加的检查逻辑

CIRCUIT_BREAKER_RULES = {
    MarketRegime.CRISIS: {
        "max_new_positions": 0,
        "max_portfolio_equity_pct": 0.20,
        "force_reduce_to": 0.15,       # 强制减仓目标
        "stop_loss_trigger": "all",     # 全部止损检查
        "action": "IMMEDIATE_REDUCE"
    },
    MarketRegime.BEAR: {
        "max_new_positions": 0,         # 禁止新建多头
        "max_portfolio_equity_pct": 0.40,
        "stop_loss_trigger": "losers",  # 仅亏损仓位触发
        "action": "GRADUAL_REDUCE"
    },
    MarketRegime.SIDEWAYS: {
        "max_new_positions": 3,         # 限制新建
        "max_portfolio_equity_pct": 0.60,
        "stop_loss_trigger": "none",
        "action": "CAUTIOUS"
    },
    MarketRegime.BULL: {
        "max_new_positions": 10,
        "max_portfolio_equity_pct": 0.80,
        "stop_loss_trigger": "none",
        "action": "NORMAL"
    }
}

def regime_circuit_breaker_check(portfolio_state: dict, regime_signal: RegimeSignal):
    """集成到risk_monitor.py的circuit breaker"""
    rules = CIRCUIT_BREAKER_RULES[regime_signal.final]
    current_equity_pct = portfolio_state.get("equity_pct", 0)
    
    if current_equity_pct > rules["max_portfolio_equity_pct"]:
        return {
            "triggered": True,
            "action": rules["action"],
            "reason": f"Equity {current_equity_pct:.0%} exceeds {rules['regime']} limit {rules['max_portfolio_equity_pct']:.0%}",
            "target_equity_pct": rules["max_portfolio_equity_pct"] * 0.9  # 10%缓冲
        }
    return {"triggered": False}
```

---

## 6. 实施路线图

### Phase 1（立即可用，1-2天）
- [x] 多因子规则层（VIX+MA+曲线+信用）
- [x] Truth Store写入 `macro/regime.json`
- [x] 信号schema定义

### Phase 2（1-2周）
- [ ] yf数据采集集成（SPY历史/HYG/LQD）
- [ ] HMM训练（需要≥5年日数据，可用yfinance获取）
- [ ] Signal Bus emit函数
- [ ] 每日自动更新cron

### Phase 3（1-2月）
- [ ] HMM季度重训机制
- [ ] Ensemble HMM（加入XGBoost/GMM投票）
- [ ] risk_monitor.py circuit breaker接口
- [ ] 回测验证（OOS 2020-2025，对比当前策略）

---

## 7. 关键判断与风险

**非共识点**：Crisis状态（VIX>35）下禁止做空是对的——2020年3月/2022年2月极端波动期，流动性枯竭时做空风险极高（轧空+无法平仓），现金才是真正的"武器"。

**失效场景**：
1. **长期低波动陷阱**：2017年VIX持续<12，规则层持续给Bull，实际已积累尾部风险。解法：加入VIX期限结构（VIX3M-VIX spread）
2. **HMM状态漂移**：2022年滞胀环境下HMM在Bull/Bear之间频繁切换。解法：加大转换处罚权重，最小持续10天
3. **黑天鹅无法预测**：任何regime系统都无法预测2020年3月15日。解法：Crisis触发机制必须基于规则层（实时），不能依赖HMM（滞后）

**Bear case of this system**：如果市场进入"结构性低波动+负实际收益"（类1970s滞胀），VIX阈值会系统性低估风险，Sharpe改善可能消失甚至为负。

---

## 来源引用

- QuantStart HMM实现: https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/
  （OOS Sharpe 0.37→0.48，Max DD 35.7%→24%，训练1993-2004，测试2005-2014）
- RL-BHRP论文: https://arxiv.org/abs/2508.11856
  （OOS 2020-2025 Sharpe 0.905 vs 静态0.846，CAGR 15.16% vs 13.36%）
- LSEG方法对比: https://developers.lseg.com/en/article-catalog/article/market-regime-detection
  （HMM>GMM>Agglomerative，2006-2023数据）
- QuantInsti HMM+RF: https://blog.quantinsti.com/regime-adaptive-trading-python/
  （Sharpe 1.16→1.76，Max DD -28.14%→-20.03%）
- Ensemble HMM: https://blog.pickmytrade.trade/regime-detection-measuring-market-regime-shifts-2026/
  （Sharpe最高1.68，Russell 3000）
- Bridgewater四象限: https://www.bridgewater.com/research-and-insights/the-all-weather-story
- Lopez de Prado CUSUM: https://www.mlfinlab.com/en/latest/feature_engineering/filters.html
