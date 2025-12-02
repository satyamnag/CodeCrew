# accounts.py — Design (detailed)

This document defines the complete design for the accounts.py module which implements a simple account management system for a trading simulation platform. The design is expressed as a single self-contained Python module. It describes classes, dataclasses, functions, method signatures, behaviors, return types, side-effects, validations, and exceptions so an engineer can implement and test the module or wire it to a simple UI.

Module responsibilities (summary)
- Create and manage user accounts
- Deposit and withdraw cash (prevent negative cash balance)
- Record buy and sell share transactions (prevent buying more than cash allows, prevent selling more than owned)
- Maintain holdings and average cost per holding
- Compute portfolio total value (cash + market value of holdings)
- Compute profit/loss relative to initial deposit or relative to net invested capital
- List transactions with filtering
- Provide an in-module test get_share_price(symbol) function providing fixed prices for AAPL, TSLA, GOOGL

All code, data containers, and helper types are intended to be contained in accounts.py.

----

Module-level overview (top-level items)

- Exceptions
  - AccountError(Exception)
  - InvalidAmountError(AccountError)
  - InsufficientFundsError(AccountError)
  - InsufficientSharesError(AccountError)
  - UnknownSymbolError(AccountError)
  - TransactionError(AccountError)

- Module-level helper
  - get_share_price(symbol: str) -> float
    - Test implementation that returns fixed prices for AAPL, TSLA, GOOGL
    - Raises UnknownSymbolError for unknown symbols

- Dataclasses / types
  - Transaction (dataclass)
  - Position (dataclass)

- Main class
  - Account

Below are the detailed definitions.

----

1) Exceptions

- class AccountError(Exception)
  - Base custom exception for this module.

- class InvalidAmountError(AccountError)
  - Raised when a negative or zero amount is passed for deposit/withdraw/buy/sell where not allowed.

- class InsufficientFundsError(AccountError)
  - Raised when a withdrawal or buy would leave the cash balance negative or is otherwise unaffordable.

- class InsufficientSharesError(AccountError)
  - Raised when attempting to sell more shares than are currently owned.

- class UnknownSymbolError(AccountError)
  - Raised when get_share_price or buy/sell receive an unknown ticker symbol.

- class TransactionError(AccountError)
  - Raised for general transaction errors (e.g., malformed inputs).

Notes:
- Each exception should include a descriptive message.
- Exceptions are simple, enabling clear handling by callers or UI layers.

----

2) Module helper function

- def get_share_price(symbol: str) -> float
  - Signature: get_share_price(symbol: str) -> float
  - Purpose: Return the current price of a share in USD for the provided symbol.
  - Behavior (test implementation):
    - Accepts case-insensitive symbols; normalizes to upper-case.
    - Fixed prices (example):
      - "AAPL" -> 150.0
      - "TSLA" -> 700.0
      - "GOOGL" -> 2800.0
    - For any other symbol, raise UnknownSymbolError(f"Unknown symbol: {symbol}")
  - Use-case: Called by Account.buy(), Account.sell(), Account.get_portfolio_value() unless explicit price is provided by caller.
  - Note: Implementation is a simple deterministic stub helpful for testing.

----

3) Dataclasses / types

- from dataclasses import dataclass
- from datetime import datetime
- from typing import Optional, Literal

A. Transaction

- @dataclass
  class Transaction:
    - tx_id: str
      - Unique transaction identifier (e.g., uuid4 hex string)
    - timestamp: datetime
      - When the transaction was recorded; default to datetime.utcnow() if none provided.
    - type: Literal['deposit', 'withdraw', 'buy', 'sell']
      - The transaction type.
    - symbol: Optional[str]
      - Ticker symbol for buy/sell; None for deposit/withdraw.
    - quantity: Optional[float]
      - Number of shares (float to allow fractional shares if desired). For deposits/withdraws this is None.
    - price: Optional[float]
      - Per-share price used for the transaction (None for deposit/withdraw).
    - total: float
      - Total cash effect of the transaction:
        - For deposit: positive amount
        - For withdraw: negative amount
        - For buy: negative total (cost)
        - For sell: positive total (proceeds)
    - balance_after: float
      - Cash balance of the account after applying this transaction
    - note: Optional[str]
      - Optional free-text note
  - Purpose: Immutable record of every action that affects state. Persistable and filterable.

B. Position

- @dataclass
  class Position:
    - symbol: str
    - quantity: float
      - Total quantity currently held (>= 0)
    - avg_cost: float
      - Average cost per share for shares currently held (0 if quantity == 0)
    - realized_pnl: float
      - Realized profit/loss for this symbol (from sells)
  - Purpose: Represents the account's current holdings for a single symbol, including realized profit/loss and average cost basis.

Notes on Position behavior:
- avg_cost is updated by buys using weighted-average:
  - new_avg = (old_avg * old_qty + buy_price * buy_qty) / (old_qty + buy_qty)
- When selling:
  - Reduce quantity by sold amount.
  - Compute realized pnl for sold portion: (sell_price - avg_cost) * sold_qty and add to realized_pnl.
  - If quantity goes to 0, avg_cost resets to 0.
- Fractional shares allowed if quantity is float.

----

4) Account class (primary API)

Class: Account

- class Account:
  - Purpose: Represent a user's simulated trading account. Maintain cash balance, holdings, transactions, and compute portfolio value and profit/loss.

- Constructor:

  def __init__(self, user_id: str, initial_deposit: float = 0.0, currency: str = 'USD') -> None

  - Parameters:
    - user_id: str — unique identifier for the account owner
    - initial_deposit: float — optional initial deposit (>= 0). If provided, a deposit transaction is recorded and initial_deposit attribute is set to this value. If zero, initial_deposit remains 0 until the first deposit (see behavior below).
    - currency: str — currency code (default 'USD'). Stored for clarity; prices and values are assumed to be in this currency.
  - Behavior:
    - Initializes internal state:
      - _user_id: str
      - _currency: str
      - _cash: float — current available cash (starts at initial_deposit)
      - _initial_deposit: float — the amount considered the "initial deposit". Implementation options:
        - If initial_deposit > 0, set _initial_deposit = initial_deposit.
        - Else set _initial_deposit = 0. If a deposit occurs later and _initial_deposit == 0, set it to the value of the first deposit (this preserves "initial deposit" semantics).
      - _positions: Dict[str, Position] — mapping symbol -> Position
      - _transactions: List[Transaction] — chronological list (append-only)
      - _realized_pnl: float — total realized pnl across all positions
      - _lock: threading.Lock — optional, for thread-safety (if implementing concurrency)
    - If initial_deposit > 0, record a deposit Transaction accordingly.
  - Returns: None

- Public methods (signatures, behavior, return types, validations, exceptions)

1. deposit

  def deposit(self, amount: float, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction

  - Purpose: Add cash to account. Records a deposit transaction.
  - Behavior:
    - Validate amount > 0 else raise InvalidAmountError.
    - Increase _cash by amount.
    - If _initial_deposit == 0, set _initial_deposit = amount (first-deposit semantics).
    - Create Transaction(type='deposit', total=amount, balance_after=_cash, ...), append to _transactions.
  - Returns: the Transaction added.
  - Exceptions: InvalidAmountError if amount <= 0.

2. withdraw

  def withdraw(self, amount: float, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction

  - Purpose: Withdraw cash from account (reduce _cash).
  - Behavior:
    - Validate amount > 0 else raise InvalidAmountError.
    - If amount > _cash: raise InsufficientFundsError (no overdraft allowed).
    - Decrease _cash by amount.
    - Create Transaction(type='withdraw', total=-amount, balance_after=_cash, ...), append to _transactions.
  - Returns: the Transaction added.
  - Exceptions: InvalidAmountError, InsufficientFundsError.

3. buy

  def buy(self, symbol: str, quantity: float, price: Optional[float] = None, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction

  - Purpose: Purchase quantity shares of symbol at given price (or market via get_share_price if price is None).
  - Parameters:
    - symbol: str
    - quantity: float (> 0)
    - price: Optional[float] — if None, call get_share_price(symbol)
  - Behavior:
    - Validate quantity > 0 else raise InvalidAmountError.
    - Resolve price: if price is None -> price = get_share_price(symbol)
    - Compute total_cost = round(price * quantity, appropriate decimal)
    - If total_cost > _cash: raise InsufficientFundsError
    - Reduce _cash by total_cost
    - Update _positions:
      - If symbol not present, create Position(symbol, quantity, avg_cost=price, realized_pnl=0.0)
      - Else update avg_cost with weighted average formula and increase quantity
    - Create Transaction(type='buy', symbol, quantity, price, total=-total_cost, balance_after=_cash, ...)
    - Append transaction
  - Returns: Transaction
  - Exceptions: InvalidAmountError, UnknownSymbolError (via get_share_price), InsufficientFundsError

4. sell

  def sell(self, symbol: str, quantity: float, price: Optional[float] = None, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction

  - Purpose: Sell quantity shares of symbol at price (or market via get_share_price).
  - Behavior:
    - Validate quantity > 0 else raise InvalidAmountError.
    - Ensure symbol exists in _positions and position.quantity >= quantity else raise InsufficientSharesError.
    - Resolve price: if price is None -> price = get_share_price(symbol)
    - Compute proceeds = round(price * quantity, appropriate decimal)
    - Increase _cash by proceeds
    - Update Position:
      - Compute realized = (price - position.avg_cost) * quantity
      - position.realized_pnl += realized
      - position.quantity -= quantity
      - If position.quantity == 0: set position.avg_cost = 0.0
    - Update account _realized_pnl += realized
    - Create Transaction(type='sell', symbol, quantity, price, total=proceeds, balance_after=_cash)
    - Append transaction
  - Returns: Transaction
  - Exceptions: InvalidAmountError, InsufficientSharesError, UnknownSymbolError

5. get_cash_balance

  def get_cash_balance(self) -> float

  - Purpose: Return the account's available cash.
  - Behavior: Return _cash (float).
  - No side-effects.

6. get_holdings

  def get_holdings(self) -> Dict[str, Position]

  - Purpose: Return a shallow copy of the positions mapping (symbol -> Position), or alternatively a list of Positions.
  - Behavior: Return copy to avoid external mutation.
  - Note: Each Position includes quantity, avg_cost, realized_pnl.

7. get_portfolio_value

  def get_portfolio_value(self, price_resolver: Optional[Callable[[str], float]] = None) -> float

  - Purpose: Compute current total value of the account: cash + sum(quantity * current_price(symbol))
  - Parameters:
    - price_resolver: Optional function to use instead of module get_share_price. Signature Callable[[str], float].
      - If None -> use get_share_price.
  - Behavior:
    - For each position with quantity > 0:
      - Resolve price = price_resolver(symbol) (wrap UnknownSymbolError to indicate missing data or treat as zero if desired — default is to raise UnknownSymbolError)
      - position_value = price * quantity
    - Sum all position_values + _cash and return.
  - Returns: float total_portfolio_value
  - Exceptions: UnknownSymbolError if price is not available for one of the holdings (unless price_resolver handles it).

8. get_profit_loss

  def get_profit_loss(self, reference: Literal['initial', 'net_invested'] = 'initial', price_resolver: Optional[Callable[[str], float]] = None) -> float

  - Purpose: Compute profit or loss for the account at present time.
  - Parameters:
    - reference:
      - 'initial' => profit relative to the initial deposit (the first deposit amount recorded).
      - 'net_invested' => profit relative to total net invested capital (sum of deposits - sum of withdrawals).
    - price_resolver: same as get_portfolio_value
  - Behavior:
    - Get current_total = get_portfolio_value(price_resolver)
    - If reference == 'initial':
      - base = _initial_deposit
      - If _initial_deposit == 0: behavior documented — return current_total (treated as profit relative to zero) or raise warning. Implementation recommendation: return current_total - 0.
    - If reference == 'net_invested':
      - base = total_deposits() - total_withdrawals()
        - Note: keep methods total_deposits() and total_withdrawals() or compute by scanning transactions
    - Return current_total - base
  - Returns: float (positive profit, negative loss)
  - Exceptions: Same as get_portfolio_value if a price cannot be obtained.

9. list_transactions

  def list_transactions(self, start: Optional[datetime] = None, end: Optional[datetime] = None, tx_type: Optional[Literal['deposit','withdraw','buy','sell']] = None, symbol: Optional[str] = None) -> List[Transaction]

  - Purpose: Return list of transactions, optionally filtered by time window, type, and/or symbol.
  - Behavior:
    - Filter _transactions with provided criteria and return a shallow copy list in chronological order.
  - Returns: List[Transaction]

10. total_deposits and total_withdrawals (helpers)

  def total_deposits(self) -> float
  def total_withdrawals(self) -> float

  - Purpose: Compute cumulative deposits and withdrawals from transaction history.
  - Behavior: Sum transaction.total where transaction.type matches and sign convention respected.

11. get_realized_unrealized_pnl_breakdown

  def get_realized_unrealized_pnl_breakdown(self, price_resolver: Optional[Callable[[str], float]] = None) -> Dict[str, float]

  - Purpose: Provide structured PnL:
    - realized_pnl: float (sum across positions)
    - unrealized_pnl: float (sum across positions: (market_price - avg_cost) * quantity)
    - total_pnl: realized + unrealized
  - Behavior:
    - Use price_resolver to get current market prices.
    - For each Position, compute unrealized and sum.

12. serialize / to_dict / from_dict (persistence helpers)

  def to_dict(self) -> Dict[str, Any]
  @classmethod
  def from_dict(cls, data: Dict[str, Any]) -> "Account"

  - Purpose: Allow basic serialization of account state (transactions, holdings, cash) for tests or simple persistence.
  - Behavior: Convert dataclasses to JSON-serializable structures (timestamps to ISO strings). from_dict recreates objects.

13. Optional helper: reset (for tests)

  def _reset(self) -> None
  - Purpose: Clear transactions, positions, and cash to 0. For test harness convenience only.

- Internal helper methods
  - _record_transaction(self, tx: Transaction) -> None
    - Append transaction to _transactions; optional validation that balance_after equals internal _cash
  - _get_position(self, symbol: str) -> Optional[Position]
    - Return existing Position or None
  - Thread-safety: All public state-mutating methods (deposit, withdraw, buy, sell) should acquire _lock if concurrency is expected.

----

Important business rules & validations (explicit)

- All monetary amounts (deposit, withdraw, buy total, sell proceeds) are floats and must be > 0 for deposit/buy/sell and withdraw.
- Withdrawals that would make cash negative are forbidden (InsufficientFundsError).
- Buys require sufficient cash: cost = quantity * price <= cash (exact floating rounding policy should be documented in implementation; tests should assert a consistent policy).
- Sales require sufficient quantity of symbol in holdings (InsufficientSharesError).
- get_share_price returns price per unit; if price is missing, operations that require price should raise UnknownSymbolError (caller may pass explicit price to avoid this).
- Transactions are recorded in chronological order. On each transaction record the cash balance after the operation (balance_after).
- For buys, transactions.total is negative (cash outflow). For sells, transactions.total is positive. For deposit positive, for withdraw negative. This convention makes summing deposits/withdrawals straightforward.
- "Initial deposit" semantics:
  - If an initial_deposit value is supplied to __init__ and > 0, that value is stored as _initial_deposit.
  - If initial_deposit is 0 at construction, then the first deposit call sets _initial_deposit to that deposit amount. This preserves the idea of "initial deposit".
  - get_profit_loss(reference='initial') subtracts this _initial_deposit from current portfolio value.
  - get_profit_loss(reference='net_invested') uses sum(deposits) - sum(withdrawals) as base.

----

Example method signatures summarized (code block)

Below are the key signatures succinctly listed for easy reference.

```python
# Exceptions
class AccountError(Exception): ...
class InvalidAmountError(AccountError): ...
class InsufficientFundsError(AccountError): ...
class InsufficientSharesError(AccountError): ...
class UnknownSymbolError(AccountError): ...
class TransactionError(AccountError): ...

# Module helper
def get_share_price(symbol: str) -> float:
    """Return fixed price for test symbols AAPL, TSLA, GOOGL; raise UnknownSymbolError otherwise."""

# Dataclasses
@dataclass
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

@dataclass
class Position:
    symbol: str
    quantity: float
    avg_cost: float
    realized_pnl: float

# Account
class Account:
    def __init__(self, user_id: str, initial_deposit: float = 0.0, currency: str = 'USD') -> None: ...

    def deposit(self, amount: float, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction: ...
    def withdraw(self, amount: float, timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction: ...

    def buy(self, symbol: str, quantity: float, price: Optional[float] = None,
            timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction: ...

    def sell(self, symbol: str, quantity: float, price: Optional[float] = None,
             timestamp: Optional[datetime] = None, note: Optional[str] = None) -> Transaction: ...

    def get_cash_balance(self) -> float: ...
    def get_holdings(self) -> Dict[str, Position]: ...
    def get_portfolio_value(self, price_resolver: Optional[Callable[[str], float]] = None) -> float: ...
    def get_profit_loss(self, reference: Literal['initial','net_invested'] = 'initial',
                        price_resolver: Optional[Callable[[str], float]] = None) -> float: ...

    def list_transactions(self, start: Optional[datetime] = None, end: Optional[datetime] = None,
                          tx_type: Optional[str] = None, symbol: Optional[str] = None) -> List[Transaction]: ...

    def total_deposits(self) -> float: ...
    def total_withdrawals(self) -> float: ...
    def get_realized_unrealized_pnl_breakdown(self, price_resolver: Optional[Callable[[str], float]] = None) -> Dict[str, float]: ...

    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account": ...
```

----

Implementation notes / decisions for the engineer

- Floating point arithmetic:
  - Decide on rounding policy for monetary values. For simplicity in the simulation, using Python float is acceptable, but if higher precision is needed consider decimal.Decimal with a configured context and currency precision.
  - When computing totals (price * quantity), decide whether to round to cents. Document chosen policy and make tests reflect it.

- Timestamps:
  - Use datetime.datetime in UTC (datetime.utcnow()) for transaction timestamps by default. Serialize to ISO format in to_dict.

- Transaction IDs:
  - Use uuid.uuid4().hex to produce stable unique tx_id.

- Thread-safety:
  - If the account may be used concurrently, wrap state-mutating operations in threading.Lock to ensure consistency.

- Price resolution:
  - All methods that need current market prices accept an optional price_resolver to facilitate testing (inject deterministic prices) or to plug in a real market data service later.

- Tests:
  - Provide unit tests that:
    - Create an account, deposit money, buy shares, verify positions and cash.
    - Attempt invalid operations and confirm the correct exceptions are raised (insufficient funds/shares).
    - Verify portfolio value and profit/loss calculations using the test get_share_price mapping.
    - Verify transaction history correctness.

- Persistence:
  - to_dict/from_dict should be sufficient for simple persistence; a database or file-based persistence can be added later.

----

Example workflow (behavioral sequence)

1. Create account
   - acct = Account(user_id='alice', initial_deposit=10000.0)
   - Cash: 10000.0, initial_deposit: 10000.0

2. Buy 10 AAPL with market price (150.0)
   - buy('AAPL', 10)
   - cost = 150.0 * 10 = 1500.0
   - Cash after buy = 8500.0
   - Position AAPL quantity=10, avg_cost=150.0

3. Sell 2 AAPL at market (150.0)
   - sell('AAPL', 2)
   - proceeds = 300.0
   - realized_pnl for AAPL = (150.0 - 150.0) * 2 = 0
   - Cash after sell = 8800.0
   - Position AAPL quantity=8

4. get_portfolio_value()
   - cash + 8 * 150.0 = 8800.0 + 1200.0 = 10000.0

5. get_profit_loss(reference='initial')
   - portfolio_value - initial_deposit = 10000.0 - 10000.0 = 0.0

6. list_transactions() returns deposit, buy, sell with accurate balance_after values.

----

Edge cases to document and test

- Buying fractional shares (e.g., quantity 0.5) — allowed if system should support it; else validate it's an integer.
- Zero initial deposit and later deposits — ensure initial_deposit semantics are correct.
- Selling partial shares until quantity becomes zero: ensure avg_cost reset and position removed or maintained with zero quantity based on design choice (recommended: remove symbol from positions if quantity == 0).
- Rounding differences when price * quantity results in repeating decimals — choose to round to cents or keep full float.

----

Minimal example of the get_share_price test implementation (to be implemented in module)

```python
def get_share_price(symbol: str) -> float:
    symbol_up = symbol.upper()
    prices = {
        'AAPL': 150.0,
        'TSLA': 700.0,
        'GOOGL': 2800.0,
    }
    try:
        return prices[symbol_up]
    except KeyError:
        raise UnknownSymbolError(f"Unknown symbol: {symbol}")
```

----

Deliverable checklist for the implementing engineer

- Implement the exceptions as specified.
- Implement Transaction and Position dataclasses with required fields and simple validation where appropriate.
- Implement get_share_price test mapping exactly as shown and raise UnknownSymbolError for unknown symbols.
- Implement Account class and all public methods, with clear docstrings describing inputs, outputs, and raised exceptions.
- Ensure transactions list records balance_after and that transaction.total uses the sign convention described.
- Add unit tests covering normal flows and failure modes (insufficient funds/shares, unknown symbols, invalid amounts).
- Add serialization helpers and optionally thread-safety if concurrent use is expected.

----

This completes the detailed design and the complete list of classes, functions, signatures, behaviors, return types, validations, and implementation notes required to implement accounts.py and the Account class to satisfy the provided requirements.
