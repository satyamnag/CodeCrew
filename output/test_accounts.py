import pytest
from datetime import datetime, timedelta
import copy

import accounts
from accounts import Account, Transaction, Position
from accounts import (
    AccountError,
    InvalidAmountError,
    InsufficientFundsError,
    InsufficientSharesError,
    UnknownSymbolError,
    TransactionError,
    get_share_price,
)


def test_get_share_price_known_symbols_case_insensitive():
    assert get_share_price('AAPL') == 150.0
    assert get_share_price('aapl') == 150.0
    assert get_share_price('TsLa') == 700.0
    assert get_share_price('GOOGL') == 2800.0

def test_get_share_price_unknown_raises():
    with pytest.raises(UnknownSymbolError):
        get_share_price('UNKNOWN')
    with pytest.raises(UnknownSymbolError):
        get_share_price(None)

def test_account_init_and_initial_deposit_validation():
    with pytest.raises(ValueError):
        Account('', initial_deposit=0)
    with pytest.raises(InvalidAmountError):
        Account('u1', initial_deposit=-10)
    # valid initial deposit records a deposit transaction
    acct = Account('user_init', initial_deposit=100.0)
    assert acct.get_cash_balance() == 100.0
    assert acct.total_deposits() == 100.0
    txs = acct.list_transactions()
    assert len(txs) == 1
    assert txs[0].type == 'deposit'
    assert txs[0].note == 'initial_deposit'

def test_deposit_and_withdraw_flow_and_errors():
    acct = Account('u2')
    with pytest.raises(InvalidAmountError):
        acct.deposit(0)
    tx = acct.deposit(250.567)
    # rounding to cents
    assert acct.get_cash_balance() == 250.57
    assert tx.total == 250.57
    assert acct.total_deposits() == 250.57

    with pytest.raises(InvalidAmountError):
        acct.withdraw(0)
    with pytest.raises(InsufficientFundsError):
        acct.withdraw(9999)
    wtx = acct.withdraw(50.123)
    assert acct.get_cash_balance() == 200.45  # 250.57 - 50.12
    assert wtx.total == pytest.approx(-50.12, rel=1e-9)
    assert acct.total_withdrawals() == pytest.approx(50.12, rel=1e-9)

def test_buy_updates_positions_and_avg_cost_and_errors():
    acct = Account('u3')
    acct.deposit(1000.0)
    # invalid symbol and amount
    with pytest.raises(TransactionError):
        acct.buy('', 1)
    with pytest.raises(InvalidAmountError):
        acct.buy('AAPL', 0)
    # buy within funds
    tx1 = acct.buy('AAPL', 2, price=100.0)
    assert acct.get_cash_balance() == 800.0
    pos = acct.get_holdings()['AAPL']
    assert pos.quantity == 2
    assert pos.avg_cost == 100.0
    # buy additional shares at different price to change avg_cost
    tx2 = acct.buy('AAPL', 3, price=110.0)
    pos = acct.get_holdings()['AAPL']
    assert pos.quantity == 5
    # expected new avg cost = (2*100 + 3*110)/5 = 106.0
    assert pos.avg_cost == 106.0
    # Insufficient funds for a large buy
    with pytest.raises(InsufficientFundsError):
        acct.buy('GOOGL', 1000)

def test_sell_updates_cash_positions_realized_pnl_and_errors():
    acct = Account('u4')
    acct.deposit(1000.0)
    acct.buy('AAPL', 5, price=100.0)
    # invalid sell symbol and amount
    with pytest.raises(TransactionError):
        acct.sell('', 1)
    with pytest.raises(InvalidAmountError):
        acct.sell('AAPL', 0)
    # insufficient shares
    with pytest.raises(InsufficientSharesError):
        acct.sell('AAPL', 10)
    # sell some shares at profit
    prev_cash = acct.get_cash_balance()
    sell_tx = acct.sell('AAPL', 2, price=120.0)
    # proceeds = 240.00
    assert acct.get_cash_balance() == prev_cash + 240.0
    # realized pnl per share = 20*2 = 40
    breakdown = acct.get_realized_unrealized_pnl_breakdown(lambda s: 120.0)
    assert breakdown['realized_pnl'] == 40.0
    # remaining position quantity
    holdings = acct.get_holdings()
    assert holdings['AAPL'].quantity == 3
    # sell remaining shares to wipe position
    acct.sell('AAPL', 3, price=100.0)  # no pnl on these
    holdings = acct.get_holdings()
    assert 'AAPL' not in holdings

def test_get_holdings_returns_deep_copy():
    acct = Account('u5')
    acct.deposit(500.0)
    acct.buy('TSLA', 1, price=100.0)
    holdings = acct.get_holdings()
    holdings['TSLA'].quantity = 9999
    # original should not be modified
    assert acct.get_holdings()['TSLA'].quantity == 1

def test_portfolio_value_with_custom_resolver_and_defaults():
    acct = Account('u6')
    acct.deposit(1000.0)
    acct.buy('AAPL', 2, price=150.0)
    # default resolver for AAPL returns 150.0, so portfolio = cash + 2*150
    expected = acct.get_cash_balance() + 2 * 150.0
    assert acct.get_portfolio_value() == expected
    # custom resolver that sets AAPL to 200
    assert acct.get_portfolio_value(lambda s: 200.0) == acct.get_cash_balance() + 2 * 200.0

def test_profit_loss_vs_initial_and_net_invested():
    acct = Account('u7')
    acct.deposit(1000.0)
    acct.buy('AAPL', 2, price=150.0)
    # change price to compute portfolio
    pl_initial = acct.get_profit_loss('initial', lambda s: 150.0)
    assert pl_initial == pytest.approx(0.0, abs=1e-9)
    # deposit more and withdraw
    acct.deposit(100.0)
    acct.withdraw(50.0)
    # net_invested = deposits - withdrawals = 1100 - 50 = 1050
    pl_net = acct.get_profit_loss('net_invested', lambda s: 150.0)
    assert pl_net == acct.get_portfolio_value(lambda s: 150.0) - acct.total_deposits() + acct.total_withdrawals() + 0  # sanity check

def test_list_transactions_filters():
    acct = Account('u8')
    t0 = datetime.utcnow()
    acct.deposit(100.0, timestamp=t0 - timedelta(seconds=10))
    acct.buy('AAPL', 1, price=150.0, timestamp=t0)
    acct.sell('AAPL', 1, price=160.0, timestamp=t0 + timedelta(seconds=10))
    # filter by type
    deposits = acct.list_transactions(tx_type='deposit')
    assert len(deposits) == 1
    buys = acct.list_transactions(tx_type='buy')
    assert len(buys) == 1
    # filter by symbol
    sells_aapl = acct.list_transactions(symbol='AAPL')
    assert len(sells_aapl) == 2  # buy and sell
    # filter by time window
    middle = acct.list_transactions(start=t0 - timedelta(seconds=1), end=t0 + timedelta(seconds=1))
    assert len(middle) == 1

def test_serialization_roundtrip():
    acct = Account('u9')
    acct.deposit(1000.0)
    acct.buy('AAPL', 2, price=150.0)
    acct.sell('AAPL', 1, price=155.0)
    data = acct.to_dict()
    acct2 = Account.from_dict(data)
    assert acct2.get_cash_balance() == acct.get_cash_balance()
    assert acct2._initial_deposit == acct._initial_deposit
    # positions and transactions lengths
    assert len(acct2.get_holdings()) == len(acct.get_holdings())
    assert len(acct2.list_transactions()) == len(acct.list_transactions())
