# accounts.py — Design for Account management module (detailed)

This document describes the full design for the accounts.py module. It is intended for the backend developer implementing a single-module self-contained account management system for a trading simulation platform.

High-level summary:
- Module name: accounts.py
- Main class: Account
- Purpose: manage account cash, trades (buy/sell), deposits/withdrawals, compute portfolio value and profit/loss, produce transaction history and holdings at arbitrary points in time.
- Money values use Decimal to avoid floating point errors.
- Transactions are timestamped and stored in a ledger; holdings and cash can be calculated at any timestamp by replaying ledger entries.
- A pluggable price provider interface is provided. A default test implementation get_share_price(symbol, timestamp=None) returns fixed prices for AAPL, TSLA, GOOGL (ignoring timestamp). For historical valuation, callers may supply a price provider that accepts (symbol, timestamp) and returns a Decimal.

---

## Module-level overview

- Module: accounts.py
- Dependencies expected in implementation:
  - datetime, uuid, typing (Dict, List, Optional, Callable), dataclasses, decimal (Decimal), threading
- Use Decimal for currency and price. Quantities are integers (shares).

---

## Public types, functions, and classes (outline)

(Each item below shows the function/method signature and detailed description of behavior, validations, return values, and exceptions.)

### Imports (expected in module)
- from dataclasses import dataclass, field
- from datetime import datetime
- from decimal import Decimal, ROUND_HALF_UP, getcontext
- from typing import Callable, Dict, List, Optional, Tuple
- import uuid
- import threading

Set Decimal context precision as needed (e.g., getcontext().prec = 28).

---

### Exceptions

Define custom exceptions for clear error handling.

- class AccountError(Exception)
  - Base class for account-specific errors.

- class InsufficientFundsError(AccountError)
  - Raised when a withdraw or buy would cause negative cash balance.

- class InsufficientSharesError(AccountError)
  - Raised when a sell attempts to sell more shares than held as of the operation timestamp.

- class InvalidTransactionError(AccountError)
  - Raised for invalid input amounts (negative amounts, zero quantity in trade, unknown symbol when price provider rejects, etc).

- class PriceLookupError(AccountError)
  - Raised when the price provider cannot supply a price (e.g., unknown symbol or missing historical price).

---

### Data classes

- @dataclass
  class Transaction:
    - id: str  # uuid4 hex string
    - timestamp: datetime
    - type: str  # one of: "deposit", "withdraw", "buy", "sell"
    - amount: Decimal  # positive Decimal for deposit/withdraw (cash) or total cash for buy/sell (positive means cash increased, negative means cash decreased)
    - symbol: Optional[str] = None  # for buy/sell
    - quantity: Optional[int] = None  # for buy/sell
    - price: Optional[Decimal] = None  # price per share for buy/sell (None for deposit/withdraw). When provided, it is the unit price used for the transaction.
    - cash_balance_after: Decimal = Decimal('0')  # resulting cash balance in account after transaction
    - note: Optional[str] = None  # free text, optional

  Notes:
  - amount semantics:
    - deposit: amount > 0
    - withdraw: amount < 0 (or for clarity amount stores the cash delta; we can define deposit as positive amount and withdraw as negative amount, but for clarity the implementation may store both deposit and withdraw with positive amount and type indicates sign. Design docs define amount as cash delta: deposits positive, withdraw negative, buy decreases cash (negative amount), sell increases cash (positive amount). Document whichever consistent style is used.)
  - The Transaction record is immutable after creation (dataclass default frozen False but treated as immutable by convention).
  - id is generated via uuid.uuid4().hex.

---

### Price provider interface

- Type alias (informal):
  - PriceProvider = Callable[[str, Optional[datetime]], Decimal]

- Default function provided in module:
  def get_share_price(symbol: str, timestamp: Optional[datetime] = None) -> Decimal
  - Test/fixture implementation:
    - AAPL -> Decimal('150.00')
    - TSLA -> Decimal('700.00')
    - GOOGL -> Decimal('2800.00')
  - Behavior:
    - If symbol not in the known set, raise PriceLookupError or KeyError (design preference: raise PriceLookupError with explanatory message).
    - Ignoring timestamp in this test implementation, but signature supports timestamp for future/historical price providers.

- Note:
  - Implementations of price provider MUST return a Decimal and raise PriceLookupError if price cannot be determined.

---

### Class: Account

Class signature:
- class Account:
  def __init__(
      self,
      account_id: Optional[str] = None,
      initial_deposit: Decimal = Decimal('0'),
      timestamp: Optional[datetime] = None,
      price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None,
  ) -> None

Description:
- Manage a single user's account.
- Tracks ledger of transactions, holdings by replaying ledger, cash balance, and supports querying over time.
- The Account instance is in-memory. Persistence (save/load) is out of scope but can be added by dumping the transactions list.

Attributes:
- account_id: str  # provided or uuid
- _transactions: List[Transaction]  # ordered by timestamp (insertion order)
- _lock: threading.Lock  # for thread-safety around transaction modifications
- _initial_deposit: Optional[Decimal]  # amount of the first deposit recorded (None if none yet)
- _price_provider: PriceProvider  # function used to look up prices when valuing holdings; defaults to get_share_price
- currency rounding behavior: rounding to 2 decimal places for cash computations (quantize(Decimal('0.01')))

Initial deposit behavior:
- If initial_deposit > 0 at construction, a deposit transaction will be added with given timestamp or now. _initial_deposit is set accordingly. If the first deposit happens later via deposit(), _initial_deposit is set on the first deposit call.

Method list (full signatures & detailed behavior):

1) def deposit(self, amount: Decimal, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction
   - Purpose: add cash to account.
   - Validations:
     - amount must be > 0
   - Behavior:
     - Create Transaction(type='deposit', amount=Decimal(amount), timestamp=timestamp or now, update cash balance).
     - If _initial_deposit is None, set it to this amount (store the initial deposit value).
     - Append transaction to ledger.
   - Returns: Transaction object for deposit.

2) def withdraw(self, amount: Decimal, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction
   - Purpose: remove cash from account.
   - Validations:
     - amount must be > 0
     - Must not cause cash balance after withdrawal to be negative (reject).
   - Behavior:
     - Cash delta stored as negative Decimal(-amount) or store positive amount with type 'withdraw'; design decision: amount in Transaction is cash delta (negative for withdraw). The doc will consistently state cash_delta semantics if chosen.
     - Append transaction and return Transaction.
   - Exceptions:
     - InsufficientFundsError if insufficient cash.

3) def buy(self, symbol: str, quantity: int, price: Optional[Decimal] = None, timestamp: Optional[datetime] = None, price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None, note: Optional[str] = None) -> Transaction
   - Purpose: record purchase of shares.
   - Validations:
     - quantity must be > 0
     - price if provided must be > 0
   - Behavior:
     - Resolve effective price: price or (price_provider or self._price_provider)(symbol, timestamp)
     - Compute total_cost = price * quantity, quantize to cents.
     - Ensure current cash balance at moment (replaying ledger up to timestamp or using last known balance if appending now) >= total_cost. If not, raise InsufficientFundsError.
     - Create Transaction(type='buy', symbol=symbol, quantity=quantity, price=unit_price, amount = -total_cost, timestamp=timestamp or now). Update cash balance and holdings by appending this transaction.
     - Return Transaction.
   - Exceptions:
     - PriceLookupError if price provider fails
     - InsufficientFundsError if not enough cash
     - InvalidTransactionError for bad inputs.

4) def sell(self, symbol: str, quantity: int, price: Optional[Decimal] = None, timestamp: Optional[datetime] = None, price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None, note: Optional[str] = None) -> Transaction
   - Purpose: record sale of shares.
   - Validations:
     - quantity must be > 0
     - Must hold at least 'quantity' shares of symbol as of the sale timestamp (replay ledger up to timestamp).
   - Behavior:
     - Resolve unit price as in buy.
     - total_proceeds = price * quantity (quantize)
     - Reduce holdings by quantity (conceptually by recording transaction).
     - Create Transaction(type='sell', symbol=symbol, quantity=quantity, price=unit_price, amount = +total_proceeds, timestamp=timestamp or now).
     - Append and return Transaction.
   - Exceptions:
     - InsufficientSharesError if inadequate holdings
     - PriceLookupError, InvalidTransactionError as appropriate.

5) def list_transactions(self, start: Optional[datetime] = None, end: Optional[datetime] = None, types: Optional[List[str]] = None) -> List[Transaction]
   - Purpose: return ledger transactions filtered by time range and optionally transaction types (e.g., ['buy','sell','deposit','withdraw']).
   - Behavior:
     - Return new list of Transaction objects in chronological order that match filters.
     - If start is None, from beginning; if end is None, to end.

6) def get_cash_balance(self, timestamp: Optional[datetime] = None) -> Decimal
   - Purpose: compute cash balance at a timestamp by replaying transactions up to that timestamp.
   - Behavior:
     - Sum transaction.amount (cash deltas) for transactions with timestamp <= provided timestamp (or all if None).
     - For initial empty account, balance is 0. Rounding to cents at end: quantize(Decimal('0.01')).
     - Important: deposit adds positive amount, withdraw is negative amount, buy negative amount, sell positive amount.

7) def get_holdings(self, timestamp: Optional[datetime] = None) -> Dict[str, int]
   - Purpose: compute holdings (share counts per symbol) at timestamp by replaying buys/sells up to timestamp.
   - Behavior:
     - Walk transactions (<= timestamp) and build dictionary symbol -> net_quantity.
     - Only return entries for which net_quantity != 0 (optionally include zeros if requested).
     - Validate that no negative holdings result (this should not happen in normal operation because sells are validated upfront).

8) def get_portfolio_value(self, timestamp: Optional[datetime] = None, price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None) -> Decimal
   - Purpose: compute total account equity at timestamp: cash balance + market value of holdings using price_provider (or default).
   - Behavior:
     - For each holding symbol and quantity (from get_holdings(timestamp)), get price via effective price_provider(symbol, timestamp) and compute symbol_value = price * quantity.
     - Sum symbol_value values + cash_balance at timestamp.
     - Quantize to cents.
   - Exceptions:
     - PriceLookupError if any symbol price lookup fails.

9) def get_profit_loss(self, timestamp: Optional[datetime] = None, basis: str = 'initial', price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None) -> Decimal
   - Purpose: calculate profit or loss at timestamp.
   - Parameters:
     - basis: 'initial' or 'net'
       - 'initial' uses the initial deposit recorded on the account (first deposit) as the cash capital base.
       - 'net' uses net_deposits = sum(deposits) - sum(withdrawals) up to the timestamp (i.e., your net cash put into account).
   - Behavior:
     - Compute equity = get_portfolio_value(timestamp, price_provider)
     - If basis == 'initial':
       - If _initial_deposit is None: raise InvalidTransactionError (no initial deposit).
       - profit_loss = equity - _initial_deposit
     - If basis == 'net':
       - Compute net_deposited = sum of deposit amounts - sum of withdrawal absolute amounts up to timestamp (i.e., cash put in by user).
       - profit_loss = equity - net_deposited
     - Return Decimal quantized to cents (positive => profit, negative => loss).
   - Note:
     - This definition of profit/loss includes realized and unrealized gains; realized gains will be reflected in cash and holdings value.

10) def get_account_summary(self, timestamp: Optional[datetime] = None, price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None) -> Dict[str, Any]
    - Purpose: convenience method returning a small summary:
      - cash_balance, holdings (symbol -> quantity), holdings_value, total_equity, profit_loss_initial, profit_loss_net
    - Behavior:
      - Use other methods to compute and return a dict.

11) def _append_transaction(self, txn: Transaction) -> None
    - Internal helper: ensures transactions are inserted in chronological order (or appended if timestamp >= last timestamp) and updates any cached state.
    - Thread-safety: acquire _lock before modifying _transactions.
    - This helper sets txn.cash_balance_after consistently by calling get_cash_balance up to txn.timestamp including this txn. To prevent re-computation cycles, the implementation will compute resulting cash balance deterministically.

12) def get_transaction_by_id(self, txn_id: str) -> Optional[Transaction]
    - Return transaction with id or None.

13) def to_dict(self) -> Dict
    - Return serializable snapshot: account_id, transactions (serializable), initial_deposit. (Useful for persistence/testing.)

14) def load_from_dict(cls, data: Dict) -> Account
    - Classmethod to reconstruct an Account from to_dict output (optional, recommended).

---

## Algorithms & implementation details

- Timestamps:
  - All transactions MUST include timezone-aware datetimes or use naive UTC datetimes consistently. For simplicity, we recommend using datetime.utcnow() with naive datetimes and documenting that all timestamps are UTC naive. Alternatively, use timezone-aware datetimes; be consistent.

- Transaction ordering and historical queries:
  - Ledger is a flat list of transactions. To compute historical balances/holdings:
    - Iterate through ledger transactions whose timestamp <= target timestamp in ascending order and accumulate cash delta and holdings changes.
    - Because clients may insert transactions with older timestamps, either:
      - Disallow inserting transactions with timestamps earlier than the latest transaction (simpler), or
      - Allow them but document that ledger will be re-sorted by timestamp; all cash_balance_after fields will be recomputed for affected transactions. The design here recommends allowing older timestamps but then _append_transaction must insert transaction into sorted order and recompute following cash_balance_after fields. This makes the system more flexible for backdated entries but more complex.
    - For the MVP, implement simple append-only semantics: if transaction timestamp < last transaction timestamp, raise InvalidTransactionError unless the implementation chooses to support out-of-order inserts. Document both choices; the developer may implement whichever is preferred.

- Quantization and rounding:
  - Use Decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) after each cash computation to ensure cents precision.
  - Price * quantity: price * Decimal(quantity) then quantize to cents.

- Cash delta sign convention (clarify for consistent implementation):
  - Use transaction.amount as the cash delta applied to balance:
    - deposit: +amount
    - withdraw: -amount
    - buy: - (price * quantity)
    - sell: + (price * quantity)
  - cash_balance_after = previous_balance + transaction.amount

- Prevent invalid operations:
  - Withdraw and buy require available cash >= required amount. Available cash computed by summing transactions up to timestamp (excluding the new transaction).
  - Sell requires holdings >= quantity at the moment.

- Concurrency:
  - All mutation methods (deposit, withdraw, buy, sell, _append_transaction) must acquire _lock to prevent race conditions. Read methods may also acquire the lock briefly when reading transactions list to ensure consistency.

- Historical prices:
  - Default price provider get_share_price ignores timestamp; if callers want historical valuations they must pass a price_provider that supports timestamp lookups.
  - get_portfolio_value and get_profit_loss accept optional price_provider param to support historical valuations when available.

---

## Example method signatures (Python-style pseudo-signatures)

Below are explicit signatures as they would appear in accounts.py. The docstrings should be implemented to match the descriptions above.

def get_share_price(symbol: str, timestamp: Optional[datetime] = None) -> Decimal
    """Default test price provider. Returns Decimal prices for AAPL, TSLA, GOOGL.
       Raises PriceLookupError for unknown symbols.
    """

class Account:
    def __init__(
        self,
        account_id: Optional[str] = None,
        initial_deposit: Decimal = Decimal('0'),
        timestamp: Optional[datetime] = None,
        price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None,
    ) -> None:
        """Create account; optionally create an initial deposit transaction if initial_deposit > 0."""

    def deposit(self, amount: Decimal, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        """Deposit cash into account. Raises InvalidTransactionError for invalid amount."""

    def withdraw(self, amount: Decimal, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction:
        """Withdraw cash. Raises InsufficientFundsError if not enough cash."""

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: Optional[Decimal] = None,
        timestamp: Optional[datetime] = None,
        price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None,
        note: Optional[str] = None
    ) -> Transaction:
        """Buy shares. Validates funds and records transaction. Raises InsufficientFundsError or PriceLookupError."""

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: Optional[Decimal] = None,
        timestamp: Optional[datetime] = None,
        price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None,
        note: Optional[str] = None
    ) -> Transaction:
        """Sell shares. Validates holdings and records transaction. Raises InsufficientSharesError or PriceLookupError."""

    def list_transactions(self, start: Optional[datetime] = None, end: Optional[datetime] = None, types: Optional[List[str]] = None) -> List[Transaction]:
        """Return chronologically ordered transactions filtered by range/types."""

    def get_transaction_by_id(self, txn_id: str) -> Optional[Transaction]:
        """Return transaction with the given id, or None."""

    def get_cash_balance(self, timestamp: Optional[datetime] = None) -> Decimal:
        """Compute cash balance at timestamp by replaying transactions."""

    def get_holdings(self, timestamp: Optional[datetime] = None) -> Dict[str, int]:
        """Compute holdings at timestamp by replaying buy/sell transactions."""

    def get_portfolio_value(self, timestamp: Optional[datetime] = None, price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None) -> Decimal:
        """Return total equity = cash + market value of holdings, using price_provider."""

    def get_profit_loss(self, timestamp: Optional[datetime] = None, basis: str = 'initial', price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None) -> Decimal:
        """Compute P/L relative to basis ('initial' or 'net')."""

    def get_account_summary(self, timestamp: Optional[datetime] = None, price_provider: Optional[Callable[[str, Optional[datetime]], Decimal]] = None) -> Dict[str, object]:
        """Convenience summary with keys: cash_balance, holdings, holdings_value, total_equity, profit_loss_initial, profit_loss_net."""

    def to_dict(self) -> Dict:
        """Return serializable dict describing the account and transactions (for tests/persistence)."""

    @classmethod
    def load_from_dict(cls, data: Dict) -> 'Account':
        """Rebuild an Account from to_dict output."""

---

## Transaction examples and sign semantics

- Example deposit:$100
  - Transaction.type = "deposit"
  - Transaction.amount = Decimal('100.00')  # cash delta +100
  - cash_balance_after = previous + 100

- Example withdraw:$30
  - Transaction.type = "withdraw"
  - Transaction.amount = Decimal('-30.00')  # cash delta -30
  - cash_balance_after = previous - 30

- Example buy 2 shares AAPL @ 150
  - unit price = Decimal('150.00')
  - total_cost = Decimal('300.00')
  - Transaction.type = "buy"
  - Transaction.symbol = 'AAPL'
  - Transaction.quantity = 2
  - Transaction.price = Decimal('150.00')
  - Transaction.amount = Decimal('-300.00')  # cash delta
  - After transaction, cash reduces by 300 and holdings AAPL increases by 2.

- Example sell 1 share TSLA @ 700
  - total_proceeds = Decimal('700.00')
  - Transaction.type = "sell"
  - Transaction.amount = Decimal('700.00')  # cash delta +700

---

## Example usage (for implementer/testing)

(This is descriptive; not runnable code here. The implementer should implement methods accordingly.)

- Create account:
  account = Account(account_id='user123')

- Deposit:
  txn = account.deposit(Decimal('1000.00'))

- Buy:
  txn_buy = account.buy('AAPL', 2)  # buys 2 * 150.00 = 300.00 cost when using default prices

- Sell:
  txn_sell = account.sell('AAPL', 1)

- Withdraw:
  txn_withdraw = account.withdraw(Decimal('100.00'))

- Query values:
  cash = account.get_cash_balance()
  holdings = account.get_holdings()
  value = account.get_portfolio_value()
  pl_initial = account.get_profit_loss(basis='initial')
  transactions = account.list_transactions()

- Historical query:
  t = datetime.utcnow()  # or some earlier timestamp
  holdings_at_t = account.get_holdings(timestamp=t)
  # For valuation at t using special price provider:
  value_at_t = account.get_portfolio_value(timestamp=t, price_provider=my_historical_price_provider)

---

## Edge cases and design decisions (explicit)

- Out-of-order transactions:
  - Simpler design: only allow appending transactions with timestamp >= last transaction timestamp; if caller attempts earlier timestamp, raise InvalidTransactionError. This avoids complex recomputation. Document this choice. Alternatively, support inserting and recomputing subsequent cash_balance_after values; if implemented, ensure _append_transaction recomputes cash balances for transactions with timestamp >= inserted transaction timestamp.

- Fractional shares:
  - Design uses integer quantities. If fractional shares are required later, quantity can be changed to Decimal, but additional validation for partial-share arithmetic must be added.

- Fees and commissions:
  - Not required in current requirements, but Transaction.note or an optional fees field could be added later.

- Multiple deposits:
  - _initial_deposit is the first deposit recorded. get_profit_loss(basis='initial') uses that value. get_profit_loss(basis='net') uses net-deposits. Both methods are available.

- Rounding:
  - Round every cash delta and monetary sum to 2 decimal places.

---

## Default test price provider implementation

Implement get_share_price in the module:

- def get_share_price(symbol: str, timestamp: Optional[datetime] = None) -> Decimal
  - mapping = {'AAPL': Decimal('150.00'), 'TSLA': Decimal('700.00'), 'GOOGL': Decimal('2800.00')}
  - if symbol.upper() in mapping: return mapping[symbol.upper()]
  - else: raise PriceLookupError(f"No test price for symbol {symbol}")

This provides immediate deterministic prices for local/testing.

---

## Additional recommended utilities (optional but recommended)

- reconcile_holdings(self) -> None
  - Run a check over ledger to ensure no point in ledger holdings go negative (invariant), and raise assertion/repair otherwise (useful for sanity checks in tests).

- compute_realized_pl(self) -> Decimal
  - Compute realized P/L from trades (complex; optional). Not required by current scope.

- export_transactions_csv(self, filepath: str)
  - For debug/testing, export ledger to CSV.

---

## Summary of responsibilities for the developer implementing accounts.py

- Use Decimal for money and implement consistent quantization to 2 decimal places.
- Implement Transaction dataclass and custom exceptions.
- Implement Account with the methods and behaviors described above.
- Use threading.Lock to protect concurrent mutation.
- Implement default get_share_price mapping for AAPL, TSLA, GOOGL.
- Ensure buy/withdraw validations to prevent negative cash; sell validation to prevent negative holdings.
- Support historical queries by replaying ledger up to provided timestamp; document whether out-of-order insertion is permitted or not.
- Provide clear docstrings for each method describing parameters, returns, and exceptions.

---

This design provides a complete, implementable blueprint for a single-file accounts.py module containing the Account class, custom exceptions, Transaction dataclass, and default price provider. The developer may now implement the module directly from these specifications and add unit tests that exercise deposits, withdrawals, buys, sells, historical queries, and error conditions.