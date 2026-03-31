"""
Brazilian Chart of Accounts (Plano de Contas)
Standard account structure following CPC/IFRS
"""

from enum import Enum
from typing import Dict, List, Optional


class AccountType(str, Enum):
    """Account types in balance sheet"""

    # ASSETS (Ativo)
    ATIVO_CIRCULANTE = "ativo_circulante"  # Current Assets
    ATIVO_NAO_CIRCULANTE = "ativo_nao_circulante"  # Non-current Assets

    # LIABILITIES (Passivo)
    PASSIVO_CIRCULANTE = "passivo_circulante"  # Current Liabilities
    PASSIVO_NAO_CIRCULANTE = "passivo_nao_circulante"  # Non-current Liabilities

    # EQUITY (Patrimônio Líquido)
    PATRIMONIO_LIQUIDO = "patrimonio_liquido"  # Equity

    # DRE ACCOUNTS (for closing entries)
    RECEITA = "receita"  # Revenue
    DESPESA = "despesa"  # Expense
    GASTO = "gasto"  # Cost/Spending
    INVESTIMENTO = "investimento"  # Investment


class AccountNature(str, Enum):
    """Normal balance of account (debit or credit)"""

    DEBIT = "debit"  # Debtor nature (Assets, Expenses)
    CREDIT = "credit"  # Creditor nature (Liabilities, Equity, Revenue)


class BrazilianChartOfAccounts:
    """
    Standard Brazilian Chart of Accounts
    Based on common Brazilian accounting practices
    """

    ACCOUNTS = {
        # ==========================================
        # 1. ATIVO CIRCULANTE (Current Assets)
        # ==========================================
        "1.01.001": {
            "code": "1.01.001",
            "name": "Caixa",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Cash on hand",
        },
        "1.01.002": {
            "code": "1.01.002",
            "name": "Bancos Conta Corrente",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Bank checking accounts",
        },
        "1.01.003": {
            "code": "1.01.003",
            "name": "Aplicações Financeiras",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Short-term investments",
        },
        "1.01.010": {
            "code": "1.01.010",
            "name": "Contas a Receber",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Accounts receivable",
        },
        "1.01.011": {
            "code": "1.01.011",
            "name": "(-) PDD - Provisão para Devedores Duvidosos",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,  # Contra-asset
            "description": "Allowance for doubtful accounts",
        },
        "1.01.020": {
            "code": "1.01.020",
            "name": "Estoques",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Inventory",
        },
        "1.01.030": {
            "code": "1.01.030",
            "name": "Adiantamentos a Fornecedores",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Advances to suppliers",
        },
        "1.01.040": {
            "code": "1.01.040",
            "name": "Impostos a Recuperar",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Taxes recoverable",
        },
        "1.01.050": {
            "code": "1.01.050",
            "name": "Despesas Antecipadas",
            "type": AccountType.ATIVO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Prepaid expenses",
        },
        # ==========================================
        # 1.2 ATIVO NÃO CIRCULANTE (Non-current Assets)
        # ==========================================
        "1.02.001": {
            "code": "1.02.001",
            "name": "Contas a Receber Longo Prazo",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Long-term accounts receivable",
        },
        "1.02.010": {
            "code": "1.02.010",
            "name": "Investimentos",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Investments",
        },
        "1.02.020": {
            "code": "1.02.020",
            "name": "Imobilizado",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Property, plant & equipment",
        },
        "1.02.021": {
            "code": "1.02.021",
            "name": "Máquinas e Equipamentos",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Machinery and equipment",
        },
        "1.02.022": {
            "code": "1.02.022",
            "name": "Móveis e Utensílios",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Furniture and fixtures",
        },
        "1.02.023": {
            "code": "1.02.023",
            "name": "Veículos",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Vehicles",
        },
        "1.02.024": {
            "code": "1.02.024",
            "name": "Computadores e Periféricos",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Computers and peripherals",
        },
        "1.02.025": {
            "code": "1.02.025",
            "name": "(-) Depreciação Acumulada",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.CREDIT,  # Contra-asset
            "description": "Accumulated depreciation",
        },
        "1.02.030": {
            "code": "1.02.030",
            "name": "Intangível",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Intangible assets",
        },
        "1.02.031": {
            "code": "1.02.031",
            "name": "Software",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.DEBIT,
            "description": "Software",
        },
        "1.02.032": {
            "code": "1.02.032",
            "name": "(-) Amortização Acumulada",
            "type": AccountType.ATIVO_NAO_CIRCULANTE,
            "nature": AccountNature.CREDIT,  # Contra-asset
            "description": "Accumulated amortization",
        },
        # ==========================================
        # 2. PASSIVO CIRCULANTE (Current Liabilities)
        # ==========================================
        "2.01.001": {
            "code": "2.01.001",
            "name": "Fornecedores",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Accounts payable - suppliers",
        },
        "2.01.010": {
            "code": "2.01.010",
            "name": "Salários a Pagar",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Salaries payable",
        },
        "2.01.011": {
            "code": "2.01.011",
            "name": "INSS a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Social security payable",
        },
        "2.01.012": {
            "code": "2.01.012",
            "name": "FGTS a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "FGTS payable",
        },
        "2.01.020": {
            "code": "2.01.020",
            "name": "ICMS a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "ICMS tax payable",
        },
        "2.01.021": {
            "code": "2.01.021",
            "name": "ISS a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "ISS tax payable",
        },
        "2.01.022": {
            "code": "2.01.022",
            "name": "PIS a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "PIS tax payable",
        },
        "2.01.023": {
            "code": "2.01.023",
            "name": "COFINS a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "COFINS tax payable",
        },
        "2.01.024": {
            "code": "2.01.024",
            "name": "IRPJ a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Corporate income tax payable",
        },
        "2.01.025": {
            "code": "2.01.025",
            "name": "CSLL a Recolher",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Social contribution payable",
        },
        "2.01.030": {
            "code": "2.01.030",
            "name": "Empréstimos Curto Prazo",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Short-term loans",
        },
        "2.01.031": {
            "code": "2.01.031",
            "name": "Financiamentos Curto Prazo",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Short-term financing",
        },
        "2.01.040": {
            "code": "2.01.040",
            "name": "Contas a Pagar",
            "type": AccountType.PASSIVO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Accounts payable - other",
        },
        # ==========================================
        # 2.2 PASSIVO NÃO CIRCULANTE (Non-current Liabilities)
        # ==========================================
        "2.02.001": {
            "code": "2.02.001",
            "name": "Empréstimos Longo Prazo",
            "type": AccountType.PASSIVO_NAO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Long-term loans",
        },
        "2.02.002": {
            "code": "2.02.002",
            "name": "Financiamentos Longo Prazo",
            "type": AccountType.PASSIVO_NAO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Long-term financing",
        },
        "2.02.003": {
            "code": "2.02.003",
            "name": "Provisões (LP)",
            "type": AccountType.PASSIVO_NAO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Long-term provisions (contingencies, legal claims)",
        },
        "2.02.004": {
            "code": "2.02.004",
            "name": "Passivos Fiscais Diferidos",
            "type": AccountType.PASSIVO_NAO_CIRCULANTE,
            "nature": AccountNature.CREDIT,
            "description": "Deferred tax liabilities",
        },
        # ==========================================
        # 3. PATRIMÔNIO LÍQUIDO (Equity)
        # ==========================================
        "3.01.001": {
            "code": "3.01.001",
            "name": "Capital Social",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.CREDIT,
            "description": "Share capital",
        },
        "3.01.002": {
            "code": "3.01.002",
            "name": "(-) Capital a Integralizar",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.DEBIT,  # Contra-equity
            "description": "Subscribed capital not paid",
        },
        "3.02.001": {
            "code": "3.02.001",
            "name": "Reservas de Capital",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.CREDIT,
            "description": "Capital reserves",
        },
        "3.03.001": {
            "code": "3.03.001",
            "name": "Reservas de Lucros",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.CREDIT,
            "description": "Profit reserves",
        },
        "3.04.001": {
            "code": "3.04.001",
            "name": "Lucros Acumulados",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.CREDIT,
            "description": "Retained earnings",
        },
        "3.04.002": {
            "code": "3.04.002",
            "name": "Lucro ou prejuízo do exercício",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.DEBIT,  # Negative equity
            "description": "Accumulated losses",
        },
        "3.05.001": {
            "code": "3.05.001",
            "name": "Lucro do Exercício",
            "type": AccountType.PATRIMONIO_LIQUIDO,
            "nature": AccountNature.CREDIT,
            "description": "Net income for the period",
        },
        # ==========================================
        # 4. RECEITAS (Revenue - DRE accounts)
        # ==========================================
        "4.01.001": {
            "code": "4.01.001",
            "name": "Receita de Vendas",
            "type": AccountType.RECEITA,
            "nature": AccountNature.CREDIT,
            "description": "Sales revenue",
        },
        "4.01.002": {
            "code": "4.01.002",
            "name": "Receita de Serviços",
            "type": AccountType.RECEITA,
            "nature": AccountNature.CREDIT,
            "description": "Service revenue",
        },
        "4.02.001": {
            "code": "4.02.001",
            "name": "(-) Devoluções de Vendas",
            "type": AccountType.RECEITA,
            "nature": AccountNature.DEBIT,  # Revenue deduction
            "description": "Sales returns",
        },
        "4.02.002": {
            "code": "4.02.002",
            "name": "(-) Descontos Concedidos",
            "type": AccountType.RECEITA,
            "nature": AccountNature.DEBIT,  # Revenue deduction
            "description": "Discounts granted",
        },
        "4.03.001": {
            "code": "4.03.001",
            "name": "Receitas Financeiras",
            "type": AccountType.RECEITA,
            "nature": AccountNature.CREDIT,
            "description": "Financial income",
        },
        # ==========================================
        # 5. DESPESAS (Expenses - DRE accounts)
        # ==========================================
        "5.01.001": {
            "code": "5.01.001",
            "name": "Custo das Mercadorias Vendidas (CMV)",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Cost of goods sold",
        },
        "5.01.002": {
            "code": "5.01.002",
            "name": "Custo dos Serviços Prestados (CSP)",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Cost of services",
        },
        "5.02.001": {
            "code": "5.02.001",
            "name": "Salários e Encargos",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Salaries and payroll taxes",
        },
        "5.02.002": {
            "code": "5.02.002",
            "name": "Aluguéis",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Rent expense",
        },
        "5.02.003": {
            "code": "5.02.003",
            "name": "Energia Elétrica",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Electricity expense",
        },
        "5.02.004": {
            "code": "5.02.004",
            "name": "Água e Esgoto",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Water and sewage",
        },
        "5.02.005": {
            "code": "5.02.005",
            "name": "Telefone e Internet",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Phone and internet",
        },
        "5.02.006": {
            "code": "5.02.006",
            "name": "Material de Escritório",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Office supplies",
        },
        "5.02.007": {
            "code": "5.02.007",
            "name": "Serviços Profissionais",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Professional services",
        },
        "5.02.008": {
            "code": "5.02.008",
            "name": "Seguros",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Insurance",
        },
        "5.02.009": {
            "code": "5.02.009",
            "name": "Manutenção e Reparos",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Maintenance and repairs",
        },
        "5.02.010": {
            "code": "5.02.010",
            "name": "Marketing e Publicidade",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Marketing and advertising",
        },
        "5.02.011": {
            "code": "5.02.011",
            "name": "Comissões",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Commissions",
        },
        "5.02.012": {
            "code": "5.02.012",
            "name": "Fretes",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Freight",
        },
        "5.02.013": {
            "code": "5.02.013",
            "name": "Depreciação",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Depreciation expense",
        },
        "5.02.014": {
            "code": "5.02.014",
            "name": "Amortização",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Amortization expense",
        },
        "5.03.001": {
            "code": "5.03.001",
            "name": "Despesas Financeiras",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Financial expenses",
        },
        "5.03.002": {
            "code": "5.03.002",
            "name": "Tarifas Bancárias",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Bank fees",
        },
        "5.04.001": {
            "code": "5.04.001",
            "name": "ICMS sobre Vendas",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "ICMS on sales",
        },
        "5.04.002": {
            "code": "5.04.002",
            "name": "ISS",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Service tax",
        },
        "5.04.003": {
            "code": "5.04.003",
            "name": "PIS",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "PIS tax",
        },
        "5.04.004": {
            "code": "5.04.004",
            "name": "COFINS",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "COFINS tax",
        },
        "5.04.005": {
            "code": "5.04.005",
            "name": "IRPJ",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Corporate income tax",
        },
        "5.04.006": {
            "code": "5.04.006",
            "name": "CSLL",
            "type": AccountType.DESPESA,
            "nature": AccountNature.DEBIT,
            "description": "Social contribution on net profit",
        },
    }

    @classmethod
    def get_account(cls, code: str) -> Optional[Dict]:
        """Get account by code"""
        return cls.ACCOUNTS.get(code)

    @classmethod
    def get_all_accounts(cls) -> List[Dict]:
        """Get all accounts"""
        return list(cls.ACCOUNTS.values())

    @classmethod
    def get_accounts_by_type(cls, account_type: AccountType) -> List[Dict]:
        """Get all accounts of a specific type"""
        return [acc for acc in cls.ACCOUNTS.values() if acc["type"] == account_type]

    @classmethod
    def search_accounts(cls, query: str) -> List[Dict]:
        """Search accounts by name or code"""
        query_lower = query.lower()
        return [
            acc
            for acc in cls.ACCOUNTS.values()
            if query_lower in acc["name"].lower() or query_lower in acc["code"]
        ]


# Default cash account for automatic entries
DEFAULT_CASH_ACCOUNT = "1.01.002"  # Bancos Conta Corrente
DEFAULT_RETAINED_EARNINGS_ACCOUNT = "3.04.001"  # Lucros Acumulados
