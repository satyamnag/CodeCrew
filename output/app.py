from datetime import datetime
import gradio as gr
from accounts import Account, get_share_price, AccountError

# Simple global single-account for demo
_account = None  # type: Account | None

# Helpers
def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"

def _ensure_account():
    if _account is None:
        raise RuntimeError("No account exists. Create an account first.")

def create_account(user_id: str, initial_deposit: float):
    global _account
    if not user_id:
        return "Error: user_id must be provided."
    try:
        if initial_deposit is None or initial_deposit <= 0:
            # allow creating account with zero deposit
            _account = Account(user_id=user_id, initial_deposit=0.0)
            return f"Account created for '{user_id}' with no initial deposit."
        else:
            _account = Account(user_id=user_id, initial_deposit=float(initial_deposit))
            return f"Account created for '{user_id}' with initial deposit {_fmt_money(initial_deposit)}."
    except AccountError as e:
        return f"Account creation error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"

def deposit(amount: float, note: str):
    try:
        _ensure_account()
        tx = _account.deposit(float(amount), note=note or None)
        return f"Deposit successful: {tx.total:+.2f}. New cash balance: {_fmt_money(_account.get_cash_balance())}"
    except Exception as e:
        return f"Deposit failed: {e}"

def withdraw(amount: float, note: str):
    try:
        _ensure_account()
        tx = _account.withdraw(float(amount), note=note or None)
        return f"Withdraw successful: {tx.total:+.2f}. New cash balance: {_fmt_money(_account.get_cash_balance())}"
    except Exception as e:
        return f"Withdraw failed: {e}"

def buy(symbol: str, quantity: float):
    try:
        _ensure_account()
        if not symbol:
            return "Buy failed: symbol required."
        tx = _account.buy(symbol, float(quantity))
        return (f"Bought {tx.quantity} {tx.symbol} @ {_fmt_money(tx.price)} each. "
                f"Cash after trade: {_fmt_money(_account.get_cash_balance())}")
    except Exception as e:
        return f"Buy failed: {e}"

def sell(symbol: str, quantity: float):
    try:
        _ensure_account()
        if not symbol:
            return "Sell failed: symbol required."
        tx = _account.sell(symbol, float(quantity))
        return (f"Sold {tx.quantity} {tx.symbol} @ {_fmt_money(tx.price)} each. "
                f"Cash after trade: {_fmt_money(_account.get_cash_balance())}")
    except Exception as e:
        return f"Sell failed: {e}"

def show_holdings():
    try:
        _ensure_account()
        holdings = _account.get_holdings()
        if not holdings:
            return "No holdings."
        lines = []
        total_positions_value = 0.0
        for sym, pos in holdings.items():
            price = get_share_price(sym)
            value = price * pos.quantity
            total_positions_value += value
            lines.append(f"{sym}: qty={pos.quantity} avg_cost={_fmt_money(pos.avg_cost)} "
                         f"market_price={_fmt_money(price)} value={_fmt_money(value)}")
        lines.append(f"Cash: {_fmt_money(_account.get_cash_balance())}")
        lines.append(f"Total positions value: {_fmt_money(total_positions_value)}")
        lines.append(f"Portfolio value (cash + positions): {_fmt_money(_account.get_portfolio_value())}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error showing holdings: {e}"

def show_portfolio():
    try:
        _ensure_account()
        cash = _account.get_cash_balance()
        pv = _account.get_portfolio_value()
        pnl_initial = _account.get_profit_loss(reference='initial')
        pnl_net = _account.get_profit_loss(reference='net_invested')
        pnl_break = _account.get_realized_unrealized_pnl_breakdown()
        lines = [
            f"Cash: {_fmt_money(cash)}",
            f"Portfolio value (cash + positions): {_fmt_money(pv)}",
            f"Profit/Loss vs initial deposit: {_fmt_money(pnl_initial)}",
            f"Profit/Loss vs net invested: {_fmt_money(pnl_net)}",
            f"Realized PnL: {_fmt_money(pnl_break['realized_pnl'])}",
            f"Unrealized PnL: {_fmt_money(pnl_break['unrealized_pnl'])}",
            f"Total PnL: {_fmt_money(pnl_break['total_pnl'])}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error showing portfolio: {e}"

def list_transactions(limit: int = 50):
    try:
        _ensure_account()
        txs = _account.list_transactions()
        if not txs:
            return "No transactions."
        lines = []
        # show most recent first
        for tx in sorted(txs, key=lambda t: t.timestamp, reverse=True)[:limit]:
            ts = tx.timestamp.isoformat()
            typ = tx.type
            sym = tx.symbol or ""
            qty = f"{tx.quantity}" if tx.quantity is not None else ""
            price = _fmt_money(tx.price) if tx.price is not None else ""
            total = _fmt_money(tx.total)
            bal = _fmt_money(tx.balance_after)
            note = f" note={tx.note}" if tx.note else ""
            lines.append(f"{ts} | {typ.upper():6} | {sym:5} | qty={qty:7} price={price:10} total={total:10} balance={bal:10}{note}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing transactions: {e}"

def refresh_summary():
    try:
        if _account is None:
            return "No account."
        return show_portfolio()
    except Exception as e:
        return f"Error refreshing: {e}"

# Build Gradio UI
with gr.Blocks(title="Trading Account Demo") as demo:
    gr.Markdown("# Simple Trading Account Demo")
    gr.Markdown("Create an account, deposit/withdraw cash, buy/sell shares (AAPL/TSLA/GOOGL supported).")

    with gr.Row():
        with gr.Column():
            user_id = gr.Textbox(label="User ID", value="demo_user", info="Single-user demo")
            initial_deposit = gr.Number(label="Initial deposit (USD)", value=10000.0)
            create_btn = gr.Button("Create Account")
            create_out = gr.Textbox(label="Create Account Output", interactive=False)
        with gr.Column():
            refresh_btn = gr.Button("Refresh Portfolio Summary")
            summary_out = gr.Textbox(label="Portfolio Summary", lines=8, interactive=False)
            holdings_btn = gr.Button("Show Holdings")
            holdings_out = gr.Textbox(label="Holdings", lines=8, interactive=False)

    with gr.Row():
        with gr.Column():
            gr.Markdown("### Cash operations")
            deposit_amt = gr.Number(label="Deposit Amount", value=1000.0)
            deposit_note = gr.Textbox(label="Deposit Note (optional)")
            deposit_btn = gr.Button("Deposit")
            deposit_out = gr.Textbox(label="Deposit Output", interactive=False)

            withdraw_amt = gr.Number(label="Withdraw Amount", value=500.0)
            withdraw_note = gr.Textbox(label="Withdraw Note (optional)")
            withdraw_btn = gr.Button("Withdraw")
            withdraw_out = gr.Textbox(label="Withdraw Output", interactive=False)
        with gr.Column():
            gr.Markdown("### Trade operations")
            trade_symbol = gr.Textbox(label="Symbol (AAPL/TSLA/GOOGL)", value="AAPL")
            trade_qty = gr.Number(label="Quantity", value=1)
            buy_btn = gr.Button("Buy")
            buy_out = gr.Textbox(label="Buy Output", interactive=False)
            sell_btn = gr.Button("Sell")
            sell_out = gr.Textbox(label="Sell Output", interactive=False)

    with gr.Row():
        tx_btn = gr.Button("List Transactions")
        tx_out = gr.Textbox(label="Transactions", lines=12, interactive=False)

    # Bind actions
    create_btn.click(fn=create_account, inputs=[user_id, initial_deposit], outputs=create_out)
    deposit_btn.click(fn=deposit, inputs=[deposit_amt, deposit_note], outputs=deposit_out)
    withdraw_btn.click(fn=withdraw, inputs=[withdraw_amt, withdraw_note], outputs=withdraw_out)
    buy_btn.click(fn=buy, inputs=[trade_symbol, trade_qty], outputs=buy_out)
    sell_btn.click(fn=sell, inputs=[trade_symbol, trade_qty], outputs=sell_out)

    holdings_btn.click(fn=show_holdings, inputs=None, outputs=holdings_out)
    tx_btn.click(fn=list_transactions, inputs=[], outputs=tx_out)
    refresh_btn.click(fn=refresh_summary, inputs=None, outputs=summary_out)

    # Also update summary/holdings after operations by chaining (simple UX)
    def _after_op(_):
        # return updated portfolio summary and holdings and transactions
        return show_portfolio(), show_holdings(), list_transactions()
    # attach to several buttons to update the summary blocks and transactions
    deposit_btn.click(fn=_after_op, inputs=None, outputs=[summary_out, holdings_out, tx_out])
    withdraw_btn.click(fn=_after_op, inputs=None, outputs=[summary_out, holdings_out, tx_out])
    buy_btn.click(fn=_after_op, inputs=None, outputs=[summary_out, holdings_out, tx_out])
    sell_btn.click(fn=_after_op, inputs=None, outputs=[summary_out, holdings_out, tx_out])
    create_btn.click(fn=_after_op, inputs=None, outputs=[summary_out, holdings_out, tx_out])

if __name__ == "__main__":
    demo.launch()
