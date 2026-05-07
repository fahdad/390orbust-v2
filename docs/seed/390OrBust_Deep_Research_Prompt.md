# Deep Research Prompt: Minute-Bar Algorithmic Trading Literature Survey

## Instructions for the Research Agent

I need a comprehensive literature survey covering academic papers, industry white papers, practitioner blog posts, and technical reports relevant to building a minute-level algorithmic trading system for US equities (specifically energy sector stocks). This survey will serve as a reference library for designing and evaluating trading strategies.

Organize your findings into the sections below. For each source, provide: title, authors, year, venue/publication, a 2-3 sentence summary of the key finding or contribution, and a direct link or DOI where available. Prioritize recency (2020-2026) but include foundational older works where they remain the definitive reference.

---

## Section 1: Intraday Return Prediction at Minute-Level Horizons

Find papers and articles addressing:

- Predictability of 1-minute, 5-minute, and 15-minute equity returns using price/volume data
- Statistical properties of minute-bar returns (distribution, autocorrelation structure, volatility clustering at intraday scale)
- Known predictive signals at sub-hourly horizons: momentum, mean-reversion, volume-price dynamics, intraday seasonality patterns (e.g., U-shaped volume curve, opening/closing auction effects)
- The boundary between where prediction is feasible vs noise at minute-level granularity
- Studies that quantify the realistic Sharpe ratio achievable from price-based signals at these horizons
- Any research specifically on energy sector equities or commodity-correlated stocks at intraday horizons

## Section 2: Deep Learning Architectures for Financial Time Series

Find papers comparing or proposing:

- **Temporal Convolutional Networks (TCN)** for financial prediction — especially Bai et al. (2018) foundational comparison and subsequent financial applications
- **Transformer architectures** adapted for financial time series — attention mechanisms, positional encoding for irregular time series, causal masking for look-ahead prevention
- **LSTM and GRU variants** — with emphasis on proper training practices (gradient clipping, learning rate scheduling, state management) that address the known instability issues in financial applications
- **Conv1D and Conv2D approaches** — treating price/feature matrices as images, dilated causal convolutions
- **Squeeze-and-Excitation (SE) networks** applied to time series — channel attention for feature re-weighting
- **Hybrid architectures** — CNN-LSTM, CNN-Transformer, attention-augmented recurrent networks
- **Multi-horizon prediction** — architectures that predict multiple future timesteps simultaneously, multi-task learning for correlated targets
- **Ensemble methods** — combining multiple model architectures, stacking, mixture of experts for financial prediction
- Head-to-head comparisons between architectures on financial data (not NLP or vision benchmarks)

## Section 3: Feature Engineering for Intraday Trading

Find research on:

- Which technical indicators have empirical support at intraday horizons (RSI, ATR, VWAP-based features, order flow imbalance)
- Cross-sectional features: cross-asset momentum, sector-relative signals, lead-lag relationships between correlated stocks
- Volume and trade-count based features: volume-weighted signals, unusual volume detection, trade size distribution features
- Calendar/time-of-day features: intraday seasonality modeling, day-of-week effects at minute level
- Feature importance and selection methods specifically for financial time series (permutation importance limitations, SHAP for temporal data, conditional feature importance)
- Dimensionality reduction for large feature sets in financial contexts (PCA, autoencoders, attention-based feature selection)
- The specific problem of look-ahead bias in feature engineering and known mitigation techniques

## Section 4: Backtesting Methodology and Pitfalls

Find papers and practitioner articles on:

- Walk-forward validation / temporal cross-validation — proper implementation, expanding vs rolling window tradeoffs
- Combinatorial purged cross-validation (de Prado's work and extensions)
- Common backtesting biases: lookahead bias, survivorship bias, overfitting to the backtest, selection bias from multiple hypothesis testing
- Transaction cost modeling at minute-bar frequency: spread estimation, slippage models, market impact for small accounts vs large accounts
- The "backtest overfitting" problem — probability of backtest overfitting (PBO), deflated Sharpe ratio, minimum backtest length
- Papers that specifically address the gap between backtested and live performance in intraday systems
- Realistic performance benchmarks: what Sharpe ratios and accuracy levels have been independently verified in published research for minute-bar strategies

## Section 5: Risk Management for Systematic Trading

Find research on:

- Position sizing methods: Kelly criterion and fractional Kelly, volatility-targeting, risk parity at the single-strategy level
- Dynamic position sizing based on regime detection or volatility state
- Drawdown control: maximum drawdown limits, trailing stop methodologies, time-based stops vs price-based stops
- Portfolio-level risk for multi-strategy systems: correlation between strategies, strategy-level capital allocation
- The specific risks of intraday mean-reversion vs momentum strategies and how risk management differs between them
- Tail risk in intraday equity trading: flash crash exposure, gap risk, liquidity withdrawal events

## Section 6: Signal-to-Execution Pipeline Design

Find industry articles, blog posts, and papers on:

- Architecture patterns for algorithmic trading systems: event-driven vs vectorized backtesting, live trading system design
- The signal-to-order pipeline: signal generation, position sizing, order management, execution
- Latency considerations for minute-bar vs tick-level systems
- Open-source framework comparisons and lessons learned: Zipline, Backtrader, QuantConnect Lean, Jesse, VectorBT — what works, what breaks, what architectural decisions they made and why
- Industry blog posts from quant practitioners on system architecture (e.g., QuantStart, Robot Wealth, Ernie Chan's blog, papers from AQR, Man Group/AHL)
- The human-in-the-loop pattern in systematic trading: how firms handle discretionary overrides of systematic signals

## Section 7: Energy Sector Specific Signals

Find research on:

- Crude oil price as a leading/lagging indicator for energy equity prices at intraday horizons
- Cross-asset signals: VIX-energy correlation, yield curve effects on energy stocks, natural gas/oil spread as a signal
- OPEC event effects on intraday energy stock volatility and predictability
- Earnings season effects specific to energy companies
- Sector rotation signals at intraday frequency — when does money flow into/out of energy stocks within a trading day
- Lead-lag relationships within XLE components (e.g., does XOM lead smaller names like CTRA or APA?)

## Section 8: Classification vs Regression for Trading Signals

Find research on:

- The tradeoffs between predicting returns (regression) vs predicting direction (classification) in trading contexts
- Multi-class classification (up/flat/down) vs binary (up/down) — how the "flat" class affects model performance
- Threshold selection for converting continuous returns into classification labels — fixed vs volatility-adaptive thresholds
- Label definition: log returns vs simple returns, volatility-scaled targets, rank-based targets
- Class imbalance handling in financial classification: focal loss, class weighting, synthetic oversampling risks in time series
- Studies comparing model performance across different label definitions on the same underlying data

## Section 9: Regime Detection and Adaptivity

Find research on:

- Hidden Markov Models for market regime detection at intraday scale
- Online learning / adaptive models that adjust to changing market conditions
- Concept drift in financial time series — detection and adaptation methods
- When to retrain: scheduled retraining vs trigger-based retraining
- Structural breaks in intraday volatility patterns and their impact on model performance
- Meta-learning approaches: learning when your model is likely to perform well vs poorly

## Section 10: Alternative and Supplementary Data Sources

Find research on:

- Level 2 / order book data as predictive features for minute-level trading: order flow imbalance, book depth asymmetry, queue position
- Options market signals (put-call ratios, unusual options activity) as leading indicators for underlying equity movement
- Sentiment data (news, social media) at intraday frequency — does it add alpha beyond price/volume?
- Economic calendar events (FOMC, EIA inventory reports, jobs reports) and their impact windows on energy stocks
- Cross-market signals: futures-spot basis, ETF arbitrage signals, ADR/domestic spread for dual-listed energy companies

---

## Output Format

For each section, provide:

1. **Foundational works** (the "must-read" papers that established the field or technique — typically pre-2020)
2. **Current state-of-the-art** (2022-2026 papers representing the latest thinking)
3. **Practitioner perspectives** (blog posts, industry talks, or white papers from actual trading firms or experienced quants)
4. **Key takeaways** — A brief synthesis per section: what does the literature collectively say about what works, what doesn't, and what remains unresolved?

For each individual source, format as:
```
**Title** (Year)
Authors | Venue/Source
Summary: [2-3 sentences on key finding]
Link: [URL or DOI]
Relevance: [One line on why this matters for a minute-bar energy sector trading system]
```

At the end, provide a **synthesis section** identifying:
- The 10 most important papers across all sections that I should read first
- The 3-5 biggest open questions in this problem space where the literature doesn't have clear answers
- Any consensus findings that should be treated as hard constraints on system design (e.g., "transaction costs dominate at horizons below X minutes" or "classification outperforms regression when Y")
