"""
Cash Flow Statement (Demonstração do Fluxo de Caixa - DFC)
Simple implementation using the direct method
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from database import ChartOfAccountsEntry, JournalEntry, JournalEntryLine


class CashFlowStatement:
    """Cash Flow Statement (DFC) - Direct Method"""

    def __init__(
        self,
        reference_date: date,
        company_name: Optional[str] = None,
        cnpj: Optional[str] = None,
    ):
        self.reference_date = reference_date
        self.company_name = company_name
        self.cnpj = cnpj

        # Operating Activities (Atividades Operacionais)
        self.receipts_from_customers = Decimal("0")  # Recebimentos de clientes
        self.payments_to_suppliers = Decimal("0")  # Pagamentos a fornecedores
        self.payments_to_employees = Decimal("0")  # Pagamentos a empregados
        self.other_operating_receipts = Decimal("0")  # Outros recebimentos operacionais
        self.other_operating_payments = Decimal("0")  # Outros pagamentos operacionais
        self.cash_from_operations = Decimal("0")  # Total das atividades operacionais

        # Investing Activities (Atividades de Investimento)
        self.purchase_of_assets = Decimal("0")  # Aquisição de imobilizado
        self.sale_of_assets = Decimal("0")  # Venda de imobilizado
        self.cash_from_investing = Decimal("0")  # Total das atividades de investimento

        # Financing Activities (Atividades de Financiamento)
        self.proceeds_from_loans = Decimal("0")  # Empréstimos obtidos
        self.repayment_of_loans = Decimal("0")  # Pagamento de empréstimos
        self.capital_contributions = Decimal("0")  # Integralização de capital
        self.dividends_paid = Decimal("0")  # Dividendos pagos
        self.cash_from_financing = Decimal("0")  # Total das atividades de financiamento

        # Summary
        self.net_cash_change = Decimal("0")  # Aumento/Diminuição líquida de caixa
        self.cash_beginning = Decimal("0")  # Caixa no início do período
        self.cash_ending = Decimal("0")  # Caixa no final do período

    def calculate_totals(self):
        """Calculate totals and net cash change"""
        # Operating activities net
        self.cash_from_operations = (
            self.receipts_from_customers
            + self.other_operating_receipts
            - self.payments_to_suppliers
            - self.payments_to_employees
            - self.other_operating_payments
        )

        # Investing activities net
        self.cash_from_investing = self.sale_of_assets - self.purchase_of_assets

        # Financing activities net
        self.cash_from_financing = (
            self.proceeds_from_loans
            + self.capital_contributions
            - self.repayment_of_loans
            - self.dividends_paid
        )

        # Net change
        self.net_cash_change = (
            self.cash_from_operations
            + self.cash_from_investing
            + self.cash_from_financing
        )

        # Ending cash = Beginning cash + Net change
        self.cash_ending = self.cash_beginning + self.net_cash_change

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "reference_date": self.reference_date.isoformat(),
            "company_name": self.company_name,
            "cnpj": self.cnpj,
            "operating_activities": {
                "receipts_from_customers": float(self.receipts_from_customers),
                "payments_to_suppliers": float(self.payments_to_suppliers),
                "payments_to_employees": float(self.payments_to_employees),
                "other_operating_receipts": float(self.other_operating_receipts),
                "other_operating_payments": float(self.other_operating_payments),
                "net_cash_from_operations": float(self.cash_from_operations),
            },
            "investing_activities": {
                "purchase_of_assets": float(self.purchase_of_assets),
                "sale_of_assets": float(self.sale_of_assets),
                "net_cash_from_investing": float(self.cash_from_investing),
            },
            "financing_activities": {
                "proceeds_from_loans": float(self.proceeds_from_loans),
                "repayment_of_loans": float(self.repayment_of_loans),
                "capital_contributions": float(self.capital_contributions),
                "dividends_paid": float(self.dividends_paid),
                "net_cash_from_financing": float(self.cash_from_financing),
            },
            "summary": {
                "net_cash_change": float(self.net_cash_change),
                "cash_beginning": float(self.cash_beginning),
                "cash_ending": float(self.cash_ending),
            },
        }


class CashFlowCalculator:
    """Calculate Cash Flow Statement from journal entries"""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id

    def calculate_cash_flow(
        self,
        start_date: date,
        end_date: date,
        company_name: Optional[str] = None,
        cnpj: Optional[str] = None,
    ) -> CashFlowStatement:
        """
        Calculate cash flow statement for a period

        Args:
            start_date: Period start date
            end_date: Period end date
            company_name: Company name
            cnpj: CNPJ

        Returns:
            CashFlowStatement object
        """
        cf = CashFlowStatement(
            reference_date=end_date, company_name=company_name, cnpj=cnpj
        )

        # Get cash beginning balance (before start_date)
        cf.cash_beginning = self._get_cash_balance_at_date(
            datetime.combine(start_date, datetime.min.time()) - timedelta(days=1)
        )

        # Get all journal entries in period affecting cash accounts
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())

        # Get cash account IDs (1.01.001 = Caixa, 1.01.002 = Bancos)
        cash_accounts = (
            self.db.query(ChartOfAccountsEntry)
            .filter(
                and_(
                    ChartOfAccountsEntry.user_id == self.user_id,
                    ChartOfAccountsEntry.account_code.in_(["1.01.001", "1.01.002"]),
                    ChartOfAccountsEntry.is_active == True,
                )
            )
            .all()
        )

        cash_account_ids = [acc.id for acc in cash_accounts]

        # Get all lines affecting cash in the period
        cash_lines = (
            self.db.query(JournalEntryLine, JournalEntry)
            .join(JournalEntry)
            .filter(
                and_(
                    JournalEntryLine.account_id.in_(cash_account_ids),
                    JournalEntry.user_id == self.user_id,
                    JournalEntry.entry_date >= start_datetime,
                    JournalEntry.entry_date <= end_datetime,
                    JournalEntry.is_posted == True,
                    JournalEntry.is_reversed == False,
                )
            )
            .all()
        )

        # OPTIMIZATION: Pre-load all account codes for offsetting accounts in one query
        # to avoid N+1 queries (was querying once per transaction)
        all_account_ids = set()
        for line, entry in cash_lines:
            offsetting_lines = [l for l in entry.lines if l.id != line.id]
            if offsetting_lines:
                all_account_ids.add(offsetting_lines[0].account_id)

        # Single query to get all account codes
        accounts_map = (
            {
                acc.id: acc.account_code
                for acc in self.db.query(ChartOfAccountsEntry)
                .filter(ChartOfAccountsEntry.id.in_(all_account_ids))
                .all()
            }
            if all_account_ids
            else {}
        )

        # Categorize cash flows
        for line, entry in cash_lines:
            # Get the offsetting account (the other account in the entry)
            offsetting_lines = [l for l in entry.lines if l.id != line.id]
            if not offsetting_lines:
                continue

            offsetting_line = offsetting_lines[0]
            # Get account code from pre-loaded map (no query!)
            account_code = accounts_map.get(offsetting_line.account_id)

            if not account_code:
                continue

            # Cash flow = debit - credit on cash account (net effect)
            cash_effect = Decimal(line.debit_amount - line.credit_amount) / Decimal(100)

            # Operating Activities
            if account_code.startswith("4.01"):  # Revenue accounts
                cf.receipts_from_customers += abs(cash_effect)
            elif account_code.startswith("2.01.001"):  # Suppliers (Fornecedores)
                cf.payments_to_suppliers += abs(cash_effect)
            elif account_code.startswith("5.02.001"):  # Salaries
                cf.payments_to_employees += abs(cash_effect)
            elif account_code.startswith("5."):  # Other expenses
                cf.other_operating_payments += abs(cash_effect)

            # Investing Activities
            elif account_code.startswith("1.02"):  # Non-current assets
                if cash_effect > 0:
                    cf.sale_of_assets += abs(cash_effect)
                else:
                    cf.purchase_of_assets += abs(cash_effect)

            # Financing Activities
            elif account_code.startswith("2.02"):  # Non-current liabilities (loans)
                if cash_effect > 0:
                    cf.proceeds_from_loans += abs(cash_effect)
                else:
                    cf.repayment_of_loans += abs(cash_effect)
            elif account_code.startswith("3.01"):  # Capital
                cf.capital_contributions += abs(cash_effect)
            elif account_code.startswith("3.03"):  # Dividends
                cf.dividends_paid += abs(cash_effect)

        # Calculate totals
        cf.calculate_totals()

        # Get actual ending cash balance to verify
        cf.cash_ending = self._get_cash_balance_at_date(end_datetime)

        return cf

    def _get_cash_balance_at_date(self, up_to_date: datetime) -> Decimal:
        """Get total cash balance at a specific date"""
        from accounting.balance_sheet_calculator import BalanceSheetCalculator

        calculator = BalanceSheetCalculator(self.db, self.user_id)

        # Get balances for cash accounts (1.01.001 and 1.01.002)
        cash_balance = Decimal("0")

        for account_code in ["1.01.001", "1.01.002"]:
            account = (
                self.db.query(ChartOfAccountsEntry)
                .filter_by(user_id=self.user_id, account_code=account_code)
                .first()
            )

            if account:
                balance = calculator._calculate_account_balance_at_date(
                    account.id, up_to_date
                )
                cash_balance += balance

        return cash_balance


def calculate_cash_flow(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date,
    company_name: Optional[str] = None,
    cnpj: Optional[str] = None,
) -> CashFlowStatement:
    """
    Convenience function to calculate cash flow

    Args:
        db: Database session
        user_id: User ID
        start_date: Period start
        end_date: Period end
        company_name: Company name
        cnpj: CNPJ

    Returns:
        CashFlowStatement object
    """
    calculator = CashFlowCalculator(db, user_id)
    return calculator.calculate_cash_flow(start_date, end_date, company_name, cnpj)


# Add missing import
from datetime import timedelta
