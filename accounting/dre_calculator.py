"""
DRE Calculator - V2
Calculates Brazilian Income Statement from transactions

V2 Changes (Item 1A - partner feedback):
- Variable vs Fixed cost separation
- Margem de Contribuição replaces Lucro Bruto as primary metric
- AV% calculated vs Receita Bruta (not Receita Líquida)
- New flow: Revenue -> Deductions -> Net -> Variable Costs -> Contribution Margin
  -> Fixed Costs -> EBITDA -> D&A -> EBIT -> Financial -> LAIR -> Taxes -> Net Profit
- Legacy fields preserved for backward compatibility
"""

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from .categories import (
    ADMIN_EXPENSE_CATEGORIES,
    COST_CATEGORIES,
    DEDUCTION_CATEGORIES,
    DEPRECIATION_CATEGORIES,
    DRE_CATEGORIES,
    FINANCIAL_EXPENSE_CATEGORIES,
    FINANCIAL_REVENUE_CATEGORIES,
    FIXED_COST_CATEGORIES,
    FIXED_EXPENSE_ADMIN_CATEGORIES,
    FIXED_EXPENSE_COMMERCIAL_CATEGORIES,
    NON_OPERATING_REVENUE_CATEGORIES,
    OTHER_EXPENSE_CATEGORIES,
    REVENUE_CATEGORIES,
    SALES_EXPENSE_CATEGORIES,
    TAX_ON_PROFIT_CATEGORIES,
    VARIABLE_COST_CATEGORIES,
    get_dre_category,
    resolve_category_name,
)
from .dre_models import DRE, DRELine, FinancialRatios, PeriodType


class DRECalculator:
    """
    DRE (Demonstração do Resultado do Exercício) Calculator - V2
    Processes financial transactions and generates Brazilian Income Statement

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

    def __init__(self):
        self.category_mapping = DRE_CATEGORIES

    def calculate_dre_from_transactions(
        self,
        transactions: List[dict],
        period_type: PeriodType,
        start_date: date,
        end_date: date,
        company_name: Optional[str] = None,
        cnpj: Optional[str] = None,
    ) -> DRE:
        """
        Calculate DRE from a list of transactions

        Args:
            transactions: List of transaction dicts with keys: date, amount, category, transaction_type
            period_type: Type of period (day, week, month, year, custom)
            start_date: Period start date
            end_date: Period end date
            company_name: Company name for report header
            cnpj: CNPJ for report header

        Returns:
            DRE object with all calculations
        """
        # Initialize DRE
        dre = DRE(
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            company_name=company_name,
            cnpj=cnpj,
        )

        # Filter transactions by period
        filtered_transactions = self._filter_transactions_by_period(
            transactions, start_date, end_date
        )

        dre.transaction_count = len(filtered_transactions)

        if not filtered_transactions:
            # No transactions - return empty DRE
            return dre

        # Categorize and aggregate transactions
        aggregated = self._aggregate_by_category(filtered_transactions)

        # ================================================================
        # V2 DRE Calculation Flow
        # ================================================================
        # 1. Receita Bruta
        self._calculate_revenue_section(dre, aggregated)
        # 2. (-) Deduções
        self._calculate_deduction_section(dre, aggregated)
        # 3. = Receita Líquida
        self._calculate_net_revenue(dre)
        # 4. (-) Custos Variáveis (V2)
        self._calculate_variable_costs(dre, aggregated)
        # 5. = Margem de Contribuição (V2)
        self._calculate_contribution_margin(dre)
        # 6. (-) Custos Fixos + Despesas Fixas (V2)
        self._calculate_fixed_costs(dre, aggregated)
        # 7. = EBITDA (V2: Margem Contribuição - Custos Fixos)
        self._calculate_ebitda(dre)
        # 8. (-) Depreciação e Amortização
        self._calculate_depreciation(dre, aggregated)
        # 9. = Resultado Operacional (EBIT)
        self._calculate_operating_result(dre)
        # 10. (+/-) Resultado Financeiro
        self._calculate_financial_result(dre, aggregated)
        # 11. = LAIR
        self._calculate_result_before_taxes(dre)
        # 12. (-) Impostos sobre o Lucro
        self._calculate_taxes_on_profit(dre, aggregated)
        # 13. = Lucro Líquido
        self._calculate_net_profit(dre)

        # ================================================================
        # Populate legacy fields for backward compatibility
        # ================================================================
        self._populate_legacy_fields(dre)

        # Calculate ratios (V2: vs receita_bruta)
        dre.calculate_ratios()

        # Track uncategorized transactions (check both V2 and legacy key names)
        uncat = aggregated.get("nao_categorizado", aggregated.get("uncategorized", {}))
        dre.uncategorized_count = uncat.get("count", 0)
        dre.uncategorized_amount = uncat.get("total", Decimal("0"))

        # Generate detailed line items (V2 structure)
        dre.detailed_lines = self._generate_detailed_lines(dre, aggregated)

        return dre

    def _filter_transactions_by_period(
        self, transactions: List[dict], start_date: date, end_date: date
    ) -> List[dict]:
        """Filter transactions within the specified period"""
        filtered = []

        for t in transactions:
            t_date = t.get("date")

            # Handle different date formats
            if isinstance(t_date, str):
                parsed = None
                # Try multiple common date formats
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
                    try:
                        parsed = datetime.strptime(t_date.strip(), fmt).date()
                        break
                    except (ValueError, TypeError):
                        continue
                if parsed is None:
                    # Log and skip transactions without valid dates
                    logger.warning(f"Skipping transaction with unparseable date: '{t.get('date')}' (doc_id={t.get('document_id')})")
                    continue
                t_date = parsed
            elif isinstance(t_date, datetime):
                t_date = t_date.date()
            elif not isinstance(t_date, date):
                # Log and skip invalid date types
                logger.warning(f"Skipping transaction with invalid date type: {type(t_date)} (doc_id={t.get('document_id')})")
                continue

            # Check if transaction falls within period
            if start_date <= t_date <= end_date:
                # Ensure amount is Decimal
                t_copy = t.copy()
                amount = t.get("amount", 0)
                if not isinstance(amount, Decimal):
                    t_copy["amount"] = Decimal(str(amount))
                filtered.append(t_copy)

        return filtered

    def _aggregate_by_category(self, transactions: List[dict]) -> Dict[str, dict]:
        """
        Aggregate transactions by category.
        Resolves legacy V1 category names to V2 canonical names via aliases.

        Returns:
            Dict with category as key and {total: Decimal, count: int, transactions: List} as value
        """
        aggregated = defaultdict(
            lambda: {"total": Decimal("0"), "count": 0, "transactions": []}
        )

        for t in transactions:
            category = t.get("category") or "uncategorized"
            # Handle None category
            if category is None:
                category = "uncategorized"
            # Resolve to canonical V2 name (handles aliases)
            category = resolve_category_name(category)

            amount = t.get("amount", Decimal("0"))
            transaction_type = t.get("transaction_type", "despesa").lower()

            # Apply sign based on transaction type
            # Income (receita) = positive contribution
            # Expense, Custo, Investimento, Perda = negative contribution
            from accounting import is_income_type
            if is_income_type(transaction_type):
                signed_amount = abs(amount)
            else:  # expense, gasto, investimento
                signed_amount = abs(amount)

            aggregated[category]["total"] += signed_amount
            aggregated[category]["count"] += 1
            aggregated[category]["transactions"].append(t)

        return dict(aggregated)

    # ====================================================================
    # V2 CALCULATION METHODS
    # ====================================================================

    def _calculate_revenue_section(self, dre: DRE, aggregated: dict):
        """Calculate Section 1: Receita Operacional Bruta"""
        total = Decimal("0")

        for category in REVENUE_CATEGORIES:
            if category in aggregated:
                total += aggregated[category]["total"]

        dre.receita_bruta = total

    def _calculate_deduction_section(self, dre: DRE, aggregated: dict):
        """Calculate Section 2: Deduções da Receita Bruta"""
        devolucoes = Decimal("0")
        impostos = Decimal("0")
        descontos = Decimal("0")

        for category in DEDUCTION_CATEGORIES:
            if category in aggregated:
                amount = aggregated[category]["total"]

                if "devolucoes" in category:
                    devolucoes += amount
                elif "descontos" in category:
                    descontos += amount
                else:
                    # Default deductions to impostos (impostos_sobre_vendas)
                    impostos += amount

        dre.devolucoes = devolucoes
        dre.impostos_sobre_vendas = impostos
        dre.descontos = descontos
        dre.total_deducoes = devolucoes + impostos + descontos

    def _calculate_net_revenue(self, dre: DRE):
        """Calculate Section 3: Receita Operacional Líquida"""
        dre.receita_liquida = dre.receita_bruta - dre.total_deducoes

    def _calculate_variable_costs(self, dre: DRE, aggregated: dict):
        """
        Calculate Section 4: Custos Variáveis (V2)
        Uses VARIABLE_COST_CATEGORIES (cost_behavior == "variable")
        """
        cmv = Decimal("0")
        csp = Decimal("0")
        outros = Decimal("0")

        for category in VARIABLE_COST_CATEGORIES:
            if category in aggregated:
                amount = aggregated[category]["total"]

                # CMV-related: cmv, materia_prima, insumos, comissoes_sobre_vendas
                if category in ("cmv", "materia_prima", "insumos", "comissoes_sobre_vendas"):
                    cmv += amount
                # CSP-related: csp
                elif category == "csp":
                    csp += amount
                # Other variable costs: salarios_producao, encargos_sociais_producao,
                # energia_producao, manutencao_equipamentos_producao
                else:
                    outros += amount

        dre.custos_variaveis_cmv = cmv
        dre.custos_variaveis_csp = csp
        dre.custos_variaveis_outros = outros
        dre.total_custos_variaveis = cmv + csp + outros

    def _calculate_contribution_margin(self, dre: DRE):
        """
        Calculate Section 5: Margem de Contribuição (V2)
        = Receita Líquida - Custos Variáveis
        """
        dre.margem_contribuicao = dre.receita_liquida - dre.total_custos_variaveis

    def _calculate_fixed_costs(self, dre: DRE, aggregated: dict):
        """
        Calculate Section 6: Custos Fixos + Despesas Fixas (V2)
        Uses FIXED_EXPENSE_ADMIN_CATEGORIES + FIXED_EXPENSE_COMMERCIAL_CATEGORIES
        """
        producao = Decimal("0")
        admin = Decimal("0")
        vendas = Decimal("0")
        outras = Decimal("0")

        # Fixed admin expenses (salarios_administrativos, pro_labore, aluguel, etc.)
        for category in FIXED_EXPENSE_ADMIN_CATEGORIES:
            if category in aggregated:
                amount = aggregated[category]["total"]
                # Check if it's a generic/other category
                if category in ("outras_despesas_operacionais", "nao_categorizado"):
                    outras += amount
                else:
                    admin += amount

        # Fixed commercial expenses (marketing, propaganda, fretes, etc.)
        for category in FIXED_EXPENSE_COMMERCIAL_CATEGORIES:
            if category in aggregated:
                vendas += aggregated[category]["total"]

        # Other operating expenses from OTHER_EXPENSE_CATEGORIES
        for category in OTHER_EXPENSE_CATEGORIES:
            if category in aggregated:
                outras += aggregated[category]["total"]

        dre.custos_fixos_producao = producao
        dre.despesas_administrativas = admin
        dre.despesas_vendas = vendas
        dre.outras_despesas = outras
        dre.total_custos_fixos = producao + admin + vendas + outras

    def _calculate_ebitda(self, dre: DRE):
        """
        Calculate Section 7: EBITDA (V2)
        = Margem de Contribuição - Total Custos Fixos
        """
        dre.ebitda = dre.margem_contribuicao - dre.total_custos_fixos

    def _calculate_depreciation(self, dre: DRE, aggregated: dict):
        """Calculate Section 8: Depreciação e Amortização"""
        deprec = Decimal("0")
        amort = Decimal("0")

        for category in DEPRECIATION_CATEGORIES:
            if category in aggregated:
                amount = aggregated[category]["total"]

                if "depreciacao" in category:
                    deprec += amount
                elif "amortizacao" in category:
                    amort += amount

        dre.depreciacao = deprec
        dre.amortizacao = amort
        dre.total_deprec_amort = deprec + amort

    def _calculate_operating_result(self, dre: DRE):
        """Calculate Section 9: Resultado Operacional (EBIT)"""
        dre.resultado_operacional = dre.ebitda - dre.total_deprec_amort

    def _calculate_financial_result(self, dre: DRE, aggregated: dict):
        """Calculate Section 10: Resultado Financeiro"""
        receitas = Decimal("0")
        despesas = Decimal("0")

        # Financial revenues
        for category in FINANCIAL_REVENUE_CATEGORIES:
            if category in aggregated:
                receitas += aggregated[category]["total"]

        # Non-operating revenues also go to financial result
        for category in NON_OPERATING_REVENUE_CATEGORIES:
            if category in aggregated:
                receitas += aggregated[category]["total"]

        # Financial expenses
        for category in FINANCIAL_EXPENSE_CATEGORIES:
            if category in aggregated:
                despesas += aggregated[category]["total"]

        dre.receitas_financeiras = receitas
        dre.despesas_financeiras = despesas
        dre.resultado_financeiro = receitas - despesas

    def _calculate_result_before_taxes(self, dre: DRE):
        """Calculate Section 11: Resultado Antes dos Impostos (LAIR)"""
        dre.resultado_antes_impostos = (
            dre.resultado_operacional + dre.resultado_financeiro
        )

    def _calculate_taxes_on_profit(self, dre: DRE, aggregated: dict):
        """Calculate Section 12: Impostos sobre o Lucro"""
        irpj = Decimal("0")
        csll = Decimal("0")

        for category in TAX_ON_PROFIT_CATEGORIES:
            if category in aggregated:
                amount = aggregated[category]["total"]

                if category == "irpj":
                    irpj += amount
                elif category == "csll":
                    csll += amount
                else:
                    # Other tax categories (simples_nacional, iptu, taxas_municipais)
                    # Default to IRPJ bucket for simplicity
                    irpj += amount

        dre.irpj = irpj
        dre.csll = csll
        dre.total_impostos_lucro = irpj + csll

    def _calculate_net_profit(self, dre: DRE):
        """Calculate Section 13: Lucro Líquido"""
        dre.lucro_liquido = dre.resultado_antes_impostos - dre.total_impostos_lucro

    # ====================================================================
    # LEGACY FIELD POPULATION (backward compatibility)
    # ====================================================================

    def _populate_legacy_fields(self, dre: DRE):
        """
        Populate legacy fields for backward compatibility.
        Maps V2 fields to their legacy equivalents.
        """
        # total_custos = total_custos_variaveis (old "costs" = new "variable costs")
        dre.total_custos = dre.total_custos_variaveis
        # lucro_bruto = margem_contribuicao (old "gross profit" = new "contribution margin")
        dre.lucro_bruto = dre.margem_contribuicao
        # total_despesas_operacionais = total_custos_fixos (old "opex" = new "fixed costs")
        dre.total_despesas_operacionais = dre.total_custos_fixos
        # custo_mercadorias_vendidas = custos_variaveis_cmv
        dre.custo_mercadorias_vendidas = dre.custos_variaveis_cmv
        # custo_servicos_prestados = custos_variaveis_csp
        dre.custo_servicos_prestados = dre.custos_variaveis_csp

    # ====================================================================
    # DETAILED LINE GENERATION (V2 Structure)
    # ====================================================================

    def _generate_detailed_lines(self, dre: DRE, aggregated: dict) -> List[DRELine]:
        """Generate detailed line items for DRE export - V2 structure"""
        lines = []
        gross_revenue = float(dre.receita_bruta)

        # V2: AV% calculated vs Receita Bruta, capped at ±999.9% for readability
        def pct(amount: Decimal) -> float:
            if gross_revenue == 0:
                return 0
            result = (float(amount) / gross_revenue) * 100
            return max(-999.9, min(999.9, result))

        # Section 1: Receita Bruta
        lines.append(
            DRELine(
                code="1",
                description="RECEITA OPERACIONAL BRUTA",
                amount=dre.receita_bruta,
                percentage_revenue=pct(dre.receita_bruta),
                is_total=True,
                level=1,
            )
        )

        # Add individual revenue categories
        for category in REVENUE_CATEGORIES:
            if category in aggregated:
                cat_config = DRE_CATEGORIES.get(category, {})
                lines.append(
                    DRELine(
                        code=cat_config.get("account_code", "1.1"),
                        description=cat_config.get("display_name", category),
                        amount=aggregated[category]["total"],
                        percentage_revenue=pct(aggregated[category]["total"]),
                        level=2,
                    )
                )

        # Section 2: Deduções
        lines.append(
            DRELine(
                code="2",
                description="(-) DEDUÇÕES DA RECEITA BRUTA",
                amount=-dre.total_deducoes,
                percentage_revenue=pct(dre.total_deducoes),
                is_subtotal=True,
                level=1,
            )
        )

        if dre.devolucoes > 0:
            lines.append(
                DRELine(
                    code="1.2.02",
                    description="(-) Devoluções",
                    amount=-dre.devolucoes,
                    percentage_revenue=pct(dre.devolucoes),
                    level=2,
                )
            )

        if dre.impostos_sobre_vendas > 0:
            lines.append(
                DRELine(
                    code="1.2.01",
                    description="(-) Impostos sobre Vendas",
                    amount=-dre.impostos_sobre_vendas,
                    percentage_revenue=pct(dre.impostos_sobre_vendas),
                    level=2,
                )
            )

        if dre.descontos > 0:
            lines.append(
                DRELine(
                    code="1.2.03",
                    description="(-) Descontos Concedidos",
                    amount=-dre.descontos,
                    percentage_revenue=pct(dre.descontos),
                    level=2,
                )
            )

        # Section 3: Receita Líquida
        lines.append(
            DRELine(
                code="3",
                description="RECEITA OPERACIONAL LÍQUIDA",
                amount=dre.receita_liquida,
                percentage_revenue=pct(dre.receita_liquida),
                is_total=True,
                level=1,
            )
        )

        # Section 4: Custos Variáveis (V2)
        if dre.total_custos_variaveis > 0:
            lines.append(
                DRELine(
                    code="4",
                    description="(-) CUSTOS VARIÁVEIS",
                    amount=-dre.total_custos_variaveis,
                    percentage_revenue=pct(dre.total_custos_variaveis),
                    is_subtotal=True,
                    level=1,
                )
            )

            # Add individual variable cost categories
            for category in VARIABLE_COST_CATEGORIES:
                if category in aggregated:
                    cat_config = DRE_CATEGORIES.get(category, {})
                    lines.append(
                        DRELine(
                            code=cat_config.get("account_code", "2.1"),
                            description=f"(-) {cat_config.get('display_name', category)}",
                            amount=-aggregated[category]["total"],
                            percentage_revenue=pct(aggregated[category]["total"]),
                            level=2,
                        )
                    )

        # Section 5: Margem de Contribuição (V2 - replaces Lucro Bruto)
        lines.append(
            DRELine(
                code="5",
                description="MARGEM DE CONTRIBUIÇÃO",
                amount=dre.margem_contribuicao,
                percentage_revenue=pct(dre.margem_contribuicao),
                is_total=True,
                level=1,
            )
        )

        # Legacy alias line for backward compatibility in exports
        # (Same value as MARGEM DE CONTRIBUIÇÃO)
        lines.append(
            DRELine(
                code="5.L",
                description="LUCRO BRUTO",
                amount=dre.lucro_bruto,
                percentage_revenue=pct(dre.lucro_bruto),
                is_total=True,
                level=1,
            )
        )

        # Section 6: Custos Fixos + Despesas Fixas (V2)
        if dre.total_custos_fixos > 0:
            lines.append(
                DRELine(
                    code="6",
                    description="(-) CUSTOS FIXOS E DESPESAS OPERACIONAIS",
                    amount=-dre.total_custos_fixos,
                    percentage_revenue=pct(dre.total_custos_fixos),
                    is_subtotal=True,
                    level=1,
                )
            )

            if dre.despesas_administrativas > 0:
                lines.append(
                    DRELine(
                        code="6.1",
                        description="(-) Despesas Administrativas",
                        amount=-dre.despesas_administrativas,
                        percentage_revenue=pct(dre.despesas_administrativas),
                        is_subtotal=True,
                        level=2,
                    )
                )

                # Individual admin expense categories
                for category in FIXED_EXPENSE_ADMIN_CATEGORIES:
                    if category in aggregated and category not in ("outras_despesas_operacionais", "nao_categorizado"):
                        cat_config = DRE_CATEGORIES.get(category, {})
                        lines.append(
                            DRELine(
                                code=cat_config.get("account_code", "3.1"),
                                description=f"(-) {cat_config.get('display_name', category)}",
                                amount=-aggregated[category]["total"],
                                percentage_revenue=pct(aggregated[category]["total"]),
                                level=3,
                            )
                        )

            if dre.despesas_vendas > 0:
                lines.append(
                    DRELine(
                        code="6.2",
                        description="(-) Despesas Comerciais",
                        amount=-dre.despesas_vendas,
                        percentage_revenue=pct(dre.despesas_vendas),
                        is_subtotal=True,
                        level=2,
                    )
                )

                # Individual commercial expense categories
                for category in FIXED_EXPENSE_COMMERCIAL_CATEGORIES:
                    if category in aggregated:
                        cat_config = DRE_CATEGORIES.get(category, {})
                        lines.append(
                            DRELine(
                                code=cat_config.get("account_code", "3.2"),
                                description=f"(-) {cat_config.get('display_name', category)}",
                                amount=-aggregated[category]["total"],
                                percentage_revenue=pct(aggregated[category]["total"]),
                                level=3,
                            )
                        )

            if dre.outras_despesas > 0:
                lines.append(
                    DRELine(
                        code="6.3",
                        description="(-) Outras Despesas",
                        amount=-dre.outras_despesas,
                        percentage_revenue=pct(dre.outras_despesas),
                        level=2,
                    )
                )

        # Section 7: EBITDA
        lines.append(
            DRELine(
                code="7",
                description="EBITDA",
                amount=dre.ebitda,
                percentage_revenue=pct(dre.ebitda),
                is_total=True,
                level=1,
            )
        )

        # Section 8: Depreciação e Amortização
        if dre.total_deprec_amort > 0:
            lines.append(
                DRELine(
                    code="8",
                    description="(-) Depreciação e Amortização",
                    amount=-dre.total_deprec_amort,
                    percentage_revenue=pct(dre.total_deprec_amort),
                    level=1,
                )
            )

            if dre.depreciacao > 0:
                lines.append(
                    DRELine(
                        code="8.1.01",
                        description="(-) Depreciação",
                        amount=-dre.depreciacao,
                        percentage_revenue=pct(dre.depreciacao),
                        level=2,
                    )
                )

            if dre.amortizacao > 0:
                lines.append(
                    DRELine(
                        code="8.1.02",
                        description="(-) Amortização",
                        amount=-dre.amortizacao,
                        percentage_revenue=pct(dre.amortizacao),
                        level=2,
                    )
                )

        # Section 9: EBIT
        lines.append(
            DRELine(
                code="9",
                description="RESULTADO OPERACIONAL (EBIT)",
                amount=dre.resultado_operacional,
                percentage_revenue=pct(dre.resultado_operacional),
                is_total=True,
                level=1,
            )
        )

        # Section 10: Resultado Financeiro
        lines.append(
            DRELine(
                code="10",
                description="RESULTADO FINANCEIRO",
                amount=dre.resultado_financeiro,
                percentage_revenue=pct(dre.resultado_financeiro),
                is_subtotal=True,
                level=1,
            )
        )

        if dre.receitas_financeiras > 0:
            lines.append(
                DRELine(
                    code="10.1",
                    description="(+) Receitas Financeiras",
                    amount=dre.receitas_financeiras,
                    percentage_revenue=pct(dre.receitas_financeiras),
                    level=2,
                )
            )

        if dre.despesas_financeiras > 0:
            lines.append(
                DRELine(
                    code="10.2",
                    description="(-) Despesas Financeiras",
                    amount=-dre.despesas_financeiras,
                    percentage_revenue=pct(dre.despesas_financeiras),
                    level=2,
                )
            )

        # Section 11: LAIR
        lines.append(
            DRELine(
                code="11",
                description="RESULTADO ANTES DOS IMPOSTOS (LAIR)",
                amount=dre.resultado_antes_impostos,
                percentage_revenue=pct(dre.resultado_antes_impostos),
                is_total=True,
                level=1,
            )
        )

        # Section 12: Impostos sobre o Lucro
        if dre.total_impostos_lucro > 0:
            lines.append(
                DRELine(
                    code="12",
                    description="(-) Impostos sobre o Lucro",
                    amount=-dre.total_impostos_lucro,
                    percentage_revenue=pct(dre.total_impostos_lucro),
                    level=1,
                )
            )

        # Section 13: Lucro Líquido
        lines.append(
            DRELine(
                code="13",
                description="LUCRO LÍQUIDO DO EXERCÍCIO",
                amount=dre.lucro_liquido,
                percentage_revenue=pct(dre.lucro_liquido),
                is_total=True,
                level=1,
            )
        )

        return lines


def calculate_dre(
    transactions: List[dict],
    period_type: PeriodType,
    start_date: date,
    end_date: date,
    company_name: Optional[str] = None,
    cnpj: Optional[str] = None,
) -> DRE:
    """
    Convenience function to calculate DRE

    Args:
        transactions: List of transaction dicts
        period_type: Period type enum
        start_date: Period start date
        end_date: Period end date
        company_name: Optional company name
        cnpj: Optional CNPJ

    Returns:
        DRE object
    """
    calculator = DRECalculator()
    return calculator.calculate_dre_from_transactions(
        transactions=transactions,
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        company_name=company_name,
        cnpj=cnpj,
    )


def get_period_dates(
    period_type: PeriodType, reference_date: Optional[date] = None
) -> tuple[date, date]:
    """
    Get start and end dates for a given period type

    Args:
        period_type: Period type enum
        reference_date: Reference date (defaults to today)

    Returns:
        Tuple of (start_date, end_date)
    """
    if reference_date is None:
        reference_date = date.today()

    if period_type == PeriodType.DAY:
        return (reference_date, reference_date)

    elif period_type == PeriodType.WEEK:
        # Monday to Sunday
        start = reference_date - timedelta(days=reference_date.weekday())
        end = start + timedelta(days=6)
        return (start, end)

    elif period_type == PeriodType.MONTH:
        # First day to last day of month
        start = reference_date.replace(day=1)
        if reference_date.month == 12:
            end = reference_date.replace(day=31)
        else:
            next_month = reference_date.replace(month=reference_date.month + 1, day=1)
            end = next_month - timedelta(days=1)
        return (start, end)

    elif period_type == PeriodType.YEAR:
        # January 1 to December 31
        start = reference_date.replace(month=1, day=1)
        end = reference_date.replace(month=12, day=31)
        return (start, end)

    else:
        # Custom - return same date (caller should override)
        return (reference_date, reference_date)
