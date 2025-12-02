from decimal import Decimal, InvalidOperation
import gradio as gr
from typing import Optional, Any, Dict, List
from accounts import Account, get_share_price, Transaction
from accounts import AccountError, InsufficientFundsError, InsufficientSharesError, InvalidTransactionError, PriceLookupError

# Helper utilities


def fmt_money(d: Decimal) -> str:
    try:
        return f"${d:.2f}"
    except Exception:
        # Decimal formatting fallback
        return f"${str(d)}"


def account_to_summary_dict(acct: Optional[Account]) -> Dict[str, Any]:
    if acct is None:
        return {"message": "No account created yet."}
    s = acct.get_account_summary(price_provider=get_share_price)
    # Convert Decimals to strings for JSON-friendly display
    return {
        "cash_balance": fmt_money(s["cash_balance"]),
        "holdings": s["holdings"],
        "holdings_value": fmt_money(s["holdings_value"]),
        "total_equity": fmt_money(s["total_equity"]),
        "profit_loss_initial": (fmt_money(s["profit_loss_initial"]) if s["profit_loss_initial"] is not None else None),
        "profit_loss_net": fmt_money(s["profit_loss_net"]),
    }


def transactions_to_list(acct: Optional[Account]) -> List[Dict[str, Any]]:
    if acct is None:
        return []
    txns = acct.list_transactions()
    return [t.to_dict() for t in txns]


# Action handlers


def handle_create_account(initial_deposit: str, acct_state: Optional[Account]):
    try:
        if initial_deposit is None or initial_deposit == "":
            acct = Account()  # empty account
            msg = "Created empty account (no initial deposit)."
        else:
            try:
                dec = Decimal(initial_deposit)
            except InvalidOperation:
                return ("Invalid initial deposit amount.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
            acct = Account(initial_deposit=dec)
            msg = f"Created account with initial deposit {fmt_money(dec)}."
        return (msg, account_to_summary_dict(acct), transactions_to_list(acct), acct)
    except Exception as e:
        return (f"Error creating account: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)


def handle_deposit(amount: str, note: str, acct_state: Optional[Account]):
    if acct_state is None:
        return ("No account exists. Create an account first.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        dec = Decimal(amount)
    except InvalidOperation:
        return ("Invalid deposit amount.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        txn = acct_state.deposit(dec, note=note or None)
        msg = f"Deposited {fmt_money(txn.amount)}. New cash balance: {fmt_money(txn.cash_balance_after)}."
        return (msg, account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except AccountError as e:
        return (f"Deposit failed: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except Exception as e:
        return (f"Unexpected error during deposit: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)


def handle_withdraw(amount: str, note: str, acct_state: Optional[Account]):
    if acct_state is None:
        return ("No account exists. Create an account first.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        dec = Decimal(amount)
    except InvalidOperation:
        return ("Invalid withdraw amount.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        txn = acct_state.withdraw(dec, note=note or None)
        msg = f"Withdrew {fmt_money(-txn.amount)}. New cash balance: {fmt_money(txn.cash_balance_after)}."
        return (msg, account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except InsufficientFundsError as e:
        return (f"Withdrawal denied: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except AccountError as e:
        return (f"Withdraw failed: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except Exception as e:
        return (f"Unexpected error during withdraw: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)


def handle_buy(symbol: str, quantity: int, acct_state: Optional[Account]):
    if acct_state is None:
        return ("No account exists. Create an account first.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    if not symbol:
        return ("Symbol is required for buy.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        qty = int(quantity)
    except Exception:
        return ("Invalid quantity.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        txn = acct_state.buy(symbol, qty)  # uses default price provider
        msg = f"Bought {txn.quantity} shares of {txn.symbol} at {fmt_money(txn.price)} each for total {fmt_money(-txn.amount)}. New cash: {fmt_money(txn.cash_balance_after)}."
        return (msg, account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except InsufficientFundsError as e:
        return (f"Buy denied: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except PriceLookupError as e:
        return (f"Price lookup failed: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except AccountError as e:
        return (f"Buy failed: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except Exception as e:
        return (f"Unexpected error during buy: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)


def handle_sell(symbol: str, quantity: int, acct_state: Optional[Account]):
    if acct_state is None:
        return ("No account exists. Create an account first.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    if not symbol:
        return ("Symbol is required for sell.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        qty = int(quantity)
    except Exception:
        return ("Invalid quantity.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    try:
        txn = acct_state.sell(symbol, qty)
        msg = f"Sold {txn.quantity} shares of {txn.symbol} at {fmt_money(txn.price)} each for total {fmt_money(txn.amount)}. New cash: {fmt_money(txn.cash_balance_after)}."
        return (msg, account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except InsufficientSharesError as e:
        return (f"Sell denied: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except PriceLookupError as e:
        return (f"Price lookup failed: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except AccountError as e:
        return (f"Sell failed: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)
    except Exception as e:
        return (f"Unexpected error during sell: {str(e)}", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)


def handle_refresh(acct_state: Optional[Account]):
    return ("Refreshed.", account_to_summary_dict(acct_state), transactions_to_list(acct_state), acct_state)


# Build Gradio UI


with gr.Blocks(title="Trading Simulation Account Demo") as demo:
    gr.Markdown("# Trading Simulation Account (Demo)")
    gr.Markdown("Simple prototype UI to demonstrate the Account backend. Uses test prices for AAPL, TSLA, GOOGL.")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("## Account Creation")
            initial_deposit = gr.Textbox(label="Initial deposit (optional, e.g. 10000)", placeholder="e.g. 10000")
            create_btn = gr.Button("Create Account")

            gr.Markdown("## Cash Operations")
            deposit_amt = gr.Textbox(label="Deposit amount", placeholder="e.g. 500")
            deposit_note = gr.Textbox(label="Deposit note (optional)")
            deposit_btn = gr.Button("Deposit")

            withdraw_amt = gr.Textbox(label="Withdraw amount", placeholder="e.g. 200")
            withdraw_note = gr.Textbox(label="Withdraw note (optional)")
            withdraw_btn = gr.Button("Withdraw")

            gr.Markdown("## Trades")
            buy_symbol = gr.Textbox(label="Buy symbol", placeholder="AAPL, TSLA, GOOGL")
            buy_qty = gr.Number(label="Buy quantity", value=1, precision=0)
            buy_btn = gr.Button("Buy")

            sell_symbol = gr.Textbox(label="Sell symbol", placeholder="AAPL, TSLA, GOOGL")
            sell_qty = gr.Number(label="Sell quantity", value=1, precision=0)
            sell_btn = gr.Button("Sell")

        with gr.Column(scale=1):
            gr.Markdown("## Account Info")
            status = gr.Textbox(label="Status", interactive=False)
            summary = gr.JSON(label="Summary")
            txns = gr.JSON(label="Transactions")

            refresh_btn = gr.Button("Refresh Summary")

    # Hidden state to hold the Account instance
    acct_state = gr.State(value=None)

    # Wire buttons
    create_btn.click(fn=handle_create_account, inputs=[initial_deposit, acct_state], outputs=[status, summary, txns, acct_state])
    deposit_btn.click(fn=handle_deposit, inputs=[deposit_amt, deposit_note, acct_state], outputs=[status, summary, txns, acct_state])
    withdraw_btn.click(fn=handle_withdraw, inputs=[withdraw_amt, withdraw_note, acct_state], outputs=[status, summary, txns, acct_state])
    buy_btn.click(fn=handle_buy, inputs=[buy_symbol, buy_qty, acct_state], outputs=[status, summary, txns, acct_state])
    sell_btn.click(fn=handle_sell, inputs=[sell_symbol, sell_qty, acct_state], outputs=[status, summary, txns, acct_state])
    refresh_btn.click(fn=handle_refresh, inputs=[acct_state], outputs=[status, summary, txns, acct_state])

if __name__ == "__main__":
    demo.launch()