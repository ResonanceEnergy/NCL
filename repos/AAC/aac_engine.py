#!/usr/bin/env python3
"""
AAC - Automated Accounting Center
Core accounting engine for Super Agency financial operations
"""

import sqlite3
import json
import logging
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import uuid

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AccountingError(Exception):
    """Custom exception for accounting operations"""
    pass

class Account:
    """Represents a chart of accounts entry"""

    def __init__(self, account_id: str, name: str, account_type: str,
                 parent_id: Optional[str] = None, description: str = ""):
        self.account_id = account_id
        self.name = name
        self.account_type = account_type  # Asset, Liability, Equity, Revenue, Expense
        self.parent_id = parent_id
        self.description = description
        self.balance = Decimal('0.00')
        self.created_date = datetime.now()
        self.is_active = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            'account_id': self.account_id,
            'name': self.name,
            'account_type': self.account_type,
            'parent_id': self.parent_id,
            'description': self.description,
            'balance': str(self.balance),
            'created_date': self.created_date.isoformat(),
            'is_active': self.is_active
        }

class Transaction:
    """Represents a financial transaction"""

    def __init__(self, transaction_id: str, date: date, description: str,
                 entries: List[Dict[str, Any]], reference: str = ""):
        self.transaction_id = transaction_id
        self.date = date
        self.description = description
        self.entries = entries  # List of {'account_id': str, 'debit': Decimal, 'credit': Decimal}
        self.reference = reference
        self.created_date = datetime.now()
        self.posted = False

    def get_total_debit(self) -> Decimal:
        return sum(Decimal(str(entry.get('debit', '0'))) for entry in self.entries)

    def get_total_credit(self) -> Decimal:
        return sum(Decimal(str(entry.get('credit', '0'))) for entry in self.entries)

    def is_balanced(self) -> bool:
        return self.get_total_debit() == self.get_total_credit()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'transaction_id': self.transaction_id,
            'date': self.date.isoformat(),
            'description': self.description,
            'entries': self.entries,
            'reference': self.reference,
            'created_date': self.created_date.isoformat(),
            'posted': self.posted
        }

class AccountingEngine:
    """Core accounting engine for AAC"""

    def __init__(self, db_path: str = "aac_accounting.db"):
        self.db_path = db_path
        self.conn = None
        self.initialize_database()

    def initialize_database(self):
        """Initialize the accounting database"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Create tables
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                account_type TEXT NOT NULL,
                parent_id TEXT,
                description TEXT,
                balance TEXT DEFAULT '0.00',
                created_date TEXT,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (parent_id) REFERENCES accounts (account_id)
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                reference TEXT,
                created_date TEXT,
                posted INTEGER DEFAULT 0
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS transaction_entries (
                entry_id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                debit TEXT DEFAULT '0.00',
                credit TEXT DEFAULT '0.00',
                FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id),
                FOREIGN KEY (account_id) REFERENCES accounts (account_id)
            )
        ''')

        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS journal_entries (
                entry_id TEXT PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                amount TEXT NOT NULL,
                entry_type TEXT NOT NULL, -- 'debit' or 'credit'
                date TEXT NOT NULL,
                description TEXT,
                FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id),
                FOREIGN KEY (account_id) REFERENCES accounts (account_id)
            )
        ''')

        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def create_account(self, account: Account) -> bool:
        """Create a new account"""
        try:
            self.conn.execute('''
                INSERT INTO accounts (account_id, name, account_type, parent_id,
                                    description, balance, created_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account.account_id, account.name, account.account_type,
                account.parent_id, account.description, str(account.balance),
                account.created_date.isoformat(), account.is_active
            ))
            self.conn.commit()
            logger.info(f"Created account: {account.name} ({account.account_id})")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error creating account: {e}")
            return False

    def get_account(self, account_id: str) -> Optional[Account]:
        """Get account by ID"""
        cursor = self.conn.execute('''
            SELECT * FROM accounts WHERE account_id = ?
        ''', (account_id,))

        row = cursor.fetchone()
        if row:
            account = Account(
                account_id=row[0], name=row[1], account_type=row[2],
                parent_id=row[3], description=row[4]
            )
            account.balance = Decimal(row[5])
            account.created_date = datetime.fromisoformat(row[6])
            account.is_active = bool(row[7])
            return account
        return None

    def record_transaction(self, transaction: Transaction) -> bool:
        """Record a transaction"""
        if not transaction.is_balanced():
            raise AccountingError("Transaction is not balanced")

        try:
            # Insert transaction
            self.conn.execute('''
                INSERT INTO transactions (transaction_id, date, description,
                                        reference, created_date, posted)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                transaction.transaction_id, transaction.date.isoformat(),
                transaction.description, transaction.reference,
                transaction.created_date.isoformat(), transaction.posted
            ))

            # Insert transaction entries
            for entry in transaction.entries:
                entry_id = str(uuid.uuid4())
                self.conn.execute('''
                    INSERT INTO transaction_entries (entry_id, transaction_id,
                                                   account_id, debit, credit)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    entry_id, transaction.transaction_id, entry['account_id'],
                    str(entry.get('debit', '0')), str(entry.get('credit', '0'))
                ))

                # Update account balance
                self.update_account_balance(entry['account_id'],
                                          Decimal(str(entry.get('debit', '0'))),
                                          Decimal(str(entry.get('credit', '0'))))

            self.conn.commit()
            logger.info(f"Recorded transaction: {transaction.description}")
            return True

        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Error recording transaction: {e}")
            return False

    def update_account_balance(self, account_id: str, debit: Decimal, credit: Decimal):
        """Update account balance based on transaction entry"""
        account = self.get_account(account_id)
        if not account:
            return

        # Determine balance change based on account type
        if account.account_type in ['Asset', 'Expense']:
            account.balance += debit - credit
        elif account.account_type in ['Liability', 'Equity', 'Revenue']:
            account.balance += credit - debit

        # Update in database
        self.conn.execute('''
            UPDATE accounts SET balance = ? WHERE account_id = ?
        ''', (str(account.balance), account_id))

    def get_balance_sheet(self, as_of_date: Optional[date] = None) -> Dict[str, Any]:
        """Generate balance sheet"""
        if as_of_date is None:
            as_of_date = date.today()

        # Get all accounts
        cursor = self.conn.execute('''
            SELECT account_type, SUM(CAST(balance AS DECIMAL)) as total
            FROM accounts
            WHERE is_active = 1
            GROUP BY account_type
        ''')

        balances = {row[0]: Decimal(str(row[1])) for row in cursor.fetchall()}

        return {
            'as_of_date': as_of_date.isoformat(),
            'assets': balances.get('Asset', Decimal('0')),
            'liabilities': balances.get('Liability', Decimal('0')),
            'equity': balances.get('Equity', Decimal('0')),
            'total_liabilities_equity': balances.get('Liability', Decimal('0')) + balances.get('Equity', Decimal('0'))
        }

    def get_income_statement(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Generate income statement"""
        # This is a simplified version - in production would filter by date
        cursor = self.conn.execute('''
            SELECT account_type, SUM(CAST(balance AS DECIMAL)) as total
            FROM accounts
            WHERE is_active = 1 AND account_type IN ('Revenue', 'Expense')
            GROUP BY account_type
        ''')

        balances = {row[0]: Decimal(str(row[1])) for row in cursor.fetchall()}

        revenue = balances.get('Revenue', Decimal('0'))
        expenses = balances.get('Expense', Decimal('0'))
        net_income = revenue - expenses

        return {
            'period_start': start_date.isoformat(),
            'period_end': end_date.isoformat(),
            'revenue': revenue,
            'expenses': expenses,
            'net_income': net_income
        }

    def setup_default_accounts(self):
        """Set up default chart of accounts"""
        default_accounts = [
            # Assets
            Account("1000", "Cash", "Asset", description="Primary cash account"),
            Account("1100", "Accounts Receivable", "Asset", description="Money owed by customers"),
            Account("1200", "Inventory", "Asset", description="Goods held for sale"),

            # Liabilities
            Account("2000", "Accounts Payable", "Liability", description="Money owed to suppliers"),
            Account("2100", "Loans Payable", "Liability", description="Outstanding loans"),

            # Equity
            Account("3000", "Owner's Equity", "Equity", description="Owner's investment"),
            Account("3100", "Retained Earnings", "Equity", description="Accumulated profits"),

            # Revenue
            Account("4000", "Sales Revenue", "Revenue", description="Revenue from sales"),
            Account("4100", "Service Revenue", "Revenue", description="Revenue from services"),

            # Expenses
            Account("5000", "Cost of Goods Sold", "Expense", description="Cost of products sold"),
            Account("5100", "Operating Expenses", "Expense", description="Day-to-day operating costs"),
            Account("5200", "Marketing Expenses", "Expense", description="Marketing and advertising costs"),
        ]

        for account in default_accounts:
            if not self.get_account(account.account_id):
                self.create_account(account)

        logger.info("Default chart of accounts created")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

def main():
    """Main function for AAC accounting engine"""
    print("🚀 AAC - Automated Accounting Center")
    print("=" * 50)

    # Initialize accounting engine
    engine = AccountingEngine()

    try:
        # Set up default accounts
        print("📊 Setting up default chart of accounts...")
        engine.setup_default_accounts()

        # Example transaction
        print("💰 Recording sample transaction...")
        transaction = Transaction(
            transaction_id=str(uuid.uuid4()),
            date=date.today(),
            description="Sample revenue transaction",
            entries=[
                {'account_id': '1000', 'debit': '1000.00', 'credit': '0.00'},  # Cash
                {'account_id': '4000', 'debit': '0.00', 'credit': '1000.00'}   # Sales Revenue
            ]
        )

        if engine.record_transaction(transaction):
            print("✅ Transaction recorded successfully")

        # Generate reports
        print("📈 Generating financial reports...")
        balance_sheet = engine.get_balance_sheet()
        print(f"Balance Sheet as of {balance_sheet['as_of_date']}:")
        print(f"  Assets: ${balance_sheet['assets']}")
        print(f"  Liabilities: ${balance_sheet['liabilities']}")
        print(f"  Equity: ${balance_sheet['equity']}")

        income_stmt = engine.get_income_statement(date(2026, 1, 1), date.today())
        print(f"Income Statement:")
        print(f"  Revenue: ${income_stmt['revenue']}")
        print(f"  Expenses: ${income_stmt['expenses']}")
        print(f"  Net Income: ${income_stmt['net_income']}")

        print("🎉 AAC accounting engine initialized successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        engine.close()

if __name__ == "__main__":
    main()