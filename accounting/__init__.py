"""
Brazilian Accounting Module
Implements DRE (Demonstração do Resultado do Exercício), Balance Sheet (Balanço Patrimonial),
and double-entry bookkeeping with financial reporting
"""

from .accounting_engine import AccountingEngine
from .balance_sheet_calculator import (
    BalanceSheet,
    BalanceSheetCalculator,
    BalanceSheetLine,
    calculate_balance_sheet,
)
from .balance_sheet_exports import (
    export_balance_sheet_to_csv,
    export_balance_sheet_to_excel,
    export_balance_sheet_to_pdf,
)
from .categories import (
    DRE_CATEGORIES,
    CATEGORY_ALIASES,
    VARIABLE_COST_CATEGORIES,
    FIXED_COST_CATEGORIES,
    get_all_categories,
    get_dre_category,
    get_categories_by_behavior,
    get_categories_by_dre_group,
    resolve_category_name,
)
# Transaction type helpers
INCOME_TYPES = {"receita", "income"}
VALID_TRANSACTION_TYPES = {"receita", "despesa", "custo", "investimento", "perda"}

def is_income_type(transaction_type: str) -> bool:
    """Check if a transaction type represents income (inflow)."""
    return (transaction_type or "").lower().strip() in INCOME_TYPES

from .chart_of_accounts import AccountNature, AccountType, BrazilianChartOfAccounts
from .dre_calculator import DRECalculator, calculate_dre, get_period_dates
from .dre_exports import export_dre_to_csv, export_dre_to_excel, export_dre_to_pdf
from .cash_flow_daily import DailyCashFlow, DailyCashFlowCalculator, DailyDREEntry
from .dre_models import DRE, DRELine, DRESection, FinancialRatios, PeriodType

__all__ = [
    # Categories
    "DRE_CATEGORIES",
    "CATEGORY_ALIASES",
    "VARIABLE_COST_CATEGORIES",
    "FIXED_COST_CATEGORIES",
    "get_dre_category",
    "get_all_categories",
    "get_categories_by_behavior",
    "get_categories_by_dre_group",
    "resolve_category_name",
    # DRE Calculator
    "DRECalculator",
    "calculate_dre",
    "get_period_dates",
    # DRE Models
    "DRE",
    "DRELine",
    "DRESection",
    "FinancialRatios",
    "PeriodType",
    # DRE Exports
    "export_dre_to_pdf",
    "export_dre_to_excel",
    "export_dre_to_csv",
    # Chart of Accounts
    "BrazilianChartOfAccounts",
    "AccountType",
    "AccountNature",
    # Accounting Engine
    "AccountingEngine",
    # Balance Sheet Calculator
    "BalanceSheet",
    "BalanceSheetLine",
    "BalanceSheetCalculator",
    "calculate_balance_sheet",
    # Balance Sheet Exports
    "export_balance_sheet_to_pdf",
    "export_balance_sheet_to_excel",
    "export_balance_sheet_to_csv",
    # Daily Cash Flow
    "DailyCashFlow",
    "DailyCashFlowCalculator",
    "DailyDREEntry",
    # Transaction type helpers
    "is_income_type",
    "INCOME_TYPES",
    "VALID_TRANSACTION_TYPES",
]
