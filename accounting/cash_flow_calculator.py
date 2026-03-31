"""
Demonstração do Fluxo de Caixa (DFC) Calculator

Implements both direct and indirect cash flow calculation methods
according to Brazilian accounting standards (CPC 03).

Uses document-based transaction data (same source as DRE).
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict
from sqlalchemy.orm import Session

from database import Document, DocumentStatus


@dataclass
class CashFlowSection:
    """Seção do Fluxo de Caixa"""

    section_name: str
    line_items: Dict[str, Decimal]  # {label: value}
    total: Decimal


@dataclass
class CashFlow:
    """Demonstração do Fluxo de Caixa (DFC)"""

    # Header
    company_name: str
    cnpj: str
    period_type: str  # "day", "week", "month", "year", "custom"
    start_date: date
    end_date: date
    method: str  # "direct" or "indirect"

    # Sections
    operating_activities: CashFlowSection
    investing_activities: CashFlowSection
    financing_activities: CashFlowSection

    # Totals
    net_cash_from_operations: Decimal
    net_cash_from_investments: Decimal
    net_cash_from_financing: Decimal
    net_increase_in_cash: Decimal

    # Cash position
    cash_beginning: Decimal
    cash_ending: Decimal


class CashFlowCalculator:
    """
    Calculadora de Fluxo de Caixa (DFC)

    Suporta dois métodos:
    - Método Indireto: Parte do lucro líquido e ajusta pelas variações patrimoniais
    - Método Direto: Mostra recebimentos e pagamentos reais

    Data source: Document-based transactions (same as DRE)
    """

    # Operating activity categories (for direct method)
    OPERATING_INFLOW_CATEGORIES = {
        "sales",
        "services",
        "other_income",
        "interest_income",
        "financial_income",
    }

    OPERATING_OUTFLOW_CATEGORIES = {
        "cogs",
        "cost_of_services",
        "salaries",
        "payroll",
        "rent",
        "utilities",
        "electricity",
        "water",
        "phone",
        "internet",
        "office_supplies",
        "marketing",
        "advertising",
        "commissions",
        "professional_services",
        "accounting_services",
        "legal_services",
        "insurance",
        "maintenance",
        "travel",
        "freight_out",
        "sales_tax_icms",
        "sales_tax_iss",
        "sales_tax_pis",
        "sales_tax_cofins",
    }

    # Investing activity categories
    INVESTING_OUTFLOW_CATEGORIES = {
        "purchase_equipment",
        "purchase_vehicle",
        "purchase_property",
        "purchase_software",
        "investments",
    }

    INVESTING_INFLOW_CATEGORIES = {
        "sale_equipment",
        "sale_vehicle",
        "sale_property",
        "investment_income",
    }

    # Financing activity categories
    FINANCING_INFLOW_CATEGORIES = {
        "loan_received",
        "capital_contribution",
        "capital_increase",
    }

    FINANCING_OUTFLOW_CATEGORIES = {
        "loan_payment",
        "interest_expense",
        "dividends_paid",
        "capital_withdrawal",
    }

    def __init__(self, db: Session, user_id: int, org_id: Optional[int] = None):
        self.db = db
        self.user_id = user_id
        self.org_id = org_id

    def calculate_cash_flow(
        self,
        period_type: str,
        start_date: date,
        end_date: date,
        method: str = "indirect",
        company_name: str = None,
        cnpj: str = None,
    ) -> CashFlow:
        """
        Calcula o Fluxo de Caixa

        Args:
            period_type: Tipo de período ("day", "week", "month", "year", "custom")
            start_date: Data inicial
            end_date: Data final
            method: Método de cálculo ("direct" ou "indirect")
            company_name: Nome da empresa (opcional)
            cnpj: CNPJ da empresa (opcional)

        Returns:
            CashFlow object
        """

        if method == "direct":
            return self._calculate_direct_method(
                period_type, start_date, end_date, company_name, cnpj
            )
        else:
            return self._calculate_indirect_method(
                period_type, start_date, end_date, company_name, cnpj
            )

    def _calculate_direct_method(
        self,
        period_type: str,
        start_date: date,
        end_date: date,
        company_name: str,
        cnpj: str,
    ) -> CashFlow:
        """
        Método Direto: Mostra recebimentos e pagamentos reais
        """

        # Get all transactions in period
        transactions = self._get_transactions(start_date, end_date)

        # 1. OPERATING ACTIVITIES
        operating_inflows = self._aggregate_by_categories(
            transactions, self.OPERATING_INFLOW_CATEGORIES, transaction_type="income"
        )
        operating_outflows = self._aggregate_by_categories(
            transactions,
            self.OPERATING_OUTFLOW_CATEGORIES,
            transaction_type="expense",
        )

        operating_items = {
            "Recebimentos de clientes": operating_inflows,
            "Pagamentos a fornecedores e funcionários": -operating_outflows,
        }
        net_operating_cash = operating_inflows - operating_outflows

        operating_activities = CashFlowSection(
            section_name="Atividades Operacionais",
            line_items=operating_items,
            total=net_operating_cash,
        )

        # 2. INVESTING ACTIVITIES
        investing_inflows = self._aggregate_by_categories(
            transactions, self.INVESTING_INFLOW_CATEGORIES, transaction_type="income"
        )
        investing_outflows = self._aggregate_by_categories(
            transactions, self.INVESTING_OUTFLOW_CATEGORIES, transaction_type="expense"
        )

        investing_items = {
            "Recebimentos por venda de ativos": investing_inflows,
            "Pagamentos por aquisição de ativos": -investing_outflows,
        }
        net_investing_cash = investing_inflows - investing_outflows

        investing_activities = CashFlowSection(
            section_name="Atividades de Investimento",
            line_items=investing_items,
            total=net_investing_cash,
        )

        # 3. FINANCING ACTIVITIES
        financing_inflows = self._aggregate_by_categories(
            transactions, self.FINANCING_INFLOW_CATEGORIES, transaction_type="income"
        )
        financing_outflows = self._aggregate_by_categories(
            transactions,
            self.FINANCING_OUTFLOW_CATEGORIES,
            transaction_type="expense",
        )

        financing_items = {
            "Recebimentos de empréstimos e capital": financing_inflows,
            "Pagamentos de empréstimos e dividendos": -financing_outflows,
        }
        net_financing_cash = financing_inflows - financing_outflows

        financing_activities = CashFlowSection(
            section_name="Atividades de Financiamento",
            line_items=financing_items,
            total=net_financing_cash,
        )

        # TOTALS
        net_increase = net_operating_cash + net_investing_cash + net_financing_cash

        # Get cash positions
        cash_beginning = self._get_cash_balance(start_date)
        cash_ending = self._get_cash_balance(end_date)

        return CashFlow(
            company_name=company_name or "Empresa",
            cnpj=cnpj or "",
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            method="direct",
            operating_activities=operating_activities,
            investing_activities=investing_activities,
            financing_activities=financing_activities,
            net_cash_from_operations=net_operating_cash,
            net_cash_from_investments=net_investing_cash,
            net_cash_from_financing=net_financing_cash,
            net_increase_in_cash=net_increase,
            cash_beginning=cash_beginning,
            cash_ending=cash_ending,
        )

    def _calculate_indirect_method(
        self,
        period_type: str,
        start_date: date,
        end_date: date,
        company_name: str,
        cnpj: str,
    ) -> CashFlow:
        """
        Método Indireto: Parte do lucro líquido e ajusta

        Estrutura:
        1. Atividades Operacionais
           - Lucro Líquido
           - Ajustes: Depreciação, Variação de contas a receber, etc.
        2. Atividades de Investimento
        3. Atividades de Financiamento
        """
        from accounting import PeriodType, calculate_dre

        # Get transactions from documents (same source as DRE)
        transactions = self._get_transactions(start_date, end_date)

        # Calculate DRE for the period to extract net income
        dre = calculate_dre(
            transactions=self._get_all_transactions(),
            period_type=PeriodType(period_type) if period_type in ["day", "week", "month", "year"] else PeriodType.CUSTOM,
            start_date=start_date,
            end_date=end_date,
            company_name=company_name,
            cnpj=cnpj,
        )

        # 1. OPERATING ACTIVITIES (Indirect Method)
        lucro_liquido = dre.lucro_liquido

        # Add back non-cash expenses
        depreciation_amortization = dre.total_deprec_amort

        operating_items = {
            "Lucro Líquido do Período": lucro_liquido,
            "(+) Depreciação e Amortização": depreciation_amortization,
        }

        net_operating_cash = lucro_liquido + depreciation_amortization

        operating_activities = CashFlowSection(
            section_name="Atividades Operacionais",
            line_items=operating_items,
            total=net_operating_cash,
        )

        # 2. INVESTING ACTIVITIES (same as direct method)
        investing_inflows = self._aggregate_by_categories(
            transactions, self.INVESTING_INFLOW_CATEGORIES, transaction_type="income"
        )
        investing_outflows = self._aggregate_by_categories(
            transactions, self.INVESTING_OUTFLOW_CATEGORIES, transaction_type="expense"
        )

        investing_items = {
            "Recebimentos por venda de ativos": investing_inflows,
            "Pagamentos por aquisição de ativos": -investing_outflows,
        }
        net_investing_cash = investing_inflows - investing_outflows

        investing_activities = CashFlowSection(
            section_name="Atividades de Investimento",
            line_items=investing_items,
            total=net_investing_cash,
        )

        # 3. FINANCING ACTIVITIES (same as direct method)
        financing_inflows = self._aggregate_by_categories(
            transactions, self.FINANCING_INFLOW_CATEGORIES, transaction_type="income"
        )
        financing_outflows = self._aggregate_by_categories(
            transactions,
            self.FINANCING_OUTFLOW_CATEGORIES,
            transaction_type="expense",
        )

        financing_items = {
            "Recebimentos de empréstimos e capital": financing_inflows,
            "Pagamentos de empréstimos e dividendos": -financing_outflows,
        }
        net_financing_cash = financing_inflows - financing_outflows

        financing_activities = CashFlowSection(
            section_name="Atividades de Financiamento",
            line_items=financing_items,
            total=net_financing_cash,
        )

        # TOTALS
        net_increase = net_operating_cash + net_investing_cash + net_financing_cash

        # Get cash positions
        cash_beginning = self._get_cash_balance(start_date)
        cash_ending = self._get_cash_balance(end_date)

        return CashFlow(
            company_name=company_name or "Empresa",
            cnpj=cnpj or "",
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            method="indirect",
            operating_activities=operating_activities,
            investing_activities=investing_activities,
            financing_activities=financing_activities,
            net_cash_from_operations=net_operating_cash,
            net_cash_from_investments=net_investing_cash,
            net_cash_from_financing=net_financing_cash,
            net_increase_in_cash=net_increase,
            cash_beginning=cash_beginning,
            cash_ending=cash_ending,
        )

    def _get_all_transactions(self) -> List[dict]:
        """Get ALL transactions from completed documents, expanding multi-row ledgers."""
        from models import FinancialDocument as FinancialDocumentModel

        from sqlalchemy import or_
        doc_filter = [
            Document.status == DocumentStatus.COMPLETED,
            Document.extracted_data_json.isnot(None),
        ]
        if self.org_id:
            doc_filter.append(or_(
                Document.organization_id == self.org_id,
                (Document.organization_id.is_(None)) & (Document.user_id == self.user_id),
            ))
        else:
            doc_filter.append(Document.user_id == self.user_id)

        documents = self.db.query(Document).filter(*doc_filter).all()

        transactions = []
        for doc in documents:
            try:
                data_dict = json.loads(doc.extracted_data_json)
                extracted = FinancialDocumentModel(**data_dict)

                # Check for inner transactions (multi-row documents like Excel ledgers)
                inner_txns = data_dict.get("transactions")
                if inner_txns and isinstance(inner_txns, list) and len(inner_txns) > 0:
                    for txn in inner_txns:
                        amount = txn.get("amount", 0)
                        if amount is None:
                            amount = 0
                        transactions.append({
                            "date": txn.get("date"),
                            "amount": amount,
                            "category": txn.get("category") or "uncategorized",
                            "transaction_type": txn.get("transaction_type") or extracted.transaction_type,
                            "description": txn.get("description") or "",
                            "document_id": doc.id,
                        })
                else:
                    transactions.append({
                        "date": extracted.issue_date,
                        "amount": extracted.total_amount,
                        "category": extracted.category or "uncategorized",
                        "transaction_type": extracted.transaction_type,
                        "description": extracted.document_number or "",
                        "document_id": doc.id,
                    })
            except Exception:
                continue

        return transactions

    def _get_transactions(
        self, start_date: date, end_date: date
    ) -> List[dict]:
        """Get financial transactions from documents within a date range"""
        all_transactions = self._get_all_transactions()

        filtered = []
        for txn in all_transactions:
            t_date = txn.get("date")
            if t_date is None:
                continue

            if isinstance(t_date, str):
                try:
                    t_date = datetime.fromisoformat(t_date).date()
                except (ValueError, TypeError):
                    continue
            elif isinstance(t_date, datetime):
                t_date = t_date.date()

            if start_date <= t_date <= end_date:
                filtered.append(txn)

        return filtered

    def _aggregate_by_categories(
        self,
        transactions: List,
        categories: set,
        transaction_type: str = None,
    ) -> Decimal:
        """Aggregate transaction amounts by categories"""
        total = Decimal("0")

        from accounting import is_income_type
        for txn in transactions:
            if txn.get("category") in categories:
                if transaction_type is None:
                    match = True
                elif transaction_type == "income":
                    match = is_income_type(txn.get("transaction_type", ""))
                elif transaction_type == "expense":
                    match = not is_income_type(txn.get("transaction_type", ""))
                else:
                    match = txn.get("transaction_type") == transaction_type
                if match:
                    amount = txn.get("amount", 0)
                    if amount is not None:
                        total += Decimal(str(amount))

        return total

    def _get_cash_balance(self, reference_date: date) -> Decimal:
        """
        Get cash balance at a specific date

        Simplified approach: sum all cash transactions up to date,
        plus initial balance from the organization's questionnaire data.
        """
        transactions = self._get_transactions(date(2000, 1, 1), reference_date)

        cash_balance = Decimal("0")

        for txn in transactions:
            category = txn.get("category", "")
            txn_type = txn.get("transaction_type", "")

            # Cash accounts
            if category in ["cash", "bank_account", "petty_cash"]:
                amount = Decimal(str(txn.get("amount", 0)))
                if txn_type in ("income", "receita"):
                    cash_balance += amount
                else:
                    cash_balance -= amount

        # Add initial balance from org questionnaire
        initial = self._get_initial_balance(reference_date)
        if initial:
            cash_balance += Decimal(str(initial.cash_and_equivalents or 0))
            # Add bank account balances
            if initial.bank_account_balances:
                for entry in initial.bank_account_balances:
                    cash_balance += Decimal(str(entry.get("balance", 0)))

        return cash_balance

    def _get_initial_balance(self, reference_date: date):
        """
        Load the initial balance for this organization.
        Returns the most recent completed initial balance record whose
        reference_date is <= the given reference_date.
        """
        if not self.org_id:
            return None

        from database import OrgInitialBalance

        initial = (
            self.db.query(OrgInitialBalance)
            .filter(
                OrgInitialBalance.organization_id == self.org_id,
                OrgInitialBalance.is_completed == True,
                OrgInitialBalance.reference_date <= reference_date,
            )
            .order_by(OrgInitialBalance.reference_date.desc())
            .first()
        )

        return initial
