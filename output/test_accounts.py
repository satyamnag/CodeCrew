import os
import csv
import tempfile
from decimal import Decimal
from datetime import datetime, timedelta
import pytest

import accounts
from accounts import (
    Account,
    Transaction,
    PriceLookupError,
    InsufficientFundsError,
    InsufficientSharesError,
    InvalidTransactionError,
    _quantize_money,
)


def test_initial_deposit_and_deposit_behavior():
    ts = datetime(2021, 1, 1, 12, 0, 0)
    acct = Account(account_id="acct1", initial_deposit=Decimal('100.00'), timestamp=ts)
    # initial deposit should be recorded
    assert acct._initial_deposit == Decimal('100.00')
    assert acct.get_cash_balance() == Decimal('100.00')
    # make another deposit; initial_deposit should stay the same
    txn = acct.deposit(Decimal('50.00'), timestamp=ts + timedelta(minutes=1), note='second')
    assert txn.type == 'deposit'
    assert txn.note == 'second'
    assert acct._initial_deposit == Decimal('100.00')
    assert acct.get_cash_balance() == Decimal('150.00')

def test_invalid_deposits():
    acct = Account()
    with pytest.raises(InvalidTransactionError):
        acct.deposit(Decimal('-10'))
    with pytest.raises(InvalidTransactionError):
        acct.deposit(None)

def test_withdraw_success_and_insufficient():
    acct = Account()
    acct.deposit(Decimal('200.00'))
    wtxn = acct.withdraw(Decimal('50.00'))
    assert wtxn.type == 'withdraw'
    assert acct.get_cash_balance() == Decimal('150.00')
    with pytest.raises(InsufficientFundsError):
        acct.withdraw(Decimal('1000.00'))
    with pytest.raises(InvalidTransactionError):
        acct.withdraw(None)

def test_buy_and_sell_and_holdings_and_portfolio_and_pl():
    ts = datetime(2021, 6, 1, 10, 0, 0)
    acct = Account(initial_deposit=Decimal('1000.00'), timestamp=ts)
    # Buy 2 AAPL at provider price 150 => cost 300
    btxn = acct.buy('AAPL', 2, timestamp=ts + timedelta(minutes=1))
    assert btxn.type == 'buy'
    assert btxn.quantity == 2
    assert btxn.price == Decimal('150.00')
    assert acct.get_cash_balance() == Decimal('700.00')
    holdings = acct.get_holdings()
    assert holdings == {'AAPL': 2}
    # Sell 1 AAPL at explicit price 160
    stxn = acct.sell('AAPL', 1, price=Decimal('160.00'), timestamp=ts + timedelta(minutes=2))
    assert stxn.type == 'sell'
    assert stxn.quantity == 1
    assert acct.get_cash_balance() == Decimal('860.00')
    holdings = acct.get_holdings()
    assert holdings == {'AAPL': 1}
    # Portfolio value uses provider price for AAPL (150)
    pv = acct.get_portfolio_value()
    # cash 860 + 1 * 150 = 1010
    assert pv == Decimal('1010.00')
    # Profit/loss initial: equity - initial_deposit = 1010 - 1000 = 10
    pl = acct.get_profit_loss(basis='initial')
    assert pl == Decimal('10.00')
    # Profit/loss net: equity - net deposits (deposits - withdrawals). Net deposits = 1000
    pl_net = acct.get_profit_loss(basis='net')
    assert pl_net == Decimal('10.00')

def test_insufficient_funds_for_buy_and_insufficient_shares_for_sell():
    acct = Account()
    acct.deposit(Decimal('100.00'))
    with pytest.raises(InsufficientFundsError):
        acct.buy('TSLA', 1, price=Decimal('700.00'))
    acct2 = Account(initial_deposit=Decimal('1000.00'))
    with pytest.raises(InsufficientSharesError):
        acct2.sell('AAPL', 1)

def test_price_lookup_errors_propagate():
    def bad_provider(symbol, ts=None):
        raise RuntimeError('no price')
    acct = Account(initial_deposit=Decimal('500.00'))
    with pytest.raises(accounts.PriceLookupError):
        acct.buy('UNKNOWN', 1, price_provider=bad_provider)
    # get_portfolio_value should propagate PriceLookupError when holdings exist and provider fails
    acct.buy('AAPL', 1)
    with pytest.raises(accounts.PriceLookupError):
        acct.get_portfolio_value(price_provider=bad_provider)

def test_list_transactions_filters_and_get_transaction_by_id():
    base = datetime(2022, 1, 1, 9, 0, 0)
    acct = Account()
    t1 = acct.deposit(Decimal('100.00'), timestamp=base)
    t2 = acct.deposit(Decimal('50.00'), timestamp=base + timedelta(hours=1))
    t3 = acct.withdraw(Decimal('20.00'), timestamp=base + timedelta(hours=2))
    all_txns = acct.list_transactions()
    assert len(all_txns) == 3
    # filter by start/end
    mid_txns = acct.list_transactions(start=base + timedelta(minutes=30), end=base + timedelta(hours=1, minutes=30))
    assert len(mid_txns) == 1
    assert mid_txns[0].id == t2.id
    # filter by types
    deposits = acct.list_transactions(types=['deposit'])
    assert all(txn.type == 'deposit' for txn in deposits)
    # get by id
    assert acct.get_transaction_by_id(t3.id).id == t3.id
    assert acct.get_transaction_by_id('nonexistent') is None

def test_to_dict_and_load_from_dict_roundtrip():
    acct = Account(initial_deposit=Decimal('300.00'))
    acct.buy('AAPL', 1)
    acct.deposit(Decimal('50.00'))
    data = acct.to_dict()
    loaded = Account.load_from_dict(data)
    assert loaded.account_id == data['account_id']
    assert loaded.get_cash_balance() == acct.get_cash_balance()
    assert loaded.get_holdings() == acct.get_holdings()
    assert len(loaded.list_transactions()) == len(acct.list_transactions())

def test_reconcile_holdings_detects_negative():
    ts = datetime(2023, 1, 1, 9, 0, 0)
    acct = Account(initial_deposit=Decimal('500.00'), timestamp=ts)
    acct.buy('AAPL', 1, timestamp=ts + timedelta(minutes=1))
    # craft a sell of 2 shares (greater than held) and append directly
    bad_sell = Transaction(
        id='bad1',
        timestamp=ts + timedelta(minutes=2),
        type='sell',
        amount=Decimal('300.00'),
        symbol='AAPL',
        quantity=2,
        price=Decimal('150.00'),
        cash_balance_after=Decimal('0'),
        note='corrupted',
    )
    # append using internal method (it will accept as it doesn't validate holdings)
    acct._append_transaction(bad_sell)
    with pytest.raises(AssertionError):
        acct.reconcile_holdings()

def test_export_transactions_csv_writes_file(tmp_path):
    acct = Account()
    acct.deposit(Decimal('100.00'))
    acct.buy('AAPL', 1)
    fp = tmp_path / "txns.csv"
    acct.export_transactions_csv(str(fp))
    assert fp.exists()
    with open(fp, newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    # header + number of transactions
    assert rows[0] == ['id', 'timestamp', 'type', 'amount', 'symbol', 'quantity', 'price', 'cash_balance_after', 'note']
    assert len(rows) == 1 + len(acct.list_transactions())