"""
Accounting Engine - Automatic Journal Entry Generation
Converts transactions into double-entry bookkeeping journal entries
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from database import ChartOfAccountsEntry, Document, JournalEntry, JournalEntryLine

from .chart_of_accounts import (
    DEFAULT_CASH_ACCOUNT,
    AccountNature,
    AccountType,
    BrazilianChartOfAccounts,
)


class AccountingEngine:
    """
    Automatic journal entry generation from financial transactions
    """

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._account_cache = {}  # Cache for account lookups

    def generate_journal_entry_from_transaction(
        self,
        transaction_data: Dict,
        document_id: Optional[int] = None,
        created_by: str = "system",
    ) -> JournalEntry:
        """
        Generate automatic journal entry from a transaction

        Args:
            transaction_data: Dict with keys: date, amount, category, transaction_type, description
            document_id: Optional link to source document
            created_by: Who created this entry (default: "system")

        Returns:
            JournalEntry object (saved to database)
        """
        category = transaction_data.get("category", "uncategorized")
        transaction_type = transaction_data.get("transaction_type", "expense")
        amount = transaction_data.get("amount", Decimal("0"))
        date = transaction_data.get("date")
        description = transaction_data.get(
            "description", f"{transaction_type}: {category}"
        )

        # Convert string date to datetime if needed
        if isinstance(date, str):
            date = datetime.strptime(date, "%Y-%m-%d")
        elif not isinstance(date, datetime):
            date = datetime.now()

        # Convert amount to cents (integer)
        amount_cents = int(amount * 100)

        # Determine accounts based on category and transaction type
        debit_account_code, credit_account_code = self._determine_accounts(
            category, transaction_type
        )

        # Get or create accounts
        debit_account = self._get_or_create_account(debit_account_code)
        credit_account = self._get_or_create_account(credit_account_code)

        # Create journal entry
        journal_entry = JournalEntry(
            user_id=self.user_id,
            entry_date=date,
            description=description,
            source_type="automatic",
            source_document_id=document_id,
            created_by=created_by,
            is_posted=True,
        )
        self.db.add(journal_entry)
        self.db.flush()  # Get ID without committing

        # Create debit line
        debit_line = JournalEntryLine(
            journal_entry_id=journal_entry.id,
            account_id=debit_account.id,
            debit_amount=amount_cents,
            credit_amount=0,
            line_order=1,
        )
        self.db.add(debit_line)

        # Create credit line
        credit_line = JournalEntryLine(
            journal_entry_id=journal_entry.id,
            account_id=credit_account.id,
            debit_amount=0,
            credit_amount=amount_cents,
            line_order=2,
        )
        self.db.add(credit_line)

        # Update account balances
        self._update_account_balance(debit_account, debit_amount=amount_cents)
        self._update_account_balance(credit_account, credit_amount=amount_cents)

        self.db.commit()
        self.db.refresh(journal_entry)

        return journal_entry

    def _determine_accounts(
        self, category: str, transaction_type: str
    ) -> Tuple[str, str]:
        """
        Determine which accounts to debit and credit

        Returns:
            Tuple of (debit_account_code, credit_account_code)
        """
        category_lower = category.lower() if category else "uncategorized"

        # INCOME TRANSACTIONS
        from accounting import is_income_type
        if is_income_type(transaction_type):
            # DEBIT: Cash (asset increases)
            # CREDIT: Revenue account

            if "sales" in category_lower or "venda" in category_lower:
                return (DEFAULT_CASH_ACCOUNT, "4.01.001")  # Receita de Vendas
            elif "service" in category_lower or "servi" in category_lower:
                return (DEFAULT_CASH_ACCOUNT, "4.01.002")  # Receita de Serviços
            elif "financial" in category_lower or "interest_income" in category_lower:
                return (DEFAULT_CASH_ACCOUNT, "4.03.001")  # Receitas Financeiras
            else:
                # Default: Other revenue
                return (DEFAULT_CASH_ACCOUNT, "4.01.001")  # Receita de Vendas

        # EXPENSE TRANSACTIONS
        else:
            # DEBIT: Expense account
            # CREDIT: Cash (asset decreases)

            # Cost of Goods/Services
            if "cogs" in category_lower or "cmv" in category_lower:
                return ("5.01.001", DEFAULT_CASH_ACCOUNT)  # CMV
            elif "cost_of_services" in category_lower or "csp" in category_lower:
                return ("5.01.002", DEFAULT_CASH_ACCOUNT)  # CSP

            # Operating Expenses - Administrative
            elif (
                "salary" in category_lower
                or "salario" in category_lower
                or "payroll" in category_lower
            ):
                return ("5.02.001", DEFAULT_CASH_ACCOUNT)  # Salários e Encargos
            elif "rent" in category_lower or "aluguel" in category_lower:
                return ("5.02.002", DEFAULT_CASH_ACCOUNT)  # Aluguéis
            elif "electric" in category_lower or "energia" in category_lower:
                return ("5.02.003", DEFAULT_CASH_ACCOUNT)  # Energia Elétrica
            elif "water" in category_lower or "agua" in category_lower:
                return ("5.02.004", DEFAULT_CASH_ACCOUNT)  # Água
            elif (
                "phone" in category_lower
                or "internet" in category_lower
                or "telefone" in category_lower
            ):
                return ("5.02.005", DEFAULT_CASH_ACCOUNT)  # Telefone e Internet
            elif "office" in category_lower or "escritorio" in category_lower:
                return ("5.02.006", DEFAULT_CASH_ACCOUNT)  # Material de Escritório
            elif (
                "professional" in category_lower
                or "accounting" in category_lower
                or "legal" in category_lower
            ):
                return ("5.02.007", DEFAULT_CASH_ACCOUNT)  # Serviços Profissionais
            elif "insurance" in category_lower or "seguro" in category_lower:
                return ("5.02.008", DEFAULT_CASH_ACCOUNT)  # Seguros
            elif "maintenance" in category_lower or "manutencao" in category_lower:
                return ("5.02.009", DEFAULT_CASH_ACCOUNT)  # Manutenção

            # Operating Expenses - Sales
            elif (
                "marketing" in category_lower
                or "advertising" in category_lower
                or "publicidade" in category_lower
            ):
                return ("5.02.010", DEFAULT_CASH_ACCOUNT)  # Marketing
            elif "commission" in category_lower or "comiss" in category_lower:
                return ("5.02.011", DEFAULT_CASH_ACCOUNT)  # Comissões
            elif "freight" in category_lower or "frete" in category_lower:
                return ("5.02.012", DEFAULT_CASH_ACCOUNT)  # Fretes

            # Depreciation/Amortization
            elif "depreciation" in category_lower or "depreciacao" in category_lower:
                return ("5.02.013", DEFAULT_CASH_ACCOUNT)  # Depreciação
            elif "amortization" in category_lower or "amortizacao" in category_lower:
                return ("5.02.014", DEFAULT_CASH_ACCOUNT)  # Amortização

            # Financial Expenses
            elif (
                "interest_expense" in category_lower
                or "financial_expense" in category_lower
            ):
                return ("5.03.001", DEFAULT_CASH_ACCOUNT)  # Despesas Financeiras
            elif "bank_fee" in category_lower or "tarifa" in category_lower:
                return ("5.03.002", DEFAULT_CASH_ACCOUNT)  # Tarifas Bancárias

            # Taxes
            elif "icms" in category_lower:
                return ("5.04.001", DEFAULT_CASH_ACCOUNT)  # ICMS
            elif "iss" in category_lower:
                return ("5.04.002", DEFAULT_CASH_ACCOUNT)  # ISS
            elif "pis" in category_lower:
                return ("5.04.003", DEFAULT_CASH_ACCOUNT)  # PIS
            elif "cofins" in category_lower:
                return ("5.04.004", DEFAULT_CASH_ACCOUNT)  # COFINS
            elif "irpj" in category_lower or "income_tax" in category_lower:
                return ("5.04.005", DEFAULT_CASH_ACCOUNT)  # IRPJ
            elif "csll" in category_lower or "social_contribution" in category_lower:
                return ("5.04.006", DEFAULT_CASH_ACCOUNT)  # CSLL

            # Default: General operating expense
            else:
                return (
                    "5.02.001",
                    DEFAULT_CASH_ACCOUNT,
                )  # Default to Salários (will be categorized)

    def _get_or_create_account(self, account_code: str) -> ChartOfAccountsEntry:
        """
        Get account from database or create if doesn't exist
        Uses cache for performance
        """
        # Check cache first
        cache_key = f"{self.user_id}:{account_code}"
        if cache_key in self._account_cache:
            return self._account_cache[cache_key]

        # Query database
        account = (
            self.db.query(ChartOfAccountsEntry)
            .filter(
                ChartOfAccountsEntry.user_id == self.user_id,
                ChartOfAccountsEntry.account_code == account_code,
            )
            .first()
        )

        if not account:
            # Create from standard chart of accounts
            standard_account = BrazilianChartOfAccounts.get_account(account_code)
            if not standard_account:
                raise ValueError(f"Unknown account code: {account_code}")

            account = ChartOfAccountsEntry(
                user_id=self.user_id,
                account_code=standard_account["code"],
                account_name=standard_account["name"],
                account_type=standard_account["type"].value,
                account_nature=standard_account["nature"].value,
                description=standard_account.get("description", ""),
                is_system_account=True,
                current_balance=0,
            )
            self.db.add(account)
            self.db.flush()

        # Cache it
        self._account_cache[cache_key] = account
        return account

    def _update_account_balance(
        self,
        account: ChartOfAccountsEntry,
        debit_amount: int = 0,
        credit_amount: int = 0,
    ):
        """
        Update account balance based on its nature

        Debit nature accounts (Assets, Expenses):
        - Increase with debits
        - Decrease with credits

        Credit nature accounts (Liabilities, Equity, Revenue):
        - Increase with credits
        - Decrease with debits
        """
        if account.account_nature == AccountNature.DEBIT.value:
            # Debit nature: debits increase, credits decrease
            account.current_balance += debit_amount
            account.current_balance -= credit_amount
        else:
            # Credit nature: credits increase, debits decrease
            account.current_balance += credit_amount
            account.current_balance -= debit_amount

    def create_manual_journal_entry(
        self, entry_date: datetime, description: str, lines: List[Dict], created_by: str
    ) -> JournalEntry:
        """
        Create a manual journal entry with custom debit/credit lines

        Args:
            entry_date: Date of the entry
            description: Entry description
            lines: List of dicts with keys: account_code, debit_amount, credit_amount, description
            created_by: User email

        Returns:
            JournalEntry object

        Raises:
            ValueError: If entry doesn't balance (debits != credits)
        """
        # Validate that entry balances
        total_debits = sum(line.get("debit_amount", 0) for line in lines)
        total_credits = sum(line.get("credit_amount", 0) for line in lines)

        if total_debits != total_credits:
            raise ValueError(
                f"Journal entry does not balance: Debits={total_debits}, Credits={total_credits}"
            )

        # Create journal entry
        journal_entry = JournalEntry(
            user_id=self.user_id,
            entry_date=entry_date,
            description=description,
            source_type="manual",
            created_by=created_by,
            is_posted=True,
        )
        self.db.add(journal_entry)
        self.db.flush()

        # Create lines
        for idx, line_data in enumerate(lines):
            account_code = line_data["account_code"]
            # Values are expected in cents
            debit = int(line_data.get("debit_amount", 0))
            credit = int(line_data.get("credit_amount", 0))
            line_desc = line_data.get("description", "")

            # Get or create account
            account = self._get_or_create_account(account_code)

            # Create line
            line = JournalEntryLine(
                journal_entry_id=journal_entry.id,
                account_id=account.id,
                debit_amount=debit,
                credit_amount=credit,
                description=line_desc,
                line_order=idx + 1,
            )
            self.db.add(line)

            # Update account balance
            self._update_account_balance(
                account, debit_amount=debit, credit_amount=credit
            )

        self.db.commit()
        self.db.refresh(journal_entry)

        return journal_entry

    def set_opening_balances(
        self,
        opening_date: datetime,
        balances: Dict[str, Decimal],
        created_by: str = "system",
    ) -> JournalEntry:
        """
        Set opening balances for accounts

        Args:
            opening_date: Date of opening balances
            balances: Dict of {account_code: balance_amount}
            created_by: Who is setting these balances

        Returns:
            JournalEntry with opening balances
        """
        lines = []

        for account_code, balance in balances.items():
            account_info = BrazilianChartOfAccounts.get_account(account_code)
            if not account_info:
                continue

            # Convert to Decimal if needed (values are in dollars)
            if not isinstance(balance, Decimal):
                balance = Decimal(str(balance))

            # Convert dollars to cents for storage
            balance_cents = int(balance * 100)

            # Determine debit or credit based on account nature and balance sign
            if account_info["nature"] == AccountNature.DEBIT:
                # Debit nature accounts (Assets, Expenses)
                if balance_cents >= 0:
                    lines.append(
                        {
                            "account_code": account_code,
                            "debit_amount": balance_cents,
                            "credit_amount": 0,
                            "description": "Saldo inicial",
                        }
                    )
                else:
                    lines.append(
                        {
                            "account_code": account_code,
                            "debit_amount": 0,
                            "credit_amount": abs(balance_cents),
                            "description": "Saldo inicial",
                        }
                    )
            else:
                # Credit nature accounts (Liabilities, Equity, Revenue)
                if balance_cents >= 0:
                    lines.append(
                        {
                            "account_code": account_code,
                            "debit_amount": 0,
                            "credit_amount": balance_cents,
                            "description": "Saldo inicial",
                        }
                    )
                else:
                    lines.append(
                        {
                            "account_code": account_code,
                            "debit_amount": abs(balance_cents),
                            "credit_amount": 0,
                            "description": "Saldo inicial",
                        }
                    )

        # Add balancing entry to "Lucros Acumulados" (Retained Earnings)
        total_debits = sum(line["debit_amount"] for line in lines)
        total_credits = sum(line["credit_amount"] for line in lines)
        difference = total_debits - total_credits

        if difference != 0:
            lines.append(
                {
                    "account_code": "3.04.001",  # Lucros Acumulados
                    "debit_amount": 0 if difference > 0 else abs(difference),
                    "credit_amount": difference if difference > 0 else 0,
                    "description": "Saldo inicial - contrapartida",
                }
            )

        return self.create_manual_journal_entry(
            entry_date=opening_date,
            description="Saldos Iniciais",
            lines=lines,
            created_by=created_by,
        )

    def reverse_journal_entry(
        self,
        original_entry_id: int,
        reversal_date: datetime,
        created_by: str,
        reason: str = "Estorno",
    ) -> JournalEntry:
        """
        Reverse (estornar) a journal entry

        Creates a new entry with opposite debits/credits
        """
        # Get original entry
        original = (
            self.db.query(JournalEntry)
            .filter(
                JournalEntry.id == original_entry_id,
                JournalEntry.user_id == self.user_id,
            )
            .first()
        )

        if not original:
            raise ValueError(f"Journal entry {original_entry_id} not found")

        if original.is_reversed:
            raise ValueError(f"Entry {original_entry_id} is already reversed")

        # Create reversal entry
        reversal = JournalEntry(
            user_id=self.user_id,
            entry_date=reversal_date,
            description=f"{reason} - {original.description}",
            source_type="adjustment",
            reversal_of_entry_id=original_entry_id,
            created_by=created_by,
            is_posted=True,
        )
        self.db.add(reversal)
        self.db.flush()

        # OPTIMIZATION: Pre-load all accounts in one query to avoid N+1
        account_ids = [line.account_id for line in original.lines]
        accounts = (
            self.db.query(ChartOfAccountsEntry)
            .filter(ChartOfAccountsEntry.id.in_(account_ids))
            .all()
        )
        accounts_map = {acc.id: acc for acc in accounts}

        # Create reverse lines (swap debits and credits)
        for original_line in original.lines:
            reverse_line = JournalEntryLine(
                journal_entry_id=reversal.id,
                account_id=original_line.account_id,
                debit_amount=original_line.credit_amount,  # Swap
                credit_amount=original_line.debit_amount,  # Swap
                description=original_line.description,
                line_order=original_line.line_order,
            )
            self.db.add(reverse_line)

            # Update account balance (reverse) - get from pre-loaded map (no query!)
            account = accounts_map[original_line.account_id]
            self._update_account_balance(
                account,
                debit_amount=original_line.credit_amount,  # Reversed
                credit_amount=original_line.debit_amount,  # Reversed
            )

        # Mark original as reversed
        original.is_reversed = True

        self.db.commit()
        self.db.refresh(reversal)

        return reversal
