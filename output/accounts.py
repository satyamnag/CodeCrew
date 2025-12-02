from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Callable, Dict, List, Optional, Any
import uuid
import threading

# Set Decimal precision
getcontext().prec = 28
CENTS = Decimal('0.01')

# Exceptions


class AccountError(Exception):
    """Base class for account-specific errors."""
    pass


class InsufficientFundsError(AccountError):
    """Raised when a withdraw or buy would cause negative cash balance."""
    pass


class InsufficientSharesError(AccountError):
    """Raised when a sell attempts to sell more shares than held as of the operation timestamp."""
    pass


class InvalidTransactionError(AccountError):
    """Raised for invalid input amounts or invalid operations."""
    pass


class PriceLookupError(AccountError):
    """Raised when the price provider cannot supply a price."""
    pass


# Transaction dataclass


@dataclass
class Transaction:
    id: str
    timestamp: datetime
    type: str  # 'deposit', 'withdraw', 'buy', 'sell'
    amount: Decimal  # cash delta: deposit +, withdraw -, buy -, sell +
    symbol: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[Decimal] = None  # unit price
    cash_balance_after: Decimal = field(default_factory=lambda: Decimal('0'))
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'type': self.type,
            'amount': str(self.amount),
            'symbol': self.symbol,
            'quantity': self.quantity,
            'price': (str(self.price) if self.price is not None else None),
            'cash_balance_after': str(self.cash_balance_after),
            'note': self.note,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        ts = datetime.fromisoformat(data['timestamp'])
        amount = Decimal(data['amount'])
        price = Decimal(data['price']) if data.get('price') is not None else None
        cash_after = Decimal(data.get('cash_balance_after', '0'))
        return cls(
            id=data['id'],
            timestamp=ts,
            type=data['type'],
            amount=amount,
            symbol=data.get('symbol'),
            quantity=data.get('quantity'),
            price=price,
            cash_balance_after=cash_after,
            note=data.get('note'),
        )


# Price provider type alias
PriceProvider = Callable[[str, Optional[datetime]], Decimal]


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def get_share_price(symbol: str, timestamp: Optional[datetime] = None) -> Decimal:
    """
    Default test price provider. Returns fixed Decimal prices for AAPL, TSLA, GOOGL.
    Raises PriceLookupError for unknown symbols. Ignores timestamp.
    """
    mapping = {
        'AAPL': Decimal('150.00'),
        'TSLA': Decimal('700.00'),
        'GOOGL': Decimal('2800.00'),
    }
    sym = symbol.upper()
    if sym in mapping:
        return mapping[sym]
    raise PriceLookupError(f"No test price for symbol {symbol}")


class Account:
    """
    Simple account management for trading simulation.
    Append-only ledger semantics: transactions must have timestamp >= last transaction timestamp.
    All timestamps are naive UTC datetimes (datetime.utcnow()).
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        initial_deposit: Decimal = Decimal('0'),
        timestamp: Optional[datetime] = None,
        price_provider: Optional[PriceProvider] = None,
    ) -> None:
        self.account_id = account_id or uuid.uuid4().hex
        self._transactions: List[Transaction] = []
        self._lock = threading.Lock()
        self._initial_deposit: Optional[Decimal] = None
        self._price_provider: PriceProvider = price_provider or get_share_price

        if initial_deposit is not None and Decimal(initial_deposit) > 0:
            ts = timestamp or datetime.utcnow()
            # ensure Decimal quantization
            amt = _quantize_money(Decimal(initial_deposit))
            with self._lock:
                txn = Transaction(
                    id=uuid.uuid4().hex,
                    timestamp=ts,
                    type='deposit',
                    amount=amt,
                    symbol=None,
                    quantity=None,
                    price=None,
                    cash_balance_after=Decimal('0'),  # will be set in _append_transaction
                    note='initial_deposit',
                )
                self._append_transaction(txn)
                self._initial_deposit = amt

    # Internal helper to get last transaction timestamp
    def _last_transaction_timestamp(self) -> Optional[datetime]:
        if not self._transactions:
            return None
        return self._transactions[-1].timestamp

    def _append_transaction(self, txn: Transaction) -> None:
        """
        Append-only semantics: only allow txn.timestamp >= last txn timestamp.
        Acquire lock and append, compute cash_balance_after for this transaction.
        """
        with self._lock:
            last_ts = self._last_transaction_timestamp()
            if last_ts is not None and txn.timestamp < last_ts:
                raise InvalidTransactionError(
                    "Out-of-order transaction timestamps not allowed in this implementation."
                )
            # compute prior balance
            prior_balance = Decimal('0')
            if self._transactions:
                prior_balance = self._transactions[-1].cash_balance_after
            new_balance = _quantize_money(prior_balance + txn.amount)
            txn.cash_balance_after = new_balance
            self._transactions.append(txn)

    def deposit(self, amount: Decimal, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        """
        Deposit cash into account. amount must be > 0.
        Sets _initial_deposit if this is the first deposit ever.
        Returns the created Transaction.
        """
        if amount is None:
            raise InvalidTransactionError("Amount is required for deposit.")
        amt = Decimal(amount)
        if amt <= 0:
            raise InvalidTransactionError("Deposit amount must be greater than 0.")
        amt = _quantize_money(amt)
        ts = timestamp or datetime.utcnow()
        txn = Transaction(
            id=uuid.uuid4().hex,
            timestamp=ts,
            type='deposit',
            amount=amt,
            note=note,
        )
        self._append_transaction(txn)
        with self._lock:
            if self._initial_deposit is None:
                self._initial_deposit = amt
        return txn

    def withdraw(self, amount: Decimal, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        """
        Withdraw cash from account. amount must be > 0 and must not cause negative cash balance.
        Returns the created Transaction.
        """
        if amount is None:
            raise InvalidTransactionError("Amount is required for withdrawal.")
        amt = Decimal(amount)
        if amt <= 0:
            raise InvalidTransactionError("Withdraw amount must be greater than 0.")
        amt = _quantize_money(amt)
        ts = timestamp or datetime.utcnow()
        # check funds at timestamp
        available = self.get_cash_balance(timestamp=ts)
        if available < amt:
            raise InsufficientFundsError("Insufficient funds for withdrawal.")
        txn = Transaction(
            id=uuid.uuid4().hex,
            timestamp=ts,
            type='withdraw',
            amount=_quantize_money(-amt),
            note=note,
        )
        self._append_transaction(txn)
        return txn

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: Optional[Decimal] = None,
        timestamp: Optional[datetime] = None,
        price_provider: Optional[PriceProvider] = None,
        note: Optional[str] = None
    ) -> Transaction:
        """
        Buy shares. Validates funds and records transaction.
        Raises InsufficientFundsError or PriceLookupError or InvalidTransactionError.
        """
        if not symbol or quantity is None:
            raise InvalidTransactionError("Symbol and quantity are required for buy.")
        if quantity <= 0:
            raise InvalidTransactionError("Buy quantity must be > 0.")
        ts = timestamp or datetime.utcnow()
        provider = price_provider or self._price_provider
        unit_price = None
        if price is not None:
            unit_price = Decimal(price)
            if unit_price <= 0:
                raise InvalidTransactionError("Price must be > 0.")
        else:
            try:
                unit_price = provider(symbol, ts)
            except Exception as e:
                raise PriceLookupError(str(e))
        if not isinstance(unit_price, Decimal):
            unit_price = Decimal(unit_price)
        unit_price = _quantize_money(unit_price)
        total_cost = _quantize_money(unit_price * Decimal(quantity))
        # check available cash at timestamp
        available = self.get_cash_balance(timestamp=ts)
        if available < total_cost:
            raise InsufficientFundsError("Insufficient funds to execute buy order.")
        txn = Transaction(
            id=uuid.uuid4().hex,
            timestamp=ts,
            type='buy',
            amount=_quantize_money(-total_cost),
            symbol=symbol.upper(),
            quantity=quantity,
            price=unit_price,
            note=note,
        )
        self._append_transaction(txn)
        return txn

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: Optional[Decimal] = None,
        timestamp: Optional[datetime] = None,
        price_provider: Optional[PriceProvider] = None,
        note: Optional[str] = None
    ) -> Transaction:
        """
        Sell shares. Validates holdings and records transaction.
        Raises InsufficientSharesError or PriceLookupError or InvalidTransactionError.
        """
        if not symbol or quantity is None:
            raise InvalidTransactionError("Symbol and quantity are required for sell.")
        if quantity <= 0:
            raise InvalidTransactionError("Sell quantity must be > 0.")
        ts = timestamp or datetime.utcnow()
        symbol_up = symbol.upper()
        holdings = self.get_holdings(timestamp=ts)
        held_qty = holdings.get(symbol_up, 0)
        if held_qty < quantity:
            raise InsufficientSharesError(f"Attempt to sell {quantity} shares but only {held_qty} held as of timestamp.")
        provider = price_provider or self._price_provider
        unit_price = None
        if price is not None:
            unit_price = Decimal(price)
            if unit_price <= 0:
                raise InvalidTransactionError("Price must be > 0.")
        else:
            try:
                unit_price = provider(symbol_up, ts)
            except Exception as e:
                raise PriceLookupError(str(e))
        if not isinstance(unit_price, Decimal):
            unit_price = Decimal(unit_price)
        unit_price = _quantize_money(unit_price)
        total_proceeds = _quantize_money(unit_price * Decimal(quantity))
        txn = Transaction(
            id=uuid.uuid4().hex,
            timestamp=ts,
            type='sell',
            amount=_quantize_money(total_proceeds),
            symbol=symbol_up,
            quantity=quantity,
            price=unit_price,
            note=note,
        )
        self._append_transaction(txn)
        return txn

    def list_transactions(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        types: Optional[List[str]] = None
    ) -> List[Transaction]:
        """
        Return chronologically ordered transactions filtered by optional start/end timestamps and types.
        """
        with self._lock:
            result = []
            for txn in self._transactions:
                if start is not None and txn.timestamp < start:
                    continue
                if end is not None and txn.timestamp > end:
                    continue
                if types is not None and txn.type not in types:
                    continue
                result.append(txn)
            return list(result)

    def get_transaction_by_id(self, txn_id: str) -> Optional[Transaction]:
        with self._lock:
            for txn in self._transactions:
                if txn.id == txn_id:
                    return txn
        return None

    def get_cash_balance(self, timestamp: Optional[datetime] = None) -> Decimal:
        """
        Compute cash balance at timestamp by replaying transactions up to and including timestamp.
        If timestamp is None, returns latest balance.
        """
        with self._lock:
            if not self._transactions:
                return _quantize_money(Decimal('0'))
            if timestamp is None:
                return _quantize_money(self._transactions[-1].cash_balance_after)
            balance = Decimal('0')
            for txn in self._transactions:
                if txn.timestamp <= timestamp:
                    balance += txn.amount
            return _quantize_money(balance)

    def get_holdings(self, timestamp: Optional[datetime] = None) -> Dict[str, int]:
        """
        Compute holdings (symbol -> net quantity) at timestamp by replaying buy/sell transactions.
        """
        with self._lock:
            holdings: Dict[str, int] = {}
            for txn in self._transactions:
                if timestamp is not None and txn.timestamp > timestamp:
                    break
                if txn.type == 'buy' and txn.symbol and txn.quantity:
                    sym = txn.symbol.upper()
                    holdings[sym] = holdings.get(sym, 0) + int(txn.quantity)
                elif txn.type == 'sell' and txn.symbol and txn.quantity:
                    sym = txn.symbol.upper()
                    holdings[sym] = holdings.get(sym, 0) - int(txn.quantity)
            # remove zero entries
            holdings = {s: q for s, q in holdings.items() if q != 0}
            return holdings

    def get_portfolio_value(
        self,
        timestamp: Optional[datetime] = None,
        price_provider: Optional[PriceProvider] = None
    ) -> Decimal:
        """
        Compute total equity = cash balance + market value of holdings at timestamp using price_provider.
        """
        provider = price_provider or self._price_provider
        cash = self.get_cash_balance(timestamp=timestamp)
        holdings = self.get_holdings(timestamp=timestamp)
        total_holdings_value = Decimal('0')
        for symbol, qty in holdings.items():
            try:
                price = provider(symbol, timestamp)
            except Exception as e:
                raise PriceLookupError(str(e))
            if not isinstance(price, Decimal):
                price = Decimal(price)
            price = _quantize_money(price)
            symbol_value = _quantize_money(price * Decimal(qty))
            total_holdings_value += symbol_value
        total = _quantize_money(cash + total_holdings_value)
        return total

    def get_profit_loss(
        self,
        timestamp: Optional[datetime] = None,
        basis: str = 'initial',
        price_provider: Optional[PriceProvider] = None
    ) -> Decimal:
        """
        Compute profit or loss at timestamp.
        basis: 'initial' uses the first deposit, 'net' uses net deposits (deposits - withdrawals) up to timestamp.
        Returns Decimal (positive => profit, negative => loss).
        """
        equity = self.get_portfolio_value(timestamp=timestamp, price_provider=price_provider)
        if basis == 'initial':
            if self._initial_deposit is None:
                raise InvalidTransactionError("No initial deposit recorded for 'initial' basis P/L calculation.")
            pl = equity - self._initial_deposit
            return _quantize_money(pl)
        elif basis == 'net':
            # compute net deposits up to timestamp
            net = Decimal('0')
            with self._lock:
                for txn in self._transactions:
                    if timestamp is not None and txn.timestamp > timestamp:
                        break
                    if txn.type == 'deposit' or txn.type == 'withdraw':
                        net += txn.amount
            return _quantize_money(equity - _quantize_money(net))
        else:
            raise InvalidTransactionError("basis must be 'initial' or 'net'")

    def get_account_summary(
        self,
        timestamp: Optional[datetime] = None,
        price_provider: Optional[PriceProvider] = None
    ) -> Dict[str, Any]:
        """
        Convenience summary:
        {
            'cash_balance': Decimal,
            'holdings': {symbol: quantity},
            'holdings_value': Decimal,
            'total_equity': Decimal,
            'profit_loss_initial': Decimal or None,
            'profit_loss_net': Decimal
        }
        """
        provider = price_provider or self._price_provider
        cash = self.get_cash_balance(timestamp=timestamp)
        holdings = self.get_holdings(timestamp=timestamp)
        holdings_value = Decimal('0')
        for symbol, qty in holdings.items():
            price = provider(symbol, timestamp)
            if not isinstance(price, Decimal):
                price = Decimal(price)
            price = _quantize_money(price)
            holdings_value += _quantize_money(price * Decimal(qty))
        total_equity = _quantize_money(cash + holdings_value)
        try:
            pl_initial = None
            if self._initial_deposit is not None:
                pl_initial = self.get_profit_loss(timestamp=timestamp, basis='initial', price_provider=provider)
        except InvalidTransactionError:
            pl_initial = None
        pl_net = self.get_profit_loss(timestamp=timestamp, basis='net', price_provider=provider)
        return {
            'cash_balance': cash,
            'holdings': holdings,
            'holdings_value': _quantize_money(holdings_value),
            'total_equity': total_equity,
            'profit_loss_initial': pl_initial,
            'profit_loss_net': pl_net,
        }

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'account_id': self.account_id,
                'initial_deposit': (str(self._initial_deposit) if self._initial_deposit is not None else None),
                'transactions': [txn.to_dict() for txn in self._transactions],
            }

    @classmethod
    def load_from_dict(cls, data: Dict[str, Any], price_provider: Optional[PriceProvider] = None) -> 'Account':
        """
        Rebuild an Account from a dict produced by to_dict.
        Note: Reconstructed transactions will be appended in the order provided.
        """
        acct = cls(account_id=data.get('account_id'), price_provider=price_provider)
        txns = data.get('transactions', [])
        # Clear any initial deposit created by __init__
        acct._transactions = []
        acct._initial_deposit = Decimal(data['initial_deposit']) if data.get('initial_deposit') is not None else None
        for t in txns:
            txn = Transaction.from_dict(t)
            # Ensure fields quantized
            txn.amount = _quantize_money(txn.amount)
            if txn.price is not None:
                txn.price = _quantize_money(txn.price)
            txn.cash_balance_after = _quantize_money(txn.cash_balance_after)
            acct._append_transaction(txn)
        return acct

    # Optional utility
    def reconcile_holdings(self) -> None:
        """
        Sanity check: ensures no negative holdings at any point in ledger.
        Raises AssertionError if inconsistency detected.
        """
        with self._lock:
            running: Dict[str, int] = {}
            for txn in self._transactions:
                if txn.type == 'buy' and txn.symbol and txn.quantity:
                    running[txn.symbol] = running.get(txn.symbol, 0) + int(txn.quantity)
                elif txn.type == 'sell' and txn.symbol and txn.quantity:
                    running[txn.symbol] = running.get(txn.symbol, 0) - int(txn.quantity)
                    if running[txn.symbol] < 0:
                        raise AssertionError(f"Negative holdings for {txn.symbol} after transaction {txn.id}")

    def export_transactions_csv(self, filepath: str) -> None:
        """
        Export transactions to CSV (basic).
        """
        import csv
        with self._lock:
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'timestamp', 'type', 'amount', 'symbol', 'quantity', 'price', 'cash_balance_after', 'note'])
                for txn in self._transactions:
                    writer.writerow([
                        txn.id,
                        txn.timestamp.isoformat(),
                        txn.type,
                        str(txn.amount),
                        txn.symbol or '',
                        txn.quantity or '',
                        str(txn.price) if txn.price is not None else '',
                        str(txn.cash_balance_after),
                        txn.note or '',
                    ])