"""
Balance Sheet (Balanço Gerencial) Calculator - V2
Calculates balance sheet from chart of accounts and journal entries,
with document-based fallback when journal entries are not available.

V2 Changes (Item 1B - partner feedback):
- 4-group asset structure: Circulante, Não Circulante, Imobilizado, Intangível
- Sub-items within each group matching ControlladorIA template
- Explicit Imobilizado (Custo - Depreciação Acumulada) and Intangível (Custo - Amortização) groups
- Legacy fields preserved for backward compatibility
"""

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from database import ChartOfAccountsEntry, Document, DocumentStatus, JournalEntry, JournalEntryLine

from .chart_of_accounts import AccountType

logger = logging.getLogger(__name__)


class BalanceSheetLine:
    """Single line in balance sheet"""

    def __init__(
        self,
        code: str,
        name: str,
        balance: Decimal,
        level: int = 1,
        is_subtotal: bool = False,
        is_total: bool = False,
    ):
        self.code = code
        self.name = name
        self.balance = balance
        self.level = level
        self.is_subtotal = is_subtotal
        self.is_total = is_total


class BalanceSheet:
    """
    Complete Balance Sheet - V2

    V2 Structure:
    ATIVO:
      Ativo Circulante (Caixa, Aplicações, Clientes, Estoques, Despesas Antecipadas)
      Ativo Não Circulante (Créditos LP, Investimentos)
      Imobilizado (Custo - Depreciação Acumulada)
      Intangível (Custo - Amortização Acumulada)
      TOTAL ATIVO

    PASSIVO + PL:
      Passivo Circulante (Fornecedores, Empréstimos CP, Obrigações Trab, Obrigações Fiscais, Contas a Pagar)
      Passivo Não Circulante (Empréstimos LP, Financiamentos LP)
      Patrimônio Líquido (Capital Social, Reservas, Lucros Acumulados)
      TOTAL PASSIVO + PL
    """

    def __init__(
        self,
        reference_date: date,
        company_name: Optional[str] = None,
        cnpj: Optional[str] = None,
    ):
        self.reference_date = reference_date
        self.company_name = company_name
        self.cnpj = cnpj

        # ================================================================
        # V2 Asset Groups
        # ================================================================
        self.ativo_circulante: Decimal = Decimal("0")
        self.ativo_nao_circulante: Decimal = Decimal("0")  # Realizável LP only
        self.imobilizado: Decimal = Decimal("0")  # V2: Separate group
        self.intangivel: Decimal = Decimal("0")  # V2: Separate group
        self.total_ativo: Decimal = Decimal("0")

        # ================================================================
        # V2 Liability Groups
        # ================================================================
        self.passivo_circulante: Decimal = Decimal("0")
        self.passivo_nao_circulante: Decimal = Decimal("0")
        self.total_passivo: Decimal = Decimal("0")

        # Equity
        self.patrimonio_liquido: Decimal = Decimal("0")

        # ================================================================
        # Detailed lines per group (V2)
        # ================================================================
        self.asset_lines: List[BalanceSheetLine] = []
        self.asset_noncurrent_lines: List[BalanceSheetLine] = []  # V2: separate
        self.imobilizado_lines: List[BalanceSheetLine] = []  # V2
        self.intangivel_lines: List[BalanceSheetLine] = []  # V2
        self.liability_lines: List[BalanceSheetLine] = []
        self.liability_noncurrent_lines: List[BalanceSheetLine] = []  # V3: separate NC liabilities
        self.equity_lines: List[BalanceSheetLine] = []

        # Validation
        self.is_balanced: bool = False
        self.balance_difference: Decimal = Decimal("0")

    def calculate_totals(self):
        """Calculate totals and validate balance - V2"""
        # V2: Total Ativo includes all 4 groups
        self.total_ativo = (
            self.ativo_circulante
            + self.ativo_nao_circulante
            + self.imobilizado
            + self.intangivel
        )
        self.total_passivo = self.passivo_circulante + self.passivo_nao_circulante

        # Assets = Liabilities + Equity
        total_passivo_e_pl = self.total_passivo + self.patrimonio_liquido

        self.balance_difference = self.total_ativo - total_passivo_e_pl
        self.is_balanced = abs(self.balance_difference) < Decimal("0.01")

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization - V2"""
        # Build detailed_lines from all line groups
        detailed_lines = []
        for line in (
            self.asset_lines
            + self.asset_noncurrent_lines
            + self.imobilizado_lines
            + self.intangivel_lines
            + self.liability_lines
            + self.liability_noncurrent_lines
            + self.equity_lines
        ):
            detailed_lines.append({
                "code": line.code,
                "description": line.name,
                "amount": float(line.balance),
                "is_subtotal": line.is_subtotal,
                "is_total": line.is_total,
                "level": line.level,
            })

        return {
            "reference_date": self.reference_date.isoformat(),
            "company_name": self.company_name,
            "cnpj": self.cnpj,
            "ativo": {
                "circulante": float(self.ativo_circulante),
                "nao_circulante": float(self.ativo_nao_circulante),
                "imobilizado": float(self.imobilizado),
                "intangivel": float(self.intangivel),
                "total": float(self.total_ativo),
            },
            "passivo": {
                "circulante": float(self.passivo_circulante),
                "nao_circulante": float(self.passivo_nao_circulante),
                "total": float(self.total_passivo),
            },
            "patrimonio_liquido": {
                "total": float(self.patrimonio_liquido),
                "capital_social": float(sum(l.balance for l in self.equity_lines if l.code.startswith("3.01"))),
                "reservas": float(sum(l.balance for l in self.equity_lines if l.code.startswith("3.02") or l.code.startswith("3.03"))),
                "lucros_acumulados": float(sum(l.balance for l in self.equity_lines if l.code.startswith("3.04") or l.code.startswith("3.05"))),
            },
            "is_balanced": self.is_balanced,
            "balance_difference": float(self.balance_difference),
            "detailed_lines": detailed_lines if detailed_lines else None,
        }


class BalanceSheetCalculator:
    """Calculate balance sheet from accounting data - V2"""

    def __init__(self, db: Session, user_id: int, org_id: Optional[int] = None):
        self.db = db
        self.user_id = user_id
        self.org_id = org_id

    def calculate_balance_sheet(
        self,
        reference_date: date,
        company_name: Optional[str] = None,
        cnpj: Optional[str] = None,
    ) -> BalanceSheet:
        """
        Calculate balance sheet as of a specific date - V2

        Uses journal entries when available, falls back to document-based
        calculation when journal entries are empty.

        The reference_date is expanded to end-of-month for consistency.

        If the organization has initial balance data, it is added on top
        of the computed values.

        Args:
            reference_date: Date for balance sheet (any day in the desired month)
            company_name: Company name for header
            cnpj: CNPJ for header

        Returns:
            BalanceSheet object with all balances
        """
        # Expand reference_date to end of the selected month
        import calendar
        last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
        ref_date = reference_date.replace(day=last_day)

        bs = BalanceSheet(
            reference_date=ref_date, company_name=company_name, cnpj=cnpj
        )

        # Try journal-entry-based calculation first
        accounts = self._get_account_balances(ref_date)

        has_journal_data = any(a["balance"] != Decimal("0") for a in accounts)

        if has_journal_data:
            # Use journal entries (full double-entry bookkeeping)
            self._populate_from_journal_entries(bs, accounts)
        else:
            # Fallback: derive balance sheet from document transactions
            logger.info("No journal entries found, using document-based balance sheet")
            self._populate_from_documents(bs, ref_date)

        # Apply initial balances from questionnaire (if available)
        initial = self._get_initial_balance(ref_date)
        if initial:
            self._apply_initial_balances(bs, initial)

        # Calculate totals and validate
        bs.calculate_totals()

        return bs

    def _get_initial_balance(self, reference_date: date):
        """
        Load the initial balance for this organization.
        Returns the most recent completed initial balance record whose
        reference_date is <= the report reference_date.
        """
        if not self.org_id:
            logger.info(f"No org_id set, skipping initial balance lookup")
            return None

        try:
            from database import OrgInitialBalance

            # First check: any initial balance records at all for this org?
            all_records = (
                self.db.query(OrgInitialBalance)
                .filter(OrgInitialBalance.organization_id == self.org_id)
                .all()
            )
            if all_records:
                logger.info(
                    f"Found {len(all_records)} initial balance record(s) for org {self.org_id}: "
                    f"dates={[str(r.reference_date) for r in all_records]}, "
                    f"completed={[r.is_completed for r in all_records]}"
                )
            else:
                logger.info(f"No initial balance records found for org {self.org_id}")
                return None

            # Query: most recent completed record where reference_date <= report date
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

            if initial:
                logger.info(
                    f"Using initial balance from {initial.reference_date} for report date {reference_date} "
                    f"(cash={initial.cash_and_equivalents}, receivables={initial.accounts_receivable})"
                )
            else:
                # Maybe the reference_date filter is too strict — check if there's
                # a completed record with a future date
                future = (
                    self.db.query(OrgInitialBalance)
                    .filter(
                        OrgInitialBalance.organization_id == self.org_id,
                        OrgInitialBalance.is_completed == True,
                    )
                    .first()
                )
                if future:
                    logger.warning(
                        f"Initial balance exists (date={future.reference_date}) but it's after "
                        f"report date {reference_date}. Using it anyway as starting point."
                    )
                    initial = future
                else:
                    logger.warning(
                        f"No completed initial balance found for org {self.org_id} "
                        f"(records exist but none are completed)"
                    )

            return initial
        except Exception as e:
            # If the query fails (e.g., new columns not yet migrated),
            # log the error and continue without initial balances rather
            # than crashing the entire report.
            logger.warning(f"Failed to load initial balance: {e}")
            self.db.rollback()
            return None

    def _apply_initial_balances(self, bs: BalanceSheet, initial) -> None:
        """
        Add initial balance values on top of computed balance sheet values.
        Creates "Saldo Inicial" line items for each non-zero category.
        """
        # === ATIVO CIRCULANTE ===
        items_circulante = [
            ("1.01.001", "Caixa e Equivalentes (Saldo Inicial)", initial.cash_and_equivalents),
            ("1.01.002", "Aplicações Financeiras CP (Saldo Inicial)", initial.short_term_investments),
            ("1.01.003", "Clientes - Contas a Receber (Saldo Inicial)", initial.accounts_receivable),
            ("1.01.004", "Estoques (Saldo Inicial)", initial.inventory),
            ("1.01.005", "Despesas Antecipadas (Saldo Inicial)", initial.prepaid_expenses),
        ]

        # Add bank account balances to cash
        bank_total = Decimal("0")
        if initial.bank_account_balances:
            for entry in initial.bank_account_balances:
                bank_total += Decimal(str(entry.get("balance", 0)))

        if bank_total > Decimal("0"):
            items_circulante.append(
                ("1.01.006", "Saldos em Contas Bancárias (Saldo Inicial)", bank_total)
            )

        for code, name, amount in items_circulante:
            val = Decimal(str(amount or 0))
            if val != Decimal("0"):
                bs.ativo_circulante += val
                bs.asset_lines.append(BalanceSheetLine(code=code, name=name, balance=val, level=2))

        # === ATIVO NÃO CIRCULANTE ===
        items_nao_circulante = [
            ("1.02.001", "Créditos a Receber LP (Saldo Inicial)", initial.long_term_receivables),
            ("1.02.002", "Investimentos LP (Saldo Inicial)", initial.long_term_investments),
        ]

        for code, name, amount in items_nao_circulante:
            val = Decimal(str(amount or 0))
            if val != Decimal("0"):
                bs.ativo_nao_circulante += val
                bs.asset_noncurrent_lines.append(BalanceSheetLine(code=code, name=name, balance=val, level=2))

        # === IMOBILIZADO ===
        items_imobilizado = [
            ("1.02.02.001", "Terrenos (Saldo Inicial)", initial.fixed_assets_land),
            ("1.02.02.002", "Prédios/Construções (Saldo Inicial)", initial.fixed_assets_buildings),
            ("1.02.02.003", "Máquinas e Equipamentos (Saldo Inicial)", initial.fixed_assets_machinery),
            ("1.02.02.004", "Veículos (Saldo Inicial)", initial.fixed_assets_vehicles),
            ("1.02.02.005", "Móveis e Utensílios (Saldo Inicial)", initial.fixed_assets_furniture),
            ("1.02.02.006", "Computadores/TI (Saldo Inicial)", initial.fixed_assets_computers),
            ("1.02.02.007", "Outros Imobilizados (Saldo Inicial)", initial.fixed_assets_other),
            ("1.02.02.099", "(-) Depreciação Acumulada (Saldo Inicial)", Decimal(str(initial.accumulated_depreciation or 0)) * Decimal("-1")),
        ]

        for code, name, amount in items_imobilizado:
            val = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
            if val != Decimal("0"):
                bs.imobilizado += val
                bs.imobilizado_lines.append(BalanceSheetLine(code=code, name=name, balance=val, level=2))

        # === INTANGÍVEL ===
        items_intangivel = [
            ("1.02.03.001", "Ativos Intangíveis (Saldo Inicial)", initial.intangible_assets),
            ("1.02.03.099", "(-) Amortização Acumulada (Saldo Inicial)", Decimal(str(initial.accumulated_amortization or 0)) * Decimal("-1")),
        ]

        for code, name, amount in items_intangivel:
            val = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
            if val != Decimal("0"):
                bs.intangivel += val
                bs.intangivel_lines.append(BalanceSheetLine(code=code, name=name, balance=val, level=2))

        # === PASSIVO CIRCULANTE ===
        items_passivo_circ = [
            ("2.01.001", "Fornecedores (Saldo Inicial)", initial.suppliers_payable),
            ("2.01.002", "Empréstimos CP (Saldo Inicial)", initial.short_term_loans),
            ("2.01.003", "Obrigações Trabalhistas (Saldo Inicial)", initial.labor_obligations),
            ("2.01.004", "Obrigações Fiscais (Saldo Inicial)", initial.tax_obligations),
            ("2.01.005", "Outras Contas a Pagar (Saldo Inicial)", initial.other_current_liabilities),
        ]

        for code, name, amount in items_passivo_circ:
            val = Decimal(str(amount or 0))
            if val != Decimal("0"):
                bs.passivo_circulante += val
                bs.liability_lines.append(BalanceSheetLine(code=code, name=name, balance=val, level=2))

        # === PASSIVO NÃO CIRCULANTE ===
        # Codes aligned with chart_of_accounts.py: 2.02.001 = Empréstimos, 2.02.002 = Financiamentos,
        # 2.02.003 = Provisões LP, 2.02.004 = Passivos Fiscais Diferidos
        emp_fin_lp = Decimal(str(initial.long_term_loans or 0)) + Decimal(str(initial.long_term_financing or 0))
        # Use getattr for V3 columns (provisions_long_term, deferred_tax_liabilities)
        # to avoid crash if migration c5d6e7f8a9b0 hasn't run yet
        items_passivo_nc = [
            ("2.02.001", "Empréstimos e Financiamentos (LP)", emp_fin_lp),
            ("2.02.003", "Provisões (LP)", getattr(initial, 'provisions_long_term', 0)),
            ("2.02.004", "Passivos Fiscais Diferidos", getattr(initial, 'deferred_tax_liabilities', 0)),
        ]

        for code, name, amount in items_passivo_nc:
            val = Decimal(str(amount or 0))
            if val != Decimal("0"):
                bs.passivo_nao_circulante += val
                bs.liability_noncurrent_lines.append(BalanceSheetLine(code=code, name=name, balance=val, level=2))

        # === PATRIMÔNIO LÍQUIDO ===
        # PL = Capital Social (from CNPJ API) + Reservas e Ajustes (user) + Lucros/Prejuízos (plug number)
        total_assets_initial = (
            sum(Decimal(str(getattr(initial, f) or 0)) for f in [
                'cash_and_equivalents', 'short_term_investments', 'accounts_receivable',
                'inventory', 'prepaid_expenses', 'long_term_receivables', 'long_term_investments',
                'fixed_assets_land', 'fixed_assets_buildings', 'fixed_assets_machinery',
                'fixed_assets_vehicles', 'fixed_assets_furniture', 'fixed_assets_computers',
                'fixed_assets_other', 'intangible_assets',
            ])
            + bank_total
            - Decimal(str(initial.accumulated_depreciation or 0))
            - Decimal(str(initial.accumulated_amortization or 0))
        )

        total_liabilities_initial = sum(Decimal(str(getattr(initial, f) or 0)) for f in [
            'suppliers_payable', 'short_term_loans', 'labor_obligations',
            'tax_obligations', 'other_current_liabilities', 'long_term_loans',
            'long_term_financing', 'provisions_long_term', 'deferred_tax_liabilities',
        ])

        equity_initial = total_assets_initial - total_liabilities_initial

        # Capital Social from the organization record
        capital_social = Decimal("0")
        if self.org_id:
            from database import Organization
            org = self.db.query(Organization).filter(Organization.id == self.org_id).first()
            if org and org.capital_social:
                capital_social = Decimal(str(org.capital_social))

        # Codes aligned with chart_of_accounts.py: 3.01.001 = Capital Social,
        # 3.02.001 = Reservas de Capital, 3.04.001 = Lucros, 3.04.002 = Prejuízos
        if capital_social != Decimal("0"):
            bs.patrimonio_liquido += capital_social
            bs.equity_lines.append(BalanceSheetLine(
                code="3.01.001", name="Capital Social", balance=capital_social, level=2
            ))

        # Reservas e Ajustes (user-supplied, V3 column - safe getattr for pre-migration compat)
        reserves = Decimal(str(getattr(initial, 'reserves_and_adjustments', 0) or 0))
        if reserves != Decimal("0"):
            bs.patrimonio_liquido += reserves
            bs.equity_lines.append(BalanceSheetLine(
                code="3.02.001", name="Reservas e Ajustes", balance=reserves, level=2
            ))

        # Lucro ou prejuízo do exercício = plug number to balance the sheet
        retained = equity_initial - capital_social - reserves
        if retained != Decimal("0"):
            bs.patrimonio_liquido += retained
            if retained > Decimal("0"):
                bs.equity_lines.append(BalanceSheetLine(
                    code="3.04.001", name="Lucro ou prejuízo do exercício", balance=retained, level=2
                ))
            else:
                bs.equity_lines.append(BalanceSheetLine(
                    code="3.04.002", name="Lucro ou prejuízo do exercício", balance=retained, level=2
                ))

    def _populate_from_journal_entries(self, bs: BalanceSheet, accounts: List[Dict]):
        """Populate balance sheet from journal entry data"""
        revenues = Decimal("0")
        expenses = Decimal("0")

        for account in accounts:
            account_type = account["type"]
            balance = account["balance"]
            code = account["code"]

            if balance == Decimal("0"):
                continue

            line = BalanceSheetLine(
                code=code, name=account["name"], balance=balance, level=2
            )

            if account_type == AccountType.ATIVO_CIRCULANTE.value:
                bs.ativo_circulante += balance
                bs.asset_lines.append(line)
            elif account_type == AccountType.ATIVO_NAO_CIRCULANTE.value:
                if code.startswith("1.02.02"):
                    bs.imobilizado += balance
                    bs.imobilizado_lines.append(line)
                elif code.startswith("1.02.03"):
                    bs.intangivel += balance
                    bs.intangivel_lines.append(line)
                else:
                    bs.ativo_nao_circulante += balance
                    bs.asset_noncurrent_lines.append(line)
            elif account_type == AccountType.PASSIVO_CIRCULANTE.value:
                bs.passivo_circulante += balance
                bs.liability_lines.append(line)
            elif account_type == AccountType.PASSIVO_NAO_CIRCULANTE.value:
                bs.passivo_nao_circulante += balance
                bs.liability_noncurrent_lines.append(line)
            elif account_type == AccountType.PATRIMONIO_LIQUIDO.value:
                bs.patrimonio_liquido += balance
                bs.equity_lines.append(line)
            elif account_type == AccountType.RECEITA.value:
                revenues += balance
            elif account_type == AccountType.DESPESA.value:
                expenses += balance

        net_income = revenues - expenses
        if net_income != Decimal("0"):
            net_income_line = BalanceSheetLine(
                code="3.04.001", name="Lucros do Exercício", balance=net_income, level=2
            )
            bs.patrimonio_liquido += net_income
            bs.equity_lines.append(net_income_line)

    def _populate_from_documents(self, bs: BalanceSheet, ref_date: date):
        """
        Derive balance sheet from document transactions (fallback).

        Uses the same document data source as DRE.
        Accumulates all income/expenses up to the reference date
        to compute net result → Patrimônio Líquido.
        Income goes to Caixa (Ativo Circulante), expenses reduce it.
        Expands multi-row documents (Excel ledgers) into individual transactions.
        """
        from models import FinancialDocument

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

        total_income = Decimal("0")
        total_expenses = Decimal("0")

        def _process_transaction(issue_date_val, amount_val, txn_type):
            """Process a single transaction, filtering by date and accumulating totals."""
            nonlocal total_income, total_expenses

            if issue_date_val is None:
                return
            if isinstance(issue_date_val, str):
                try:
                    issue_date_val = datetime.fromisoformat(issue_date_val).date()
                except (ValueError, TypeError):
                    return
            elif isinstance(issue_date_val, datetime):
                issue_date_val = issue_date_val.date()

            if issue_date_val > ref_date:
                return

            amount = Decimal(str(amount_val or 0))
            if txn_type in ("income", "receita"):
                total_income += amount
            else:
                total_expenses += amount

        for doc in documents:
            try:
                data_dict = json.loads(doc.extracted_data_json)
                extracted = FinancialDocument(**data_dict)

                # Check for inner transactions (multi-row documents like Excel ledgers)
                inner_txns = data_dict.get("transactions")
                if inner_txns and isinstance(inner_txns, list) and len(inner_txns) > 0:
                    for txn in inner_txns:
                        _process_transaction(
                            txn.get("date"),
                            txn.get("amount", 0),
                            txn.get("transaction_type") or extracted.transaction_type,
                        )
                else:
                    _process_transaction(
                        extracted.issue_date,
                        extracted.total_amount,
                        extracted.transaction_type,
                    )

            except Exception as e:
                logger.warning(f"Error processing document {doc.id} for balance sheet: {e}")
                continue

        # Build the balance sheet from accumulated data
        net_result = total_income - total_expenses

        if net_result > Decimal("0"):
            # Positive: company has net cash
            # Assets = net_result (cash), PL = net_result (retained earnings)
            # Balance: net_result = 0 + net_result ✓
            bs.ativo_circulante = net_result
            bs.asset_lines.append(BalanceSheetLine(
                code="1.01.001", name="Caixa e Equivalentes de Caixa",
                balance=net_result, level=2
            ))
            bs.patrimonio_liquido = net_result
            bs.equity_lines.append(BalanceSheetLine(
                code="3.04.001", name="Lucros Acumulados",
                balance=net_result, level=2
            ))
        elif net_result < Decimal("0"):
            # Negative: company has accumulated losses
            # Assets = 0 (no cash), Liabilities = |net_result|, PL = net_result
            # Balance: 0 = |net_result| + net_result = 0 ✓
            abs_deficit = abs(net_result)
            bs.passivo_circulante = abs_deficit
            bs.liability_lines.append(BalanceSheetLine(
                code="2.01.005", name="Obrigações a Pagar (Déficit Operacional)",
                balance=abs_deficit, level=2
            ))
            bs.patrimonio_liquido = net_result
            bs.equity_lines.append(BalanceSheetLine(
                code="3.04.001", name="Lucro ou prejuízo do exercício",
                balance=net_result, level=2
            ))

    def _get_account_balances(self, reference_date: date) -> List[Dict]:
        """
        Get balances for all accounts as of a specific date

        OPTIMIZED: Uses a single batch query to calculate all balances at once
        instead of N+1 queries (one per account)
        """
        from sqlalchemy import case, func

        # Convert date to datetime for comparison
        ref_datetime = datetime.combine(reference_date, datetime.max.time())

        # OPTIMIZED: Single query that gets ALL account balances in one shot
        balance_query = (
            self.db.query(
                JournalEntryLine.account_id,
                func.sum(JournalEntryLine.debit_amount).label("total_debits"),
                func.sum(JournalEntryLine.credit_amount).label("total_credits"),
            )
            .join(JournalEntry)
            .filter(
                and_(
                    JournalEntry.user_id == self.user_id,
                    JournalEntry.entry_date <= ref_datetime,
                    JournalEntry.is_posted == True,
                    JournalEntry.is_reversed == False,
                )
            )
            .group_by(JournalEntryLine.account_id)
            .all()
        )

        # Create a dict of account_id -> (debits, credits) for fast lookup
        balance_map = {
            row.account_id: (row.total_debits or 0, row.total_credits or 0)
            for row in balance_query
        }

        # Get all user's accounts
        accounts = (
            self.db.query(ChartOfAccountsEntry)
            .filter(
                ChartOfAccountsEntry.user_id == self.user_id,
                ChartOfAccountsEntry.is_active == True,
            )
            .all()
        )

        result = []

        for account in accounts:
            # Get balances from pre-calculated map (no additional query!)
            total_debits, total_credits = balance_map.get(account.id, (0, 0))

            # Calculate balance based on account nature
            if account.account_nature == "debit":
                balance_cents = total_debits - total_credits
            else:
                balance_cents = total_credits - total_debits

            # Convert from cents to decimal
            balance = Decimal(balance_cents) / Decimal("100")

            result.append(
                {
                    "id": account.id,
                    "code": account.account_code,
                    "name": account.account_name,
                    "type": account.account_type,
                    "nature": account.account_nature,
                    "balance": balance,
                }
            )

        return result

    def _calculate_account_balance_at_date(
        self, account_id: int, up_to_date: datetime
    ) -> Decimal:
        """
        Calculate account balance from journal entries up to a specific date
        """
        lines = (
            self.db.query(JournalEntryLine)
            .join(JournalEntry)
            .filter(
                and_(
                    JournalEntryLine.account_id == account_id,
                    JournalEntry.user_id == self.user_id,
                    JournalEntry.entry_date <= up_to_date,
                    JournalEntry.is_posted == True,
                    JournalEntry.is_reversed == False,
                )
            )
            .all()
        )

        total_debits = sum(line.debit_amount for line in lines)
        total_credits = sum(line.credit_amount for line in lines)

        account = self.db.query(ChartOfAccountsEntry).get(account_id)

        if account.account_nature == "debit":
            balance_cents = total_debits - total_credits
        else:
            balance_cents = total_credits - total_debits

        return Decimal(balance_cents) / Decimal(100)

    def get_account_ledger(
        self,
        account_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict]:
        """
        Get detailed ledger for a specific account (Razão)
        """
        account = (
            self.db.query(ChartOfAccountsEntry)
            .filter(
                ChartOfAccountsEntry.user_id == self.user_id,
                ChartOfAccountsEntry.account_code == account_code,
            )
            .first()
        )

        if not account:
            raise ValueError(f"Account {account_code} not found")

        query = (
            self.db.query(JournalEntryLine, JournalEntry)
            .join(JournalEntry)
            .filter(
                and_(
                    JournalEntryLine.account_id == account.id,
                    JournalEntry.user_id == self.user_id,
                    JournalEntry.is_posted == True,
                )
            )
        )

        if start_date:
            start_datetime = datetime.combine(start_date, datetime.min.time())
            query = query.filter(JournalEntry.entry_date >= start_datetime)

        if end_date:
            end_datetime = datetime.combine(end_date, datetime.max.time())
            query = query.filter(JournalEntry.entry_date <= end_datetime)

        query = query.order_by(JournalEntry.entry_date.asc())

        results = query.all()

        ledger = []
        running_balance = Decimal("0")

        for line, entry in results:
            debit = Decimal(line.debit_amount) / Decimal(100)
            credit = Decimal(line.credit_amount) / Decimal(100)

            if account.account_nature == "debit":
                running_balance += debit - credit
            else:
                running_balance += credit - debit

            ledger.append(
                {
                    "date": entry.entry_date.date().isoformat(),
                    "description": entry.description,
                    "debit": float(debit),
                    "credit": float(credit),
                    "balance": float(running_balance),
                    "entry_id": entry.id,
                    "source_type": entry.source_type,
                }
            )

        return ledger

    def get_trial_balance(self, reference_date: date) -> List[Dict]:
        """
        Get trial balance (Balancete de Verificação)
        """
        ref_datetime = datetime.combine(reference_date, datetime.max.time())

        accounts = (
            self.db.query(ChartOfAccountsEntry)
            .filter(
                ChartOfAccountsEntry.user_id == self.user_id,
                ChartOfAccountsEntry.is_active == True,
            )
            .all()
        )

        trial_balance = []

        for account in accounts:
            lines = (
                self.db.query(
                    func.sum(JournalEntryLine.debit_amount).label("total_debits"),
                    func.sum(JournalEntryLine.credit_amount).label("total_credits"),
                )
                .join(JournalEntry)
                .filter(
                    and_(
                        JournalEntryLine.account_id == account.id,
                        JournalEntry.user_id == self.user_id,
                        JournalEntry.entry_date <= ref_datetime,
                        JournalEntry.is_posted == True,
                        JournalEntry.is_reversed == False,
                    )
                )
                .first()
            )

            total_debits = Decimal(lines.total_debits or 0) / Decimal(100)
            total_credits = Decimal(lines.total_credits or 0) / Decimal(100)

            if account.account_nature == "debit":
                balance = total_debits - total_credits
            else:
                balance = total_credits - total_debits

            if balance == Decimal("0"):
                continue

            debit_balance = (
                balance
                if balance > 0 and account.account_nature == "debit"
                else Decimal("0")
            )
            credit_balance = (
                balance
                if balance > 0 and account.account_nature == "credit"
                else Decimal("0")
            )

            trial_balance.append(
                {
                    "account_code": account.account_code,
                    "account_name": account.account_name,
                    "account_type": account.account_type,
                    "debit_balance": float(debit_balance),
                    "credit_balance": float(credit_balance),
                }
            )

        return trial_balance


def calculate_balance_sheet(
    db: Session,
    user_id: int,
    reference_date: date,
    company_name: Optional[str] = None,
    cnpj: Optional[str] = None,
    org_id: Optional[int] = None,
) -> BalanceSheet:
    """
    Convenience function to calculate balance sheet

    Args:
        db: Database session
        user_id: User ID
        reference_date: Date for balance sheet
        company_name: Company name
        cnpj: CNPJ
        org_id: Organization ID (for loading initial balances)

    Returns:
        BalanceSheet object
    """
    calculator = BalanceSheetCalculator(db, user_id, org_id=org_id)
    return calculator.calculate_balance_sheet(reference_date, company_name, cnpj)
