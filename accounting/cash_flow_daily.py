"""
Daily Cash Flow (Fluxo de Caixa Diário) - V2

Matches the ControlladorIA template structure:
- Section A: Bank-by-bank daily tracking
  (Saldo Inicial -> Entradas -> Saídas -> Saldo Final per bank)
- Section B: DRE-like daily breakdown
  (Revenue -> Deductions -> Net -> Variable Costs -> Contribution Margin ->
   Fixed Costs sub-groups -> Operating Result -> Non-Operating -> Net Result -> Accumulated)

Daily granularity with monthly totals.
Rolling balance: today's opening = yesterday's closing.

NOTE: This module is SEPARATE from the CPC 03 DFC (cash_flow.py / cash_flow_calculator.py).
The CPC 03 implementation remains intact for compliance reporting.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from .categories import (
    DRE_CATEGORIES,
    DRELineType,
    resolve_category_name,
)


@dataclass
class DailyBankEntry:
    """Single day's cash flow for one bank account"""

    bank_name: str
    day: date
    opening_balance: Decimal = Decimal("0")
    total_inflows: Decimal = Decimal("0")
    total_outflows: Decimal = Decimal("0")
    closing_balance: Decimal = Decimal("0")

    def calculate_closing(self):
        self.closing_balance = self.opening_balance + self.total_inflows - self.total_outflows


@dataclass
class DailyDREEntry:
    """Single day's DRE-like breakdown"""

    day: date

    # Revenue
    receita_bruta: Decimal = Decimal("0")

    # Deductions
    total_deducoes: Decimal = Decimal("0")

    # Net Revenue
    receita_liquida: Decimal = Decimal("0")

    # Variable Costs
    total_custos_variaveis: Decimal = Decimal("0")

    # Contribution Margin
    margem_contribuicao: Decimal = Decimal("0")

    # Fixed Costs sub-groups
    custos_fixos_administrativos: Decimal = Decimal("0")
    custos_fixos_comerciais: Decimal = Decimal("0")
    custos_fixos_producao: Decimal = Decimal("0")
    outras_despesas_fixas: Decimal = Decimal("0")
    total_custos_fixos: Decimal = Decimal("0")

    # Operating Result
    resultado_operacional: Decimal = Decimal("0")

    # Non-Operating
    receitas_nao_operacionais: Decimal = Decimal("0")
    despesas_nao_operacionais: Decimal = Decimal("0")
    resultado_nao_operacional: Decimal = Decimal("0")

    # Net Result
    resultado_liquido: Decimal = Decimal("0")

    # Accumulated
    resultado_acumulado: Decimal = Decimal("0")

    def calculate(self):
        """Calculate derived fields"""
        self.receita_liquida = self.receita_bruta - self.total_deducoes
        self.margem_contribuicao = self.receita_liquida - self.total_custos_variaveis
        self.total_custos_fixos = (
            self.custos_fixos_administrativos
            + self.custos_fixos_comerciais
            + self.custos_fixos_producao
            + self.outras_despesas_fixas
        )
        self.resultado_operacional = self.margem_contribuicao - self.total_custos_fixos
        self.resultado_nao_operacional = (
            self.receitas_nao_operacionais - self.despesas_nao_operacionais
        )
        self.resultado_liquido = self.resultado_operacional + self.resultado_nao_operacional


@dataclass
class DailyCashFlow:
    """Complete Daily Cash Flow report"""

    # Header
    company_name: Optional[str] = None
    cnpj: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Section A: Bank-by-bank daily tracking
    bank_entries: Dict[str, List[DailyBankEntry]] = field(default_factory=dict)

    # Section B: DRE-like daily breakdown
    daily_dre_entries: List[DailyDREEntry] = field(default_factory=list)

    # Monthly summary
    monthly_totals: Dict[str, DailyDREEntry] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""

        def decimal_to_float(val):
            return float(val) if val else 0.0

        bank_data = {}
        for bank_name, entries in self.bank_entries.items():
            bank_data[bank_name] = [
                {
                    "day": e.day.isoformat(),
                    "opening_balance": decimal_to_float(e.opening_balance),
                    "total_inflows": decimal_to_float(e.total_inflows),
                    "total_outflows": decimal_to_float(e.total_outflows),
                    "closing_balance": decimal_to_float(e.closing_balance),
                }
                for e in entries
            ]

        daily_data = [
            {
                "day": e.day.isoformat(),
                "receita_bruta": decimal_to_float(e.receita_bruta),
                "total_deducoes": decimal_to_float(e.total_deducoes),
                "receita_liquida": decimal_to_float(e.receita_liquida),
                "total_custos_variaveis": decimal_to_float(e.total_custos_variaveis),
                "margem_contribuicao": decimal_to_float(e.margem_contribuicao),
                "custos_fixos_administrativos": decimal_to_float(e.custos_fixos_administrativos),
                "custos_fixos_comerciais": decimal_to_float(e.custos_fixos_comerciais),
                "custos_fixos_producao": decimal_to_float(e.custos_fixos_producao),
                "outras_despesas_fixas": decimal_to_float(e.outras_despesas_fixas),
                "total_custos_fixos": decimal_to_float(e.total_custos_fixos),
                "resultado_operacional": decimal_to_float(e.resultado_operacional),
                "receitas_nao_operacionais": decimal_to_float(e.receitas_nao_operacionais),
                "despesas_nao_operacionais": decimal_to_float(e.despesas_nao_operacionais),
                "resultado_nao_operacional": decimal_to_float(e.resultado_nao_operacional),
                "resultado_liquido": decimal_to_float(e.resultado_liquido),
                "resultado_acumulado": decimal_to_float(e.resultado_acumulado),
            }
            for e in self.daily_dre_entries
        ]

        monthly_data = {}
        for month_key, entry in self.monthly_totals.items():
            monthly_data[month_key] = {
                "receita_bruta": decimal_to_float(entry.receita_bruta),
                "margem_contribuicao": decimal_to_float(entry.margem_contribuicao),
                "resultado_operacional": decimal_to_float(entry.resultado_operacional),
                "resultado_liquido": decimal_to_float(entry.resultado_liquido),
            }

        return {
            "company_name": self.company_name,
            "cnpj": self.cnpj,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "bank_entries": bank_data,
            "daily_dre": daily_data,
            "monthly_totals": monthly_data,
        }


# ============================================================================
# Category classification helpers
# ============================================================================

# Build classification lookup from DRE_CATEGORIES using DRELineType
_LINE_TYPE_TO_BUCKET = {
    DRELineType.REVENUE: "receita_bruta",
    DRELineType.DEDUCTION: "deducao",
    DRELineType.VARIABLE_COST: "custo_variavel",
    DRELineType.FIXED_EXPENSE_ADMIN: "custo_fixo_admin",
    DRELineType.FIXED_EXPENSE_COMMERCIAL: "custo_fixo_comercial",
    DRELineType.OTHER_EXPENSE: "outra_despesa_fixa",
    DRELineType.NON_OPERATING_REVENUE: "receita_nao_operacional",
    DRELineType.TAX_ON_PROFIT: "despesa_nao_operacional",
    DRELineType.DEPRECIATION: "custo_fixo_producao",
    DRELineType.FINANCIAL_REVENUE: "receita_nao_operacional",
    DRELineType.FINANCIAL_EXPENSE: "despesa_nao_operacional",
    DRELineType.OTHER_REVENUE: "receita_nao_operacional",
}

# Pre-build lookup: category_name -> bucket
_CATEGORY_BUCKET_MAP: Dict[str, str] = {}
for _cat_name, _cat_info in DRE_CATEGORIES.items():
    _lt = _cat_info.get("line_type")
    if _lt and _lt in _LINE_TYPE_TO_BUCKET:
        _CATEGORY_BUCKET_MAP[_cat_name] = _LINE_TYPE_TO_BUCKET[_lt]


def _classify_transaction(category: str) -> str:
    """Classify a transaction category into a daily cash flow bucket.

    Uses DRELineType from the V2 categories to determine the bucket.
    Falls back to 'other' if category is unknown.
    """
    cat = resolve_category_name(category)

    bucket = _CATEGORY_BUCKET_MAP.get(cat)
    if bucket:
        return bucket

    return "other"


# ============================================================================
# Calculator
# ============================================================================


class DailyCashFlowCalculator:
    """
    Calculate daily cash flow from transaction data.

    Transactions are dicts with keys:
      - date: str (ISO format) or date object
      - amount: float or Decimal
      - category: str
      - transaction_type: "income" | "expense"
      - description: str (optional)
      - bank_account: str (optional, for Section A)
    """

    def calculate(
        self,
        transactions: List[dict],
        start_date: date,
        end_date: date,
        company_name: Optional[str] = None,
        cnpj: Optional[str] = None,
        initial_bank_balances: Optional[Dict[str, Decimal]] = None,
    ) -> DailyCashFlow:
        """
        Calculate daily cash flow for a date range.

        Args:
            transactions: List of transaction dicts
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            company_name: Company name for header
            cnpj: CNPJ for header
            initial_bank_balances: Optional dict of {bank_name: opening_balance}

        Returns:
            DailyCashFlow object
        """
        result = DailyCashFlow(
            company_name=company_name,
            cnpj=cnpj,
            start_date=start_date,
            end_date=end_date,
        )

        # Group transactions by day
        daily_txns = self._group_by_day(transactions, start_date, end_date)

        # ================================================================
        # Section B: DRE-like daily breakdown
        # ================================================================
        accumulated = Decimal("0")

        for current_date in self._date_range(start_date, end_date):
            entry = DailyDREEntry(day=current_date)
            day_key = current_date.isoformat()

            if day_key in daily_txns:
                for txn in daily_txns[day_key]:
                    amount = Decimal(str(txn.get("amount", 0)))
                    category = txn.get("category", "")
                    txn_type = txn.get("transaction_type", "expense")

                    bucket = _classify_transaction(category)

                    if bucket == "receita_bruta":
                        entry.receita_bruta += amount
                    elif bucket == "deducao":
                        entry.total_deducoes += amount
                    elif bucket == "custo_variavel":
                        entry.total_custos_variaveis += amount
                    elif bucket == "custo_fixo_admin":
                        entry.custos_fixos_administrativos += amount
                    elif bucket == "custo_fixo_comercial":
                        entry.custos_fixos_comerciais += amount
                    elif bucket == "custo_fixo_producao":
                        entry.custos_fixos_producao += amount
                    elif bucket == "outra_despesa_fixa":
                        entry.outras_despesas_fixas += amount
                    elif bucket == "receita_nao_operacional":
                        entry.receitas_nao_operacionais += amount
                    elif bucket == "despesa_nao_operacional":
                        entry.despesas_nao_operacionais += amount
                    else:
                        # Unclassified: use transaction_type to decide
                        if txn_type in ("income", "receita"):
                            entry.receita_bruta += amount
                        else:
                            entry.outras_despesas_fixas += amount

            entry.calculate()
            accumulated += entry.resultado_liquido
            entry.resultado_acumulado = accumulated

            result.daily_dre_entries.append(entry)

        # ================================================================
        # Section A: Bank-by-bank daily tracking
        # ================================================================
        bank_balances = dict(initial_bank_balances or {})
        bank_daily = {}  # {bank_name: {day_key: DailyBankEntry}}

        for current_date in self._date_range(start_date, end_date):
            day_key = current_date.isoformat()

            if day_key in daily_txns:
                for txn in daily_txns[day_key]:
                    bank = txn.get("bank_account", "Principal")
                    amount = Decimal(str(txn.get("amount", 0)))
                    txn_type = txn.get("transaction_type", "expense")

                    if bank not in bank_daily:
                        bank_daily[bank] = {}

                    if day_key not in bank_daily[bank]:
                        opening = bank_balances.get(bank, Decimal("0"))
                        bank_daily[bank][day_key] = DailyBankEntry(
                            bank_name=bank,
                            day=current_date,
                            opening_balance=opening,
                        )

                    from accounting import is_income_type
                    if is_income_type(txn_type):
                        bank_daily[bank][day_key].total_inflows += amount
                    else:
                        bank_daily[bank][day_key].total_outflows += amount

            # Calculate closing balances and roll forward
            for bank in bank_daily:
                if day_key in bank_daily[bank]:
                    entry = bank_daily[bank][day_key]
                    entry.calculate_closing()
                    bank_balances[bank] = entry.closing_balance

        # Convert to result format
        for bank_name, days in bank_daily.items():
            result.bank_entries[bank_name] = sorted(
                days.values(), key=lambda e: e.day
            )

        # ================================================================
        # Monthly totals
        # ================================================================
        self._calculate_monthly_totals(result)

        return result

    def _group_by_day(
        self, transactions: List[dict], start_date: date, end_date: date
    ) -> Dict[str, List[dict]]:
        """Group transactions by day (ISO date string key)"""
        grouped: Dict[str, List[dict]] = {}

        for txn in transactions:
            txn_date = txn.get("date")
            if txn_date is None:
                continue

            # Convert to date if needed
            if isinstance(txn_date, str):
                try:
                    txn_date = date.fromisoformat(txn_date)
                except ValueError:
                    try:
                        txn_date = datetime.fromisoformat(txn_date).date()
                    except ValueError:
                        continue
            elif isinstance(txn_date, datetime):
                txn_date = txn_date.date()

            # Filter to date range
            if txn_date < start_date or txn_date > end_date:
                continue

            day_key = txn_date.isoformat()
            if day_key not in grouped:
                grouped[day_key] = []
            grouped[day_key].append(txn)

        return grouped

    def _date_range(self, start: date, end: date):
        """Yield dates from start to end (inclusive)"""
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)

    def _calculate_monthly_totals(self, result: DailyCashFlow):
        """Aggregate daily entries into monthly totals"""
        monthly: Dict[str, DailyDREEntry] = {}

        for entry in result.daily_dre_entries:
            month_key = entry.day.strftime("%Y-%m")

            if month_key not in monthly:
                monthly[month_key] = DailyDREEntry(
                    day=entry.day.replace(day=1)  # First day of month
                )

            m = monthly[month_key]
            m.receita_bruta += entry.receita_bruta
            m.total_deducoes += entry.total_deducoes
            m.total_custos_variaveis += entry.total_custos_variaveis
            m.custos_fixos_administrativos += entry.custos_fixos_administrativos
            m.custos_fixos_comerciais += entry.custos_fixos_comerciais
            m.custos_fixos_producao += entry.custos_fixos_producao
            m.outras_despesas_fixas += entry.outras_despesas_fixas
            m.receitas_nao_operacionais += entry.receitas_nao_operacionais
            m.despesas_nao_operacionais += entry.despesas_nao_operacionais

        # Calculate derived fields for each month
        for month_key, m in monthly.items():
            m.calculate()

        result.monthly_totals = monthly
