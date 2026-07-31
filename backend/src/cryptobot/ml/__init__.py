"""Machine-learning experimentation (Phase 5).

ML here is decision support under strict discipline, never a guaranteed
prediction system:

- Features are causal and versioned; labels are forward returns after costs.
- Splits are chronological with an embargo gap; the test period is untouched.
- Every run is seeded and reproducible.
- A candidate model is promoted only by beating the deployed champion on
  predefined criteria (ml/promotion.py) — never by recent live performance
  alone, and never automatically retrained from the bot's own trades.
- Drift monitoring (PSI) demotes trust in a model whose input distribution
  has moved away from its training data.

Why no deep learning yet: with hourly bars, a few years of data yields only
tens of thousands of samples with a very low signal-to-noise ratio. Gradient-
boosted trees and logistic regression match or beat neural networks in this
regime while remaining inspectable, cheap to validate, and hard to overfit
silently. Deep learning becomes worth its variance and opacity only after
clean data volume grows (tick/order-book level) AND classical baselines have
demonstrated a stable, cost-surviving edge to improve upon.
"""
