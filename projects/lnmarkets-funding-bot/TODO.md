# TODO

## 🔴 Blockers (before first run)
- [ ] Install `python3.11-venv` on Pi (`sudo apt install -y python3.11-venv`)
- [ ] Set up virtualenv and install deps
- [ ] Configure API keys in `.env`

## 🟡 Pre-Live (before switching to mainnet)
- [ ] Validate funding data parsing against real testnet data
- [ ] Run dry-mode for a few days, verify signals make sense
- [ ] Confirm stop-loss/take-profit calculations are correct
- [ ] Test kill switch and daily reset
- [ ] Tune `FUNDING_RATE_THRESHOLD` based on observed testnet rates

## 🟢 Enhancements
- [ ] **Delta-neutral mode** — hold spot BTC to hedge short exposure, making it true arb
- [ ] **Grid trading layer** — add grid on top of funding strategy for extra income in choppy markets
- [ ] **Telegram alerts** — push trade open/close/errors via OpenClaw notifications
- [ ] **Backtest engine** — test against historical LN Markets funding rate data
- [ ] **Dashboard** — simple web status page (balance, open positions, daily P&L, funding history)
- [ ] **Websocket integration** — use LN Markets websocket for real-time price/funding instead of polling
- [ ] **Cross-margin support** — option to use cross-margin mode instead of isolated
- [ ] **Multi-position scaling** — scale into positions as funding strengthens instead of all-at-once
- [ ] **Funding rate prediction** — use open interest + price premium to anticipate rate changes

## 💡 Ideas
- Run via OpenClaw cron (`--once` mode) instead of continuous loop for lighter resource usage
- Auto-deposit from Lightning wallet when balance runs low
- Weekly P&L summary sent via Telegram
- Compare funding rates across exchanges to find best opportunity
