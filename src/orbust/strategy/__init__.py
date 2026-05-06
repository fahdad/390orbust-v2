"""Strategy Framework — define, train, and run trading strategies.

Components:
    base:       Strategy ABC (build_model, train, predict, save, load)
    engine:     Strategy loading, GPU memory management
    training:   Training harness (data materialization, logging)
    signals:    Signal types, serialization
"""
