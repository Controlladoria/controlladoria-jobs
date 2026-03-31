"""
Financial Data Validation Engine
Hospital-grade validation for accuracy and compliance
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple, Any, Optional


class FinancialValidator:
    """Validates financial documents for hospitals"""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate_document(self, data: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
        """
        Comprehensive validation of a financial document

        Returns:
            (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []

        # Required field validation
        self._validate_required_fields(data)

        # Date validation
        self._validate_dates(data)

        # Amount validation
        self._validate_amounts(data)

        # Line items validation (if present)
        if data.get("line_items"):
            self._validate_line_items(data)

        # Balance sheet equation (if applicable)
        if data.get("document_type") == "balance_sheet":
            self._validate_balance_sheet(data)

        # Transaction type validation
        self._validate_transaction_type(data)

        # CNPJ/CPF validation
        self._validate_tax_ids(data)

        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings

    def _validate_required_fields(self, data: Dict[str, Any]):
        """Validate required fields are present"""
        required = ["total_amount"]

        for field in required:
            if field not in data or data[field] is None:
                self.errors.append(f"Campo obrigatório ausente: {field}")

        # Warn if optional but recommended fields are missing
        recommended = ["issue_date", "transaction_type", "category"]
        for field in recommended:
            if field not in data or data[field] is None:
                self.warnings.append(f"Campo recomendado ausente: {field}")

    def _validate_dates(self, data: Dict[str, Any]):
        """Validate date fields"""
        date_fields = ["issue_date", "due_date", "payment_date"]

        for field in date_fields:
            if field in data and data[field]:
                try:
                    # Parse ISO date
                    date_obj = datetime.fromisoformat(data[field].replace("Z", "+00:00"))

                    # Warn if date is in the future
                    if date_obj > datetime.now() + timedelta(days=1):
                        self.warnings.append(f"{field} está no futuro: {data[field]}")

                    # Warn if date is very old (>10 years)
                    if date_obj < datetime.now() - timedelta(days=3650):
                        self.warnings.append(f"{field} é muito antiga (>10 anos): {data[field]}")

                except (ValueError, AttributeError) as e:
                    self.errors.append(f"Data inválida em {field}: {data[field]}")

    def _validate_amounts(self, data: Dict[str, Any]):
        """Validate monetary amounts"""
        try:
            total = Decimal(str(data.get("total_amount", 0)))

            if total < 0:
                self.errors.append("Valor total não pode ser negativo")

            if total == 0:
                self.warnings.append("Valor total é zero")

            if total > Decimal("1000000000"):  # 1 billion
                self.warnings.append("Valor muito alto (>R$ 1 bilhão) - verificar se está correto")

            # Validate subtotal + tax = total (if present)
            if "subtotal" in data and "tax_amount" in data:
                subtotal = Decimal(str(data["subtotal"]))
                tax = Decimal(str(data["tax_amount"]))
                discount = Decimal(str(data.get("discount", 0)))

                calculated_total = subtotal + tax - discount
                difference = abs(calculated_total - total)

                # Allow 0.01 difference for rounding
                if difference > Decimal("0.01"):
                    self.errors.append(
                        f"Subtotal + Imposto - Desconto ({calculated_total}) ≠ Total ({total})"
                    )

        except (ValueError, TypeError, ArithmeticError) as e:
            # Show clean error message instead of raw exception internals
            self.warnings.append("Aviso: alguns valores monetários não puderam ser validados (formato inválido)")
            import logging
            logging.getLogger(__name__).warning(f"Amount validation error: {type(e).__name__}: {e}")

    def _validate_line_items(self, data: Dict[str, Any]):
        """Validate line items sum to total"""
        try:
            line_items = data.get("line_items", [])
            if not line_items:
                return

            line_items_total = Decimal("0")
            for idx, item in enumerate(line_items):
                if "total_price" in item and item["total_price"] is not None:
                    line_items_total += Decimal(str(item["total_price"]))

                # Validate quantity * unit_price = total_price
                if all(k in item for k in ["quantity", "unit_price", "total_price"]):
                    qty = Decimal(str(item["quantity"]))
                    price = Decimal(str(item["unit_price"]))
                    total = Decimal(str(item["total_price"]))

                    calculated = qty * price
                    if abs(calculated - total) > Decimal("0.01"):
                        self.warnings.append(
                            f"Item #{idx+1}: Qtd × Preço ({calculated}) ≠ Total ({total})"
                        )

            # Check if line items sum matches subtotal or total
            doc_total = Decimal(str(data.get("total_amount", 0)))
            doc_subtotal = Decimal(str(data.get("subtotal", 0))) if "subtotal" in data else doc_total

            difference = abs(line_items_total - doc_subtotal)
            if difference > Decimal("0.01") and line_items_total > 0:
                self.warnings.append(
                    f"Soma dos itens ({line_items_total}) ≠ Subtotal ({doc_subtotal})"
                )

        except (ValueError, TypeError, ArithmeticError) as e:
            self.warnings.append(f"Erro ao validar itens: {str(e)}")

    def _validate_balance_sheet(self, data: Dict[str, Any]):
        """Validate balance sheet equation: Assets = Liabilities + Equity"""
        try:
            assets = Decimal(str(data.get("total_assets", 0)))
            liabilities = Decimal(str(data.get("total_liabilities", 0)))
            equity = Decimal(str(data.get("total_equity", 0)))

            difference = abs(assets - (liabilities + equity))

            if difference > Decimal("0.01"):
                self.errors.append(
                    f"Equação contábil não balanceada: Ativo ({assets}) ≠ Passivo + PL ({liabilities + equity})"
                )

        except (ValueError, TypeError, ArithmeticError):
            pass  # Balance sheet fields might not be present

    def _validate_transaction_type(self, data: Dict[str, Any]):
        """Validate transaction type logic"""
        txn_type = data.get("transaction_type")

        # Accept both English and Portuguese transaction types
        _valid_types = {
            "income", "expense",
            "receita", "despesa", "gasto", "custo", "investimento", "perda",
            "entrada", "saída", "saida", "crédito", "credito", "débito", "debito",
            "revenue", "cost", "recebimento",
        }
        if txn_type and str(txn_type).lower().strip() not in _valid_types:
            self.warnings.append(f"Tipo de transação não reconhecido: {txn_type} - verificar manualmente")

        # Check if confidence is low and type might be wrong
        confidence = data.get("confidence_score")
        if confidence is not None and confidence < 0.7 and txn_type:
            self.warnings.append(
                f"Baixa confiança ({confidence:.0%}) no tipo de transação - verificar manualmente"
            )

    def _validate_tax_ids(self, data: Dict[str, Any]):
        """Validate Brazilian CNPJ and CPF with user-friendly error messages"""
        issuer = data.get("issuer", {})
        recipient = data.get("recipient", {})

        for entity_name, entity in [("Emissor", issuer), ("Destinatário", recipient)]:
            tax_id = entity.get("tax_id") if isinstance(entity, dict) else None
            if tax_id:
                tax_id_clean = re.sub(r"[^\d]", "", tax_id)

                # CNPJ has 14 digits
                if len(tax_id_clean) == 14:
                    if not self._validate_cnpj(tax_id_clean):
                        self.warnings.append(
                            f"{entity_name}: CNPJ inválido - O número {tax_id} não passou na validação dos dígitos verificadores. "
                            f"Isto pode ser um CNPJ de teste, fictício, ou digitado incorretamente no documento."
                        )

                # CPF has 11 digits
                elif len(tax_id_clean) == 11:
                    if not self._validate_cpf(tax_id_clean):
                        self.warnings.append(
                            f"{entity_name}: CPF inválido - O número {tax_id} não passou na validação dos dígitos verificadores. "
                            f"Isto pode ser um CPF de teste, fictício, ou digitado incorretamente no documento."
                        )

                elif tax_id_clean:  # Has digits but wrong length
                    self.warnings.append(
                        f"{entity_name}: CNPJ/CPF com formato inválido - O número {tax_id} tem {len(tax_id_clean)} dígitos, "
                        f"mas CNPJ deve ter 14 dígitos e CPF deve ter 11 dígitos."
                    )

    def _validate_cnpj(self, cnpj: str) -> bool:
        """Validate CNPJ checksum"""
        if len(cnpj) != 14 or not cnpj.isdigit():
            return False

        # Check for known invalid CNPJs (all same digit)
        if len(set(cnpj)) == 1:
            return False

        # Calculate first check digit
        weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        sum1 = sum(int(cnpj[i]) * weights[i] for i in range(12))
        digit1 = 11 - (sum1 % 11)
        digit1 = 0 if digit1 >= 10 else digit1

        if int(cnpj[12]) != digit1:
            return False

        # Calculate second check digit
        weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        sum2 = sum(int(cnpj[i]) * weights[i] for i in range(13))
        digit2 = 11 - (sum2 % 11)
        digit2 = 0 if digit2 >= 10 else digit2

        return int(cnpj[13]) == digit2

    def _validate_cpf(self, cpf: str) -> bool:
        """Validate CPF checksum"""
        if len(cpf) != 11 or not cpf.isdigit():
            return False

        # Check for known invalid CPFs (all same digit)
        if len(set(cpf)) == 1:
            return False

        # Calculate first check digit
        sum1 = sum(int(cpf[i]) * (10 - i) for i in range(9))
        digit1 = 11 - (sum1 % 11)
        digit1 = 0 if digit1 >= 10 else digit1

        if int(cpf[9]) != digit1:
            return False

        # Calculate second check digit
        sum2 = sum(int(cpf[i]) * (11 - i) for i in range(10))
        digit2 = 11 - (sum2 % 11)
        digit2 = 0 if digit2 >= 10 else digit2

        return int(cpf[10]) == digit2


class DuplicateDetector:
    """Detects potential duplicate documents"""

    @staticmethod
    def find_duplicates(
        documents: List[Dict[str, Any]], new_doc: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Find potential duplicates of a new document

        Returns list of potentially duplicate documents with similarity score
        """
        duplicates = []

        new_amount = Decimal(str(new_doc.get("total_amount", 0)))
        new_date = new_doc.get("issue_date")
        new_number = new_doc.get("document_number", "").lower()
        new_issuer = new_doc.get("issuer", {}).get("tax_id", "") if isinstance(new_doc.get("issuer"), dict) else ""

        for doc in documents:
            similarity_score = 0
            reasons = []

            # Same amount (high weight)
            if "total_amount" in doc:
                doc_amount = Decimal(str(doc["total_amount"]))
                if abs(doc_amount - new_amount) < Decimal("0.01"):
                    similarity_score += 40
                    reasons.append("mesmo valor")

            # Same date (medium weight)
            if doc.get("issue_date") == new_date and new_date:
                similarity_score += 30
                reasons.append("mesma data")

            # Same document number (very high weight)
            doc_number = doc.get("document_number", "").lower()
            if doc_number and new_number and doc_number == new_number:
                similarity_score += 50
                reasons.append("mesmo número")

            # Same issuer (medium weight)
            doc_issuer = doc.get("issuer", {}).get("tax_id", "") if isinstance(doc.get("issuer"), dict) else ""
            if doc_issuer and new_issuer and doc_issuer == new_issuer:
                similarity_score += 20
                reasons.append("mesmo emissor")

            # Consider it a potential duplicate if similarity > 60%
            if similarity_score >= 60:
                duplicates.append(
                    {
                        "document": doc,
                        "similarity_score": similarity_score,
                        "reasons": reasons,
                    }
                )

        # Sort by similarity score (highest first)
        duplicates.sort(key=lambda x: x["similarity_score"], reverse=True)

        return duplicates
