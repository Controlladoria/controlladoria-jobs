"""
DRE (Income Statement) Pydantic Models
Brazilian accounting standard models

V2 Changes (Item 1A - partner feedback):
- Added Margem de Contribuição (Contribution Margin)
- Separated variable vs fixed costs
- AV% calculated vs Receita Bruta (not Receita Líquida)
- New flow: Revenue -> Deductions -> Net -> Variable Costs -> Contribution Margin
  -> Fixed Costs -> EBITDA -> D&A -> EBIT -> Financial -> LAIR -> Taxes -> Net Profit
- Legacy fields preserved for backward compatibility
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PeriodType(str, Enum):
    """Period types for DRE calculation"""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    CUSTOM = "custom"


class DRELine(BaseModel):
    """Individual line item in DRE"""

    code: str = Field(..., description="Line code (e.g., '1.1', '2.1')")
    description: str = Field(..., description="Line description")
    amount: Decimal = Field(default=Decimal("0"), description="Line amount")
    percentage_revenue: Optional[float] = Field(None, description="AV% of gross revenue")
    is_subtotal: bool = Field(
        default=False, description="Whether this is a subtotal line"
    )
    is_total: bool = Field(default=False, description="Whether this is a total line")
    level: int = Field(default=1, description="Indentation level (1-3)")

    class Config:
        json_encoders = {Decimal: lambda v: float(v)}


class DRESection(BaseModel):
    """Section in DRE (e.g., Revenue, Expenses)"""

    title: str = Field(..., description="Section title")
    lines: List[DRELine] = Field(
        default_factory=list, description="Line items in section"
    )
    subtotal: Optional[DRELine] = Field(None, description="Section subtotal")


class FinancialRatios(BaseModel):
    """Financial performance ratios - V2: all calculated vs Receita Bruta"""

    # V2 ratios (vs Receita Bruta)
    margem_contribuicao: float = Field(default=0.0, description="Contribution margin % (vs Receita Bruta)")
    margem_ebitda: float = Field(default=0.0, description="EBITDA margin % (vs Receita Bruta)")
    margem_operacional: float = Field(default=0.0, description="Operating margin % (vs Receita Bruta)")
    margem_liquida: float = Field(default=0.0, description="Net margin % (vs Receita Bruta)")

    # Legacy ratio (kept for backward compat)
    margem_bruta: float = Field(default=0.0, description="[Legacy] Gross margin % = margem_contribuicao")

    # Additional ratios
    roe: Optional[float] = Field(None, description="Return on Equity %")
    roa: Optional[float] = Field(None, description="Return on Assets %")

    class Config:
        json_encoders = {float: lambda v: round(v, 2)}


class DRE(BaseModel):
    """
    Complete DRE (Demonstração do Resultado do Exercício)
    Brazilian Income Statement - V2 Structure

    V2 Flow (matching ControlladorIA template):
      Receita Bruta
      (-) Deduções
      = Receita Líquida
      (-) Custos Variáveis
      = Margem de Contribuição
      (-) Custos Fixos + Despesas Fixas
      = EBITDA
      (-) Depreciação e Amortização
      = Resultado Operacional (EBIT)
      (+/-) Resultado Financeiro
      = Resultado Antes Impostos (LAIR)
      (-) Impostos sobre Lucro
      = Lucro Líquido
    """

    # Period information
    period_type: PeriodType
    start_date: date
    end_date: date
    company_name: Optional[str] = None
    cnpj: Optional[str] = None

    # ========================================================================
    # V2 DRE Line Items
    # ========================================================================

    # Section 1: Receita Bruta
    receita_bruta: Decimal = Field(default=Decimal("0"), description="Gross revenue")

    # Section 2: (-) Deduções
    devolucoes: Decimal = Field(default=Decimal("0"), description="Returns and cancellations")
    impostos_sobre_vendas: Decimal = Field(default=Decimal("0"), description="Sales taxes")
    descontos: Decimal = Field(default=Decimal("0"), description="Discounts granted")
    total_deducoes: Decimal = Field(default=Decimal("0"), description="Total deductions")

    # Section 3: = Receita Líquida
    receita_liquida: Decimal = Field(default=Decimal("0"), description="Net revenue")

    # Section 4: (-) Custos Variáveis (V2 - replaces old "Custos Operacionais")
    custos_variaveis_cmv: Decimal = Field(default=Decimal("0"), description="CMV - Cost of goods sold (variable)")
    custos_variaveis_csp: Decimal = Field(default=Decimal("0"), description="CSP - Cost of services (variable)")
    custos_variaveis_outros: Decimal = Field(default=Decimal("0"), description="Other variable costs")
    total_custos_variaveis: Decimal = Field(default=Decimal("0"), description="Total variable costs")

    # Section 5: = Margem de Contribuição (V2 - NEW, replaces Lucro Bruto)
    margem_contribuicao: Decimal = Field(default=Decimal("0"), description="Contribution margin")

    # Section 6: (-) Custos Fixos + Despesas Fixas (V2 - separated from variable)
    custos_fixos_producao: Decimal = Field(default=Decimal("0"), description="Fixed production costs")
    despesas_administrativas: Decimal = Field(default=Decimal("0"), description="Administrative expenses (fixed)")
    despesas_vendas: Decimal = Field(default=Decimal("0"), description="Sales/commercial expenses (fixed)")
    outras_despesas: Decimal = Field(default=Decimal("0"), description="Other operating expenses")
    total_custos_fixos: Decimal = Field(default=Decimal("0"), description="Total fixed costs + expenses")

    # Section 7: = EBITDA
    ebitda: Decimal = Field(default=Decimal("0"), description="EBITDA")

    # Section 8: (-) Depreciação e Amortização
    depreciacao: Decimal = Field(default=Decimal("0"), description="Depreciation")
    amortizacao: Decimal = Field(default=Decimal("0"), description="Amortization")
    total_deprec_amort: Decimal = Field(default=Decimal("0"), description="Total depreciation & amortization")

    # Section 9: = Resultado Operacional (EBIT)
    resultado_operacional: Decimal = Field(default=Decimal("0"), description="Operating result (EBIT)")

    # Section 10: (+/-) Resultado Financeiro
    receitas_financeiras: Decimal = Field(default=Decimal("0"), description="Financial revenues")
    despesas_financeiras: Decimal = Field(default=Decimal("0"), description="Financial expenses")
    resultado_financeiro: Decimal = Field(default=Decimal("0"), description="Net financial result")

    # Section 11: = Resultado Antes dos Impostos (LAIR)
    resultado_antes_impostos: Decimal = Field(default=Decimal("0"), description="Result before taxes (LAIR)")

    # Section 12: (-) Impostos sobre o Lucro
    irpj: Decimal = Field(default=Decimal("0"), description="Corporate income tax")
    csll: Decimal = Field(default=Decimal("0"), description="Social contribution on net profit")
    total_impostos_lucro: Decimal = Field(default=Decimal("0"), description="Total taxes on profit")

    # Section 13: = Lucro Líquido
    lucro_liquido: Decimal = Field(default=Decimal("0"), description="Net profit")

    # ========================================================================
    # Legacy fields (backward compatibility - still populated by calculator)
    # ========================================================================
    total_custos: Decimal = Field(default=Decimal("0"), description="[Legacy] = total_custos_variaveis")
    lucro_bruto: Decimal = Field(default=Decimal("0"), description="[Legacy] = margem_contribuicao")
    total_despesas_operacionais: Decimal = Field(default=Decimal("0"), description="[Legacy] = total_custos_fixos")
    custo_mercadorias_vendidas: Decimal = Field(default=Decimal("0"), description="[Legacy] = custos_variaveis_cmv")
    custo_servicos_prestados: Decimal = Field(default=Decimal("0"), description="[Legacy] = custos_variaveis_csp")

    # ========================================================================
    # Ratios and metadata
    # ========================================================================
    ratios: FinancialRatios = Field(default_factory=FinancialRatios)
    detailed_lines: List[DRELine] = Field(default_factory=list, description="All DRE line items")
    transaction_count: int = Field(default=0, description="Total transactions processed")
    uncategorized_count: int = Field(default=0, description="Uncategorized transactions")
    uncategorized_amount: Decimal = Field(default=Decimal("0"), description="Uncategorized amount")

    class Config:
        json_encoders = {Decimal: lambda v: float(v), date: lambda v: v.isoformat()}

    def calculate_ratios(self):
        """Calculate all financial ratios - V2: vs Receita Bruta"""
        if self.receita_bruta == 0:
            self.ratios = FinancialRatios()
            return

        gross_revenue = float(self.receita_bruta)

        self.ratios = FinancialRatios(
            margem_contribuicao=(float(self.margem_contribuicao) / gross_revenue) * 100,
            margem_ebitda=(float(self.ebitda) / gross_revenue) * 100,
            margem_operacional=(float(self.resultado_operacional) / gross_revenue) * 100,
            margem_liquida=(float(self.lucro_liquido) / gross_revenue) * 100,
            # Legacy: margem_bruta = margem_contribuicao for backward compat
            margem_bruta=(float(self.margem_contribuicao) / gross_revenue) * 100,
        )

    def to_dict_formatted(self) -> dict:
        """Return formatted dict for display (with BRL formatting)"""

        def format_brl(value: Decimal) -> str:
            """Format as Brazilian Real with negative in parentheses"""
            abs_value = abs(value)
            formatted = (
                f"{abs_value:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
            if value < 0:
                return f"(R$ {formatted})"
            return f"R$ {formatted}"

        return {
            "period": f"{self.start_date.strftime('%d/%m/%Y')} a {self.end_date.strftime('%d/%m/%Y')}",
            "period_type": self.period_type.value,
            "company_name": self.company_name or "Empresa",
            "cnpj": self.cnpj or "",
            "receita_bruta": format_brl(self.receita_bruta),
            "total_deducoes": format_brl(self.total_deducoes),
            "receita_liquida": format_brl(self.receita_liquida),
            # V2 fields
            "total_custos_variaveis": format_brl(self.total_custos_variaveis),
            "margem_contribuicao": format_brl(self.margem_contribuicao),
            "total_custos_fixos": format_brl(self.total_custos_fixos),
            "ebitda": format_brl(self.ebitda),
            "total_deprec_amort": format_brl(self.total_deprec_amort),
            "resultado_operacional": format_brl(self.resultado_operacional),
            "resultado_financeiro": format_brl(self.resultado_financeiro),
            "resultado_antes_impostos": format_brl(self.resultado_antes_impostos),
            "total_impostos_lucro": format_brl(self.total_impostos_lucro),
            "lucro_liquido": format_brl(self.lucro_liquido),
            # Legacy fields
            "total_custos": format_brl(self.total_custos),
            "lucro_bruto": format_brl(self.lucro_bruto),
            "total_despesas_operacionais": format_brl(self.total_despesas_operacionais),
            "ratios": {
                "margem_contribuicao": f"{self.ratios.margem_contribuicao:.1f}%",
                "margem_ebitda": f"{self.ratios.margem_ebitda:.1f}%",
                "margem_operacional": f"{self.ratios.margem_operacional:.1f}%",
                "margem_liquida": f"{self.ratios.margem_liquida:.1f}%",
                # Legacy
                "margem_bruta": f"{self.ratios.margem_bruta:.1f}%",
            },
        }


class DREComparisonPeriod(BaseModel):
    """DRE data for a single period in comparison view"""

    period_label: str
    start_date: date
    end_date: date
    dre: DRE


class DREComparison(BaseModel):
    """Comparative DRE across multiple periods"""

    periods: List[DREComparisonPeriod]
    variance_analysis: List[dict] = Field(
        default_factory=list, description="Period-over-period variance"
    )

    class Config:
        json_encoders = {date: lambda v: v.isoformat()}
