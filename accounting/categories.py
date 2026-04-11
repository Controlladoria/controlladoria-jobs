"""
DRE Category Mappings - V2
Maps transaction categories to DRE (Income Statement) line items
Based on the Plano de Contas (Chart of Accounts) provided by business partner
Following Brazilian accounting standards (CPC/IFRS)

V2 Changes:
- 52 categories from official Plano de Contas spreadsheet
- Variable vs Fixed cost behavior classification
- Account codes (X.Y.ZZ format)
- DRE Group mapping for correct report placement
- Backward-compatible aliases for old category names
"""

from enum import Enum
from typing import Dict, List, Optional


class DRELineType(str, Enum):
    """DRE line item types"""

    REVENUE = "revenue"
    DEDUCTION = "deduction"
    VARIABLE_COST = "variable_cost"
    FIXED_EXPENSE_ADMIN = "fixed_expense_admin"
    FIXED_EXPENSE_COMMERCIAL = "fixed_expense_commercial"
    DEPRECIATION = "depreciation"
    FINANCIAL_REVENUE = "financial_revenue"
    FINANCIAL_EXPENSE = "financial_expense"
    TAX_ON_PROFIT = "tax_on_profit"
    NON_OPERATING_REVENUE = "non_operating_revenue"
    OTHER_REVENUE = "other_revenue"
    OTHER_EXPENSE = "other_expense"

    # Legacy types kept for backward compatibility
    COST = "cost"
    SALES_EXPENSE = "sales_expense"
    ADMIN_EXPENSE = "admin_expense"


# ============================================================================
# V2 CATEGORIES - Based on Plano de Contas (Chart of Accounts) spreadsheet
# 52 accounts organized by code (X.Y.ZZ)
# ============================================================================

DRE_CATEGORIES: Dict[str, dict] = {
    # ========================================================================
    # 1.1 - RECEITA BRUTA (Gross Revenue) | Nature: Receita | DRE: Receita Bruta
    # ========================================================================
    "receita_vendas_produtos": {
        "account_code": "1.1.01",
        "dre_line": "receita_vendas_produtos",
        "line_type": DRELineType.REVENUE,
        "dre_group": "Receita Bruta",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "1. Receita Bruta",
        "display_name": "Receita de Vendas de Produtos",
        "sign": 1,
        "order": 1.01,
    },
    "receita_servicos": {
        "account_code": "1.1.02",
        "dre_line": "receita_servicos",
        "line_type": DRELineType.REVENUE,
        "dre_group": "Receita Bruta",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "1. Receita Bruta",
        "display_name": "Receita de Prestação de Serviços",
        "sign": 1,
        "order": 1.02,
    },
    "receita_locacao": {
        "account_code": "1.1.03",
        "dre_line": "receita_locacao",
        "line_type": DRELineType.REVENUE,
        "dre_group": "Receita Bruta",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "1. Receita Bruta",
        "display_name": "Receita de Locação",
        "sign": 1,
        "order": 1.03,
    },
    "receita_comissoes": {
        "account_code": "1.1.04",
        "dre_line": "receita_comissoes",
        "line_type": DRELineType.REVENUE,
        "dre_group": "Receita Bruta",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "1. Receita Bruta",
        "display_name": "Receita de Comissões",
        "sign": 1,
        "order": 1.04,
    },
    "receita_contratos_recorrentes": {
        "account_code": "1.1.05",
        "dre_line": "receita_contratos_recorrentes",
        "line_type": DRELineType.REVENUE,
        "dre_group": "Receita Bruta",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "1. Receita Bruta",
        "display_name": "Receita de Contratos Recorrentes",
        "sign": 1,
        "order": 1.05,
    },

    # ========================================================================
    # 1.2 - (-) DEDUÇÕES (Deductions) | Nature: Dedução | DRE: (-) Deduções
    # ========================================================================
    "impostos_sobre_vendas": {
        "account_code": "1.2.01",
        "dre_line": "impostos_sobre_vendas",
        "line_type": DRELineType.DEDUCTION,
        "dre_group": "(-) Deduções",
        "nature": "Deducao",
        "cost_behavior": None,
        "section": "2. Deduções e Impostos sobre Vendas",
        "display_name": "Impostos sobre Vendas",
        "sign": -1,
        "order": 2.01,
    },
    "devolucoes": {
        "account_code": "1.2.02",
        "dre_line": "devolucoes",
        "line_type": DRELineType.DEDUCTION,
        "dre_group": "(-) Deduções",
        "nature": "Deducao",
        "cost_behavior": None,
        "section": "2. Deduções e Impostos sobre Vendas",
        "display_name": "Devoluções",
        "sign": -1,
        "order": 2.02,
    },
    "descontos_concedidos": {
        "account_code": "1.2.03",
        "dre_line": "descontos_concedidos",
        "line_type": DRELineType.DEDUCTION,
        "dre_group": "(-) Deduções",
        "nature": "Deducao",
        "cost_behavior": None,
        "section": "2. Deduções e Impostos sobre Vendas",
        "display_name": "Descontos Concedidos",
        "sign": -1,
        "order": 2.03,
    },

    # ========================================================================
    # 1.4 - OUTRAS RECEITAS | Nature: Receita | DRE: Outras Receitas
    # (Note: 1.3 is intentionally skipped in the Plano de Contas)
    # ========================================================================
    "receita_financeira": {
        "account_code": "1.4.01",
        "dre_line": "receita_financeira",
        "line_type": DRELineType.OTHER_REVENUE,
        "dre_group": "Outras Receitas",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Receita Financeira",
        "sign": 1,
        "order": 10.01,
    },
    "juros_ativos": {
        "account_code": "1.4.02",
        "dre_line": "juros_ativos",
        "line_type": DRELineType.FINANCIAL_REVENUE,
        "dre_group": "Outras Receitas",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Juros Ativos",
        "sign": 1,
        "order": 10.02,
    },
    "descontos_obtidos": {
        "account_code": "1.4.03",
        "dre_line": "descontos_obtidos",
        "line_type": DRELineType.FINANCIAL_REVENUE,
        "dre_group": "Outras Receitas",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Descontos Obtidos",
        "sign": 1,
        "order": 10.03,
    },
    "recuperacao_despesas": {
        "account_code": "1.4.04",
        "dre_line": "recuperacao_despesas",
        "line_type": DRELineType.OTHER_REVENUE,
        "dre_group": "Outras Receitas",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Recuperação de Despesas",
        "sign": 1,
        "order": 10.04,
    },

    # ========================================================================
    # 1.5 - RECEITAS NÃO OPERACIONAIS | Nature: Receita
    # ========================================================================
    "venda_imobilizado": {
        "account_code": "1.5.01",
        "dre_line": "venda_imobilizado",
        "line_type": DRELineType.NON_OPERATING_REVENUE,
        "dre_group": "Receitas Não Operacionais",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "11. Resultado Não Operacional",
        "display_name": "Venda de Imobilizado",
        "sign": 1,
        "order": 11.01,
    },
    "indenizacoes_recebidas": {
        "account_code": "1.5.02",
        "dre_line": "indenizacoes_recebidas",
        "line_type": DRELineType.NON_OPERATING_REVENUE,
        "dre_group": "Receitas Não Operacionais",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "11. Resultado Não Operacional",
        "display_name": "Indenizações",
        "sign": 1,
        "order": 11.02,
    },
    "outras_receitas_eventuais": {
        "account_code": "1.5.03",
        "dre_line": "outras_receitas_eventuais",
        "line_type": DRELineType.NON_OPERATING_REVENUE,
        "dre_group": "Receitas Não Operacionais",
        "nature": "Receita",
        "cost_behavior": None,
        "section": "11. Resultado Não Operacional",
        "display_name": "Outras Receitas Eventuais",
        "sign": 1,
        "order": 11.03,
    },

    # ========================================================================
    # 2.1 - (-) CUSTOS DIRETOS (Variable) | Nature: Custo | DRE: (-) Custos
    # ========================================================================
    "cmv": {
        "account_code": "2.1.01",
        "dre_line": "cmv",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Custo das Mercadorias Vendidas (CMV)",
        "sign": -1,
        "order": 4.01,
    },
    "csp": {
        "account_code": "2.1.02",
        "dre_line": "csp",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Custo dos Serviços Prestados (CSP)",
        "sign": -1,
        "order": 4.02,
    },
    "materia_prima": {
        "account_code": "2.1.03",
        "dre_line": "materia_prima",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Matéria-Prima",
        "sign": -1,
        "order": 4.03,
    },
    "insumos": {
        "account_code": "2.1.04",
        "dre_line": "insumos",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Insumos",
        "sign": -1,
        "order": 4.04,
    },
    "comissoes_sobre_vendas": {
        "account_code": "2.1.05",
        "dre_line": "comissoes_sobre_vendas",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Comissões sobre Vendas",
        "sign": -1,
        "order": 4.05,
    },

    # ========================================================================
    # 2.2 - (-) CUSTOS INDIRETOS DE PRODUÇÃO (Variable) | Nature: Custo
    # ========================================================================
    "salarios_producao": {
        "account_code": "2.2.01",
        "dre_line": "salarios_producao",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Salários Produção",
        "sign": -1,
        "order": 4.06,
    },
    "encargos_sociais_producao": {
        "account_code": "2.2.02",
        "dre_line": "encargos_sociais_producao",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Encargos Sociais Produção",
        "sign": -1,
        "order": 4.07,
    },
    "energia_producao": {
        "account_code": "2.2.03",
        "dre_line": "energia_producao",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Energia Produção",
        "sign": -1,
        "order": 4.08,
    },
    "manutencao_equipamentos_producao": {
        "account_code": "2.2.04",
        "dre_line": "manutencao_equipamentos_producao",
        "line_type": DRELineType.VARIABLE_COST,
        "dre_group": "(-) Custos",
        "nature": "Custo",
        "cost_behavior": "variable",
        "section": "4. Custos Variáveis",
        "display_name": "Manutenção Equipamentos",
        "sign": -1,
        "order": 4.09,
    },

    # ========================================================================
    # 3.1 - (-) DESPESAS OPERACIONAIS / ADMINISTRATIVAS (Fixed)
    # Nature: Despesa | DRE: (-) Despesas Operacionais
    # ========================================================================
    "salarios_administrativos": {
        "account_code": "3.1.01",
        "dre_line": "salarios_administrativos",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Salários Administrativos",
        "sign": -1,
        "order": 6.01,
    },
    "pro_labore": {
        "account_code": "3.1.02",
        "dre_line": "pro_labore",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Pró-labore",
        "sign": -1,
        "order": 6.02,
    },
    "encargos_sociais_administrativos": {
        "account_code": "3.1.03",
        "dre_line": "encargos_sociais_administrativos",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Encargos Sociais Administrativos",
        "sign": -1,
        "order": 6.03,
    },
    "aluguel": {
        "account_code": "3.1.04",
        "dre_line": "aluguel",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Aluguel",
        "sign": -1,
        "order": 6.04,
    },
    "condominio": {
        "account_code": "3.1.05",
        "dre_line": "condominio",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Condomínio",
        "sign": -1,
        "order": 6.05,
    },
    "agua_energia": {
        "account_code": "3.1.06",
        "dre_line": "agua_energia",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Água e Energia",
        "sign": -1,
        "order": 6.06,
    },
    "material_escritorio": {
        "account_code": "3.1.07",
        "dre_line": "material_escritorio",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Material de Escritório",
        "sign": -1,
        "order": 6.07,
    },
    "honorarios_contabeis": {
        "account_code": "3.1.08",
        "dre_line": "honorarios_contabeis",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Honorários Contábeis",
        "sign": -1,
        "order": 6.08,
    },
    "sistemas_softwares": {
        "account_code": "3.1.09",
        "dre_line": "sistemas_softwares",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Sistemas e Softwares",
        "sign": -1,
        "order": 6.09,
    },
    "telefonia_internet": {
        "account_code": "3.1.10",
        "dre_line": "telefonia_internet",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Telefonia e Internet",
        "sign": -1,
        "order": 6.10,
    },

    # ========================================================================
    # 3.2 - (-) DESPESAS OPERACIONAIS / COMERCIAIS (Fixed)
    # Nature: Despesa | DRE: (-) Despesas Operacionais
    # ========================================================================
    "marketing_publicidade": {
        "account_code": "3.2.01",
        "dre_line": "marketing_publicidade",
        "line_type": DRELineType.FIXED_EXPENSE_COMMERCIAL,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Marketing e Publicidade",
        "sign": -1,
        "order": 6.11,
    },
    "propaganda_digital": {
        "account_code": "3.2.02",
        "dre_line": "propaganda_digital",
        "line_type": DRELineType.FIXED_EXPENSE_COMMERCIAL,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Propaganda Digital",
        "sign": -1,
        "order": 6.12,
    },
    "comissao_vendas": {
        "account_code": "3.2.03",
        "dre_line": "comissao_vendas",
        "line_type": DRELineType.FIXED_EXPENSE_COMMERCIAL,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Comissão de Vendas",
        "sign": -1,
        "order": 6.13,
    },
    "fretes": {
        "account_code": "3.2.04",
        "dre_line": "fretes",
        "line_type": DRELineType.FIXED_EXPENSE_COMMERCIAL,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Fretes",
        "sign": -1,
        "order": 6.14,
    },
    "representantes_comerciais": {
        "account_code": "3.2.05",
        "dre_line": "representantes_comerciais",
        "line_type": DRELineType.FIXED_EXPENSE_COMMERCIAL,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Representantes Comerciais",
        "sign": -1,
        "order": 6.15,
    },

    # ========================================================================
    # 3.3 - RESULTADO FINANCEIRO | Nature: Despesa | DRE: Resultado Financeiro
    # ========================================================================
    "juros_passivos": {
        "account_code": "3.3.01",
        "dre_line": "juros_passivos",
        "line_type": DRELineType.FINANCIAL_EXPENSE,
        "dre_group": "Resultado Financeiro",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Juros Passivos",
        "sign": -1,
        "order": 10.11,
    },
    "tarifas_bancarias": {
        "account_code": "3.3.02",
        "dre_line": "tarifas_bancarias",
        "line_type": DRELineType.FINANCIAL_EXPENSE,
        "dre_group": "Resultado Financeiro",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Tarifas Bancárias",
        "sign": -1,
        "order": 10.12,
    },
    "iof": {
        "account_code": "3.3.03",
        "dre_line": "iof",
        "line_type": DRELineType.FINANCIAL_EXPENSE,
        "dre_group": "Resultado Financeiro",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "IOF",
        "sign": -1,
        "order": 10.13,
    },
    "multas_encargos": {
        "account_code": "3.3.04",
        "dre_line": "multas_encargos",
        "line_type": DRELineType.FINANCIAL_EXPENSE,
        "dre_group": "Resultado Financeiro",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "10. Resultado Financeiro",
        "display_name": "Multas e Encargos",
        "sign": -1,
        "order": 10.14,
    },

    # ========================================================================
    # 3.4 - (-) TRIBUTOS | Nature: Despesa | DRE: (-) Tributos
    # ========================================================================
    "irpj": {
        "account_code": "3.4.01",
        "dre_line": "irpj",
        "line_type": DRELineType.TAX_ON_PROFIT,
        "dre_group": "(-) Tributos",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "12. Impostos sobre o Lucro",
        "display_name": "IRPJ",
        "sign": -1,
        "order": 12.01,
    },
    "csll": {
        "account_code": "3.4.02",
        "dre_line": "csll",
        "line_type": DRELineType.TAX_ON_PROFIT,
        "dre_group": "(-) Tributos",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "12. Impostos sobre o Lucro",
        "display_name": "CSLL",
        "sign": -1,
        "order": 12.02,
    },
    "simples_nacional": {
        "account_code": "3.4.03",
        "dre_line": "simples_nacional",
        "line_type": DRELineType.TAX_ON_PROFIT,
        "dre_group": "(-) Tributos",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "12. Impostos sobre o Lucro",
        "display_name": "Simples Nacional",
        "sign": -1,
        "order": 12.03,
    },
    "iptu": {
        "account_code": "3.4.04",
        "dre_line": "iptu",
        "line_type": DRELineType.TAX_ON_PROFIT,
        "dre_group": "(-) Tributos",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "12. Impostos sobre o Lucro",
        "display_name": "IPTU",
        "sign": -1,
        "order": 12.04,
    },
    "taxas_municipais": {
        "account_code": "3.4.05",
        "dre_line": "taxas_municipais",
        "line_type": DRELineType.TAX_ON_PROFIT,
        "dre_group": "(-) Tributos",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "12. Impostos sobre o Lucro",
        "display_name": "Taxas Municipais",
        "sign": -1,
        "order": 12.05,
    },

    # ========================================================================
    # 3.5 - OUTRAS DESPESAS | Nature: Despesa | DRE: Outras Despesas
    # ========================================================================
    "perdas": {
        "account_code": "3.5.01",
        "dre_line": "perdas",
        "line_type": DRELineType.OTHER_EXPENSE,
        "dre_group": "Outras Despesas",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "13. Outras Despesas",
        "display_name": "Perdas",
        "sign": -1,
        "order": 13.01,
    },
    "indenizacoes_pagas": {
        "account_code": "3.5.02",
        "dre_line": "indenizacoes_pagas",
        "line_type": DRELineType.OTHER_EXPENSE,
        "dre_group": "Outras Despesas",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "13. Outras Despesas",
        "display_name": "Indenizações",
        "sign": -1,
        "order": 13.02,
    },
    "doacoes": {
        "account_code": "3.5.03",
        "dre_line": "doacoes",
        "line_type": DRELineType.OTHER_EXPENSE,
        "dre_group": "Outras Despesas",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "13. Outras Despesas",
        "display_name": "Doações",
        "sign": -1,
        "order": 13.03,
    },
    "provisoes": {
        "account_code": "3.5.04",
        "dre_line": "provisoes",
        "line_type": DRELineType.OTHER_EXPENSE,
        "dre_group": "Outras Despesas",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "13. Outras Despesas",
        "display_name": "Provisões",
        "sign": -1,
        "order": 13.04,
    },

    # ========================================================================
    # DEPRECIATION & AMORTIZATION (kept for template compatibility)
    # ========================================================================
    "depreciacao": {
        "account_code": "8.1.01",
        "dre_line": "depreciacao",
        "line_type": DRELineType.DEPRECIATION,
        "dre_group": "Depreciação e Amortização",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "8. Depreciação e Amortização",
        "display_name": "Depreciação",
        "sign": -1,
        "order": 8.01,
    },
    "amortizacao": {
        "account_code": "8.1.02",
        "dre_line": "amortizacao",
        "line_type": DRELineType.DEPRECIATION,
        "dre_group": "Depreciação e Amortização",
        "nature": "Despesa",
        "cost_behavior": None,
        "section": "8. Depreciação e Amortização",
        "display_name": "Amortização",
        "sign": -1,
        "order": 8.02,
    },

    # ========================================================================
    # GENERIC / UNCATEGORIZED (catch-all)
    # ========================================================================
    "outras_despesas_operacionais": {
        "account_code": "6.9.01",
        "dre_line": "outras_despesas_operacionais",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Outras Despesas Operacionais",
        "sign": -1,
        "order": 6.99,
    },
    "nao_categorizado": {
        "account_code": "9.9.99",
        "dre_line": "nao_categorizado",
        "line_type": DRELineType.FIXED_EXPENSE_ADMIN,
        "dre_group": "(-) Despesas Operacionais",
        "nature": "Despesa",
        "cost_behavior": "fixed",
        "section": "6. Despesas Fixas Operacionais",
        "display_name": "Não Categorizado",
        "sign": -1,
        "order": 99.99,
    },
}


# ============================================================================
# BACKWARD COMPATIBILITY: Alias old category names to new V2 names
# This ensures existing data and tests continue working without changes
# ============================================================================

CATEGORY_ALIASES: Dict[str, str] = {
    # Old V1 revenue names -> V2
    "sales": "receita_vendas_produtos",
    "services": "receita_servicos",
    "other_income": "receita_locacao",

    # Portuguese aliases (from legacy AI categorization)
    "vendas": "receita_vendas_produtos",
    "venda": "receita_vendas_produtos",
    "receita": "receita_vendas_produtos",
    "receitas": "receita_vendas_produtos",
    "servicos": "receita_servicos",
    "serviço": "receita_servicos",
    "serviços": "receita_servicos",
    "compras": "cmv",
    "compra": "cmv",
    "impostos": "impostos_sobre_vendas",
    "imposto": "impostos_sobre_vendas",
    "tributos": "impostos_sobre_vendas",
    "taxas": "taxas_municipais",
    "frete": "fretes",
    "transporte": "fretes",
    "transportation": "fretes",
    "aluguel_imovel": "aluguel",
    "honorarios": "honorarios_contabeis",
    "contabilidade": "honorarios_contabeis",
    "salario": "salarios_administrativos",
    "salarios": "salarios_administrativos",
    "folha": "salarios_administrativos",
    "energia": "agua_energia",
    "luz": "agua_energia",
    "agua": "agua_energia",
    "telefone": "telefonia_internet",
    "combustivel": "outras_despesas_operacionais",
    "material": "material_escritorio",
    "software": "sistemas_softwares",
    "sistema": "sistemas_softwares",

    # Old V1 deduction names -> V2
    "sales_returns": "devolucoes",
    "sales_tax_icms": "impostos_sobre_vendas",
    "sales_tax_iss": "impostos_sobre_vendas",
    "sales_tax_pis": "impostos_sobre_vendas",
    "sales_tax_cofins": "impostos_sobre_vendas",
    "sales_tax": "impostos_sobre_vendas",
    "discounts_granted": "descontos_concedidos",

    # Old V1 cost names -> V2
    "cogs": "cmv",
    "cost_of_services": "csp",
    "direct_materials": "materia_prima",
    "direct_labor": "salarios_producao",

    # Old V1 sales expense names -> V2
    "commissions": "comissoes_sobre_vendas",
    "marketing": "marketing_publicidade",
    "advertising": "propaganda_digital",
    "freight_out": "fretes",
    "packaging": "fretes",

    # Old V1 admin expense names -> V2
    "salaries": "salarios_administrativos",
    "payroll": "salarios_administrativos",
    "rent": "aluguel",
    "office_supplies": "material_escritorio",
    "utilities": "agua_energia",
    "electricity": "agua_energia",
    "water": "agua_energia",
    "phone": "telefonia_internet",
    "internet": "telefonia_internet",
    "professional_services": "honorarios_contabeis",
    "accounting_services": "honorarios_contabeis",
    "legal_services": "honorarios_contabeis",
    "insurance": "outras_despesas_operacionais",
    "travel": "outras_despesas_operacionais",
    "maintenance": "outras_despesas_operacionais",

    # Old V1 depreciation names -> V2
    "depreciation": "depreciacao",
    "amortization": "amortizacao",

    # Old V1 financial names -> V2
    "interest_income": "juros_ativos",
    "financial_income": "receita_financeira",
    "investment_income": "receita_financeira",
    "interest_expense": "juros_passivos",
    "financial_expense": "juros_passivos",
    "bank_fees": "tarifas_bancarias",

    # Old V1 tax names -> V2
    "income_tax": "irpj",
    "social_contribution": "csll",

    # Old V1 generic names -> V2
    "other_expense": "outras_despesas_operacionais",
    "uncategorized": "nao_categorizado",
}


def get_dre_category(category: str) -> Optional[dict]:
    """
    Get DRE category configuration for a given transaction category.
    Supports both V2 category names and legacy V1 aliases.

    Args:
        category: Transaction category name (V1 or V2)

    Returns:
        DRE category configuration dict or None if not found
    """
    if category is None:
        return DRE_CATEGORIES.get("nao_categorizado")

    key = category.lower().strip()

    # Try direct lookup in V2 categories first
    result = DRE_CATEGORIES.get(key)
    if result:
        return result

    # Fall back to alias mapping
    aliased = CATEGORY_ALIASES.get(key)
    if aliased:
        return DRE_CATEGORIES.get(aliased)

    # Not found
    return None


def resolve_category_name(category: str) -> str:
    """
    Resolve a category name to its canonical V2 name.
    Handles aliases and returns the V2 name.

    Args:
        category: Transaction category name (V1 or V2)

    Returns:
        Canonical V2 category name
    """
    if category is None:
        return "nao_categorizado"

    key = category.lower().strip()

    # Already a V2 category?
    if key in DRE_CATEGORIES:
        return key

    # Check alias
    aliased = CATEGORY_ALIASES.get(key)
    if aliased and aliased in DRE_CATEGORIES:
        return aliased

    # Check display_name → key mapping (for template spreadsheets)
    for cat_key, cat_config in DRE_CATEGORIES.items():
        display = cat_config.get("display_name", "")
        if display and display.lower().strip() == key:
            return cat_key

    return "nao_categorizado"


def get_all_categories() -> List[dict]:
    """
    Get all DRE categories sorted by section order

    Returns:
        List of all category configurations with category name included
    """
    categories = []
    for cat_name, cat_config in DRE_CATEGORIES.items():
        categories.append({"category": cat_name, **cat_config})

    categories.sort(key=lambda x: x["order"])
    return categories


def get_categories_by_type(line_type: DRELineType) -> List[str]:
    """
    Get all category names for a specific DRE line type

    Args:
        line_type: DRE line type enum

    Returns:
        List of category names
    """
    return [
        cat_name
        for cat_name, cat_config in DRE_CATEGORIES.items()
        if cat_config["line_type"] == line_type
    ]


def get_categories_by_behavior(behavior: str) -> List[str]:
    """
    Get all category names by cost behavior (variable/fixed)

    Args:
        behavior: "variable" or "fixed"

    Returns:
        List of category names
    """
    return [
        cat_name
        for cat_name, cat_config in DRE_CATEGORIES.items()
        if cat_config.get("cost_behavior") == behavior
    ]


def get_categories_by_dre_group(dre_group: str) -> List[str]:
    """
    Get all category names for a specific DRE group

    Args:
        dre_group: e.g., "Receita Bruta", "(-) Deduções", "(-) Custos"

    Returns:
        List of category names
    """
    return [
        cat_name
        for cat_name, cat_config in DRE_CATEGORIES.items()
        if cat_config.get("dre_group") == dre_group
    ]


# ============================================================================
# PRE-COMPUTED CATEGORY LISTS FOR QUICK LOOKUPS
# ============================================================================

# V2 category lists by line type
REVENUE_CATEGORIES = get_categories_by_type(DRELineType.REVENUE)
DEDUCTION_CATEGORIES = get_categories_by_type(DRELineType.DEDUCTION)
VARIABLE_COST_CATEGORIES = get_categories_by_behavior("variable")
FIXED_EXPENSE_ADMIN_CATEGORIES = get_categories_by_type(DRELineType.FIXED_EXPENSE_ADMIN)
FIXED_EXPENSE_COMMERCIAL_CATEGORIES = get_categories_by_type(DRELineType.FIXED_EXPENSE_COMMERCIAL)
DEPRECIATION_CATEGORIES = get_categories_by_type(DRELineType.DEPRECIATION)
FINANCIAL_REVENUE_CATEGORIES = get_categories_by_type(DRELineType.FINANCIAL_REVENUE) + get_categories_by_type(DRELineType.OTHER_REVENUE)
FINANCIAL_EXPENSE_CATEGORIES = get_categories_by_type(DRELineType.FINANCIAL_EXPENSE)
TAX_ON_PROFIT_CATEGORIES = get_categories_by_type(DRELineType.TAX_ON_PROFIT)
NON_OPERATING_REVENUE_CATEGORIES = get_categories_by_type(DRELineType.NON_OPERATING_REVENUE)
OTHER_EXPENSE_CATEGORIES = get_categories_by_type(DRELineType.OTHER_EXPENSE)

# Combined lists for DRE calculator convenience
FIXED_COST_CATEGORIES = get_categories_by_behavior("fixed")
ALL_EXPENSE_CATEGORIES = FIXED_EXPENSE_ADMIN_CATEGORIES + FIXED_EXPENSE_COMMERCIAL_CATEGORIES

# Legacy compatibility lists (map to V2 via aliases)
COST_CATEGORIES = VARIABLE_COST_CATEGORIES  # Old COST = new VARIABLE_COST
SALES_EXPENSE_CATEGORIES = FIXED_EXPENSE_COMMERCIAL_CATEGORIES
ADMIN_EXPENSE_CATEGORIES = FIXED_EXPENSE_ADMIN_CATEGORIES

# All valid category names (V2 + aliases)
ALL_CATEGORY_NAMES = list(DRE_CATEGORIES.keys()) + list(CATEGORY_ALIASES.keys())


# ============================================================================
# CATEGORY → TRANSACTION TYPE ENFORCEMENT (Plano de Contas compliance)
# ============================================================================

# Build lookup: category_name → nature (Receita/Deducao/Custo/Despesa)
CATEGORY_TO_NATURE: Dict[str, str] = {
    cat_name: cat_info["nature"]
    for cat_name, cat_info in DRE_CATEGORIES.items()
    if "nature" in cat_info
}

# Map nature to the canonical transaction_type
NATURE_TO_TRANSACTION_TYPE: Dict[str, str] = {
    "Receita": "receita",
    "Deducao": "deducao",
    "Custo": "custo",
    "Despesa": "despesa",
}


def enforce_category_type(category: str, transaction_type: str) -> str:
    """Return the correct transaction_type for the given category.

    If category is a known V2 category (or resolves to one via aliases),
    override transaction_type to match the Plano de Contas nature.
    Otherwise return transaction_type unchanged.

    Examples:
        enforce_category_type("insumos", "despesa")   → "custo"
        enforce_category_type("cmv", "expense")        → "custo"
        enforce_category_type("aluguel", "custo")      → "despesa"
        enforce_category_type("unknown_cat", "despesa") → "despesa"
    """
    if not category:
        return transaction_type

    resolved = resolve_category_name(category)
    nature = CATEGORY_TO_NATURE.get(resolved)
    if nature:
        return NATURE_TO_TRANSACTION_TYPE.get(nature, transaction_type)
    return transaction_type
