"""
accounts.py

A simple account management system for a trading simulation platform.

This module implements:
- Exceptions for account errors
- get_share_price test resolver
- Transaction and Position dataclasses
- Account class with deposit/withdraw/buy/sell, holdings, PnL, transactions, serialization

"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Literal, Callable, Dict, Any, List
import uuid
import threading
import copy
import json

# Exceptions
class AccountError(Exception):
    """Base custom exception for account module."""

class InvalidAmountError(AccountError):
    pass

class InsufficientFundsError(AccountError):
    pass

class InsufficientSharesError(AccountError):
    pass

class UnknownSymbolError(AccountError):
    pass

class TransactionError(AccountError):
    pass

# Module-level helper
def get_share_price(symbol: str) -> float:
    """Return fixed price for test symbols AAPL, TSLA, GOOGL; raise UnknownSymbolError otherwise.

    Accepts case-insensitive symbols.
    """
    if not symbol or not isinstance(symbol, str):
        raise UnknownSymbolError(f"Unknown symbol: {symbol}")
    prices = {
        'AAPL': 150.0,
        'TSLA': 700.0,
        'GOOGL': 2800.0,
    }
    sym = symbol.upper()
    try:
        return prices[sym]
    except KeyError:
        raise UnknownSymbolError(f"Unknown symbol: {symbol}")

# Dataclasses
@dataclass(frozen=True)
class Transaction:
    tx_id: str
    timestamp: datetime
    type: Literal['deposit', 'withdraw', 'buy', 'sell']
    symbol: Optional[str]
    quantity: Optional[float]
    price: Optional[float]
    total: float
    balance_after: float
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'tx_id': self.tx_id,
            'timestamp': self.timestamp.isoformat(),
            'type': self.type,
            'symbol': self.symbol,
            'quantity': self.quantity,
            'price': self.price,
            'total': self.total,
            'balance_after': self.balance_after,
            'note': self.note,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        ts = data.get('timestamp')
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return cls(
            tx_id=data['tx_id'],
            timestamp=ts,
            type=data['type'],
            symbol=data.get('symbol'),
            quantity=data.get('quantity'),
            price=data.get('price'),
            total=data['total'],
            balance_after=data['balance_after'],
            note=data.get('note'),
        )

@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float
    realized_pnl: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'avg_cost': self.avg_cost,
            'realized_pnl': self.realized_pnl,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        return cls(
            symbol=data['symbol'],
            quantity=data.get('quantity', 0.0),
            avg_cost=data.get('avg_cost', 0.0),
            realized_pnl=data.get('realized_pnl', 0.0),
        )

# Helper for rounding monetary amounts (cents precision)
def _round_money(x: float) -> float:
    try:
        return round(float(x) + 0.0, 2)
    except Exception:
        return float(x)

class Account:
    """Represents a user's simulated trading account.

    Public methods include deposit, withdraw, buy, sell, and reporting utilities.
    """

    def __init__(self, user_id: str, initial_deposit: float = 0.0, currency: str = 'USD') -> None:
        if not user_id or not isinstance(user_id, str):
            raise ValueError("user_id must be a non-empty string")
        self._user_id = user_id
        self._currency = currency
        self._cash = 0.0
        self._initial_deposit = 0.0
        self._positions: Dict[str, Position] = {}
        self._transactions: List[Transaction] = []
        self._realized_pnl = 0.0
        self._lock = threading.Lock()

        if initial_deposit:
            if initial_deposit <= 0:
                raise InvalidAmountError("Initial deposit must be > 0 if provided")
            self._cash = _round_money(initial_deposit)
            self._initial_deposit = _round_money(initial_deposit)
            tx = Transaction(
                tx_id=uuid.uuid4().hex,
                timestamp=datetime.utcnow(),
                type='deposit',
                symbol=None,
                quantity=None,
                price=None,
                total=_round_money(initial_deposit),
                balance_after=self._cash,
                note='initial_deposit'
            )
            self._transactions.append(tx)

    # Internal helpers
    def _record_transaction(self, tx: Transaction) -> None:
        # Ensure consistency: set balance_after to current cash if mismatch
        if _round_money(tx.balance_after) != _round_money(self._cash):
            # Create a corrected transaction to append
            corrected = Transaction(
                tx_id=tx.tx_id,
                timestamp=tx.timestamp,
                type=tx.type,
                symbol=tx.symbol,
                quantity=tx.quantity,
                price=tx.price,
                total=tx.total,
                balance_after=self._cash,
                note=tx.note,
            )
            self._transactions.append(corrected)
        else:
            self._transactions.append(tx)

    def _get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol.upper())

    # Public API
    def deposit(self, amount: float, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        if amount is None or amount <= 0:
            raise InvalidAmountError("Deposit amount must be > 0")
        with self._lock:
            amt = _round_money(amount)
            self._cash = _round_money(self._cash + amt)
            if self._initial_deposit == 0.0:
                self._initial_deposit = amt
            tx = Transaction(
                tx_id=uuid.uuid4().hex,
                timestamp=timestamp or datetime.utcnow(),
                type='deposit',
                symbol=None,
                quantity=None,
                price=None,
                total=amt,
                balance_after=self._cash,
                note=note,
            )
            self._record_transaction(tx)
            return tx

    def withdraw(self, amount: float, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        if amount is None or amount <= 0:
            raise InvalidAmountError("Withdraw amount must be > 0")
        with self._lock:
            amt = _round_money(amount)
            if amt > self._cash + 1e-9:
                raise InsufficientFundsError(f"Insufficient funds: attempting to withdraw {amt} with cash {self._cash}")
            self._cash = _round_money(self._cash - amt)
            tx = Transaction(
                tx_id=uuid.uuid4().hex,
                timestamp=timestamp or datetime.utcnow(),
                type='withdraw',
                symbol=None,
                quantity=None,
                price=None,
                total=_round_money(-amt),
                balance_after=self._cash,
                note=note,
            )
            self._record_transaction(tx)
            return tx

    def buy(self, symbol: str, quantity: float, price: Optional[float] = None,
            timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        if not symbol or not isinstance(symbol, str):
            raise TransactionError("Symbol must be a non-empty string for buy")
        if quantity is None or quantity <= 0:
            raise InvalidAmountError("Buy quantity must be > 0")
        sym = symbol.upper()
        with self._lock:
            resolved_price = price if price is not None else get_share_price(sym)
            if resolved_price is None:
                raise UnknownSymbolError(f"Unknown symbol: {symbol}")
            cost = _round_money(resolved_price * float(quantity))
            if cost > self._cash + 1e-9:
                raise InsufficientFundsError(f"Insufficient cash to buy {quantity} {sym} at {resolved_price} (cost {cost}), cash {self._cash}")
            # Deduct cash
            self._cash = _round_money(self._cash - cost)
            pos = self._positions.get(sym)
            if pos is None:
                self._positions[sym] = Position(symbol=sym, quantity=float(quantity), avg_cost=_round_money(resolved_price), realized_pnl=0.0)
            else:
                old_qty = pos.quantity
                old_avg = pos.avg_cost
                new_qty = old_qty + float(quantity)
                new_avg = 0.0
                if new_qty > 0:
                    new_avg = _round_money((old_avg * old_qty + resolved_price * float(quantity)) / new_qty)
                pos.quantity = new_qty
                pos.avg_cost = new_avg
            tx = Transaction(
                tx_id=uuid.uuid4().hex,
                timestamp=timestamp or datetime.utcnow(),
                type='buy',
                symbol=sym,
                quantity=float(quantity),
                price=_round_money(resolved_price),
                total=_round_money(-cost),
                balance_after=self._cash,
                note=note,
            )
            self._record_transaction(tx)
            return tx

    def sell(self, symbol: str, quantity: float, price: Optional[float] = None,
             timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        if not symbol or not isinstance(symbol, str):
            raise TransactionError("Symbol must be a non-empty string for sell")
        if quantity is None or quantity <= 0:
            raise InvalidAmountError("Sell quantity must be > 0")
        sym = symbol.upper()
        with self._lock:
            pos = self._positions.get(sym)
            if pos is None or pos.quantity + 1e-9 < float(quantity):
                raise InsufficientSharesError(f"Insufficient shares to sell {quantity} {sym}")
            resolved_price = price if price is not None else get_share_price(sym)
            proceeds = _round_money(resolved_price * float(quantity))
            # Update cash
            self._cash = _round_money(self._cash + proceeds)
            # Compute realized pnl
            realized = _round_money((resolved_price - pos.avg_cost) * float(quantity))
            pos.realized_pnl = _round_money(pos.realized_pnl + realized)
            pos.quantity = _round_money(pos.quantity - float(quantity))
            if pos.quantity <= 0:
                # remove position entirely
                del self._positions[sym]
            # Update account realized pnl
            self._realized_pnl = _round_money(self._realized_pnl + realized)
            tx = Transaction(
                tx_id=uuid.uuid4().hex,
                timestamp=timestamp or datetime.utcnow(),
                type='sell',
                symbol=sym,
                quantity=float(quantity),
                price=_round_money(resolved_price),
                total=_round_money(proceeds),
                balance_after=self._cash,
                note=note,
            )
            self._record_transaction(tx)
            return tx

    def get_cash_balance(self) -> float:
        return _round_money(self._cash)

    def get_holdings(self) -> Dict[str, Position]:
        # Return a deep copy to prevent external mutation
        return {k: copy.deepcopy(v) for k, v in self._positions.items()}

    def get_portfolio_value(self, price_resolver: Optional[Callable[[str], float]] = None) -> float:
        resolver = price_resolver or get_share_price
        total = self._cash
        for sym, pos in self._positions.items():
            if pos.quantity <= 0:
                continue
            price = resolver(sym)
            total += price * pos.quantity
        return _round_money(total)

    def total_deposits(self) -> float:
        deposits = sum(tx.total for tx in self._transactions if tx.type == 'deposit')
        return _round_money(deposits)

    def total_withdrawals(self) -> float:
        withdrawals = sum(-tx.total for tx in self._transactions if tx.type == 'withdraw')
        return _round_money(withdrawals)

    def get_profit_loss(self, reference: Literal['initial', 'net_invested'] = 'initial',
                        price_resolver: Optional[Callable[[str], float]] = None) -> float:
        current_total = self.get_portfolio_value(price_resolver)
        if reference == 'initial':
            base = self._initial_deposit
        elif reference == 'net_invested':
            base = self.total_deposits() - self.total_withdrawals()
        else:
            raise ValueError("reference must be 'initial' or 'net_invested'")
        return _round_money(current_total - base)

    def list_transactions(self, start: Optional[datetime] = None, end: Optional[datetime] = None,
                          tx_type: Optional[Literal['deposit', 'withdraw', 'buy', 'sell']] = None,
                          symbol: Optional[str] = None) -> List[Transaction]:
        res: List[Transaction] = []
        sym_upper = symbol.upper() if symbol else None
        for tx in self._transactions:
            if start and tx.timestamp < start:
                continue
            if end and tx.timestamp > end:
                continue
            if tx_type and tx.type != tx_type:
                continue
            if sym_upper and (not tx.symbol or tx.symbol.upper() != sym_upper):
                continue
            res.append(copy.deepcopy(tx))
        return res

    def get_realized_unrealized_pnl_breakdown(self, price_resolver: Optional[Callable[[str], float]] = None) -> Dict[str, float]:
        resolver = price_resolver or get_share_price
        realized = 0.0
        unrealized = 0.0
        for sym, pos in self._positions.items():
            realized += pos.realized_pnl
            if pos.quantity > 0:
                price = resolver(sym)
                unrealized += (price - pos.avg_cost) * pos.quantity
        return {
            'realized_pnl': _round_money(realized),
            'unrealized_pnl': _round_money(unrealized),
            'total_pnl': _round_money(realized + unrealized),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'user_id': self._user_id,
            'currency': self._currency,
            'cash': self._cash,
            'initial_deposit': self._initial_deposit,
            'positions': {k: v.to_dict() for k, v in self._positions.items()},
            'transactions': [tx.to_dict() for tx in self._transactions],
            'realized_pnl': self._realized_pnl,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Account':
        acct = cls(user_id=data.get('user_id', 'unknown'), initial_deposit=0.0, currency=data.get('currency', 'USD'))
        acct._cash = _round_money(data.get('cash', 0.0))
        acct._initial_deposit = _round_money(data.get('initial_deposit', 0.0))
        acct._realized_pnl = _round_money(data.get('realized_pnl', 0.0))
        acct._positions = {k: Position.from_dict(v) for k, v in data.get('positions', {}).items()}
        acct._transactions = [Transaction.from_dict(tx) for tx in data.get('transactions', [])]
        return acct

    def _reset(self) -> None:
        """Reset account to empty state. For testing only."""
        with self._lock:
            self._cash = 0.0
            self._initial_deposit = 0.0
            self._positions.clear()
            self._transactions.clear()
            self._realized_pnl = 0.0

# If executed as script, demonstrate a simple scenario and run basic assertions
if __name__ == '__main__':
    # Simple smoke tests
    acct = Account('alice', initial_deposit=10000.0)
    print('Initial cash:', acct.get_cash_balance())

    tx1 = acct.buy('AAPL', 10)
    print('After buy 10 AAPL cash:', acct.get_cash_balance())
    tx2 = acct.sell('AAPL', 2)
    print('After sell 2 AAPL cash:', acct.get_cash_balance())
    pv = acct.get_portfolio_value()
    print('Portfolio value:', pv)
    pnl = acct.get_profit_loss('initial')
    print('Profit/Loss vs initial:', pnl)

    # List transactions
    for tx in acct.list_transactions():
        print(tx.to_dict())

    # Attempt invalid operations
    try:
        acct.withdraw(20000)
    except InsufficientFundsError as e:
        print('Expected error:', e)

    try:
        acct.sell('AAPL', 1000)
    except InsufficientSharesError as e:
        print('Expected error:', e)

    # Test serialization
    data = acct.to_dict()
    acct2 = Account.from_dict(data)
    print('Deserialized cash:', acct2.get_cash_balance())
