"""Execution Layer — signals to orders, risk gates, broker integration.

Components:
    interpreter:   Signal → ProposedAction conversion
    risk:          RiskGate (system + strategy tiers)
    broker:        BrokerAdapter ABC
    alpaca_broker: AlpacaBrokerAdapter implementation
    portfolio:     StrategyBook, position tracking, PnL
    approval:      Human-in-the-loop workflow (supervised mode)
"""
