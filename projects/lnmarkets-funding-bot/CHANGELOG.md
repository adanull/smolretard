# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] — 2026-03-22

### Added
- Initial project structure
- Funding rate arbitrage strategy (`strategy.py`)
  - Analyzes funding settlement history for trend + strength
  - Opens shorts on positive funding, longs on negative funding
  - Closes positions when funding flips
- LN Markets API client wrapper using official SDK v3 (`lnm_client.py`)
- Risk manager with daily loss limit + kill switch (`risk_manager.py`)
- Bot main loop with `--once` and `--status` modes (`bot.py`)
- Dry-run mode (paper trading) as default
- AGENTS.md for cross-agent context
- README.md with full setup instructions
