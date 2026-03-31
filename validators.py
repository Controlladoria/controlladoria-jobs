"""
Week 3: Data Validation Rules
Validates extracted financial data for consistency and accuracy
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from models import FinancialDocument


class ValidationError:
    """Represents a validation error"""

    def __init__(self, field: str, message: str, severity: str = "error"):
        self.field = field
        self.message = message
        self.severity = severity  # "error", "warning", "info"

    def to_dict(self):
        return {"field": self.field, "message": self.message, "severity": self.severity}


class FinancialDataValidator:
    """Validates financial document data"""

    @staticmethod
    def validate_cpf(cpf: str) -> bool:
        """
        Validate Brazilian CPF (Cadastro de Pessoas Físicas)
        Format: XXX.XXX.XXX-XX
        """
        if not cpf:
            return True  # Optional field

        # Remove formatting
        cpf_digits = re.sub(r"[^0-9]", "", cpf)

        # Check length
        if len(cpf_digits) != 11:
            return False

        # Check if all digits are the same
        if cpf_digits == cpf_digits[0] * 11:
            return False

        # Validate check digits
        def calc_digit(cpf_partial, multiplier):
            total = sum(
                int(digit) * (multiplier - i) for i, digit in enumerate(cpf_partial)
            )
            remainder = total % 11
            return 0 if remainder < 2 else 11 - remainder

        # First check digit
        if int(cpf_digits[9]) != calc_digit(cpf_digits[:9], 10):
            return False

        # Second check digit
        if int(cpf_digits[10]) != calc_digit(cpf_digits[:10], 11):
            return False

        return True

    @staticmethod
    def validate_cnpj(cnpj: str) -> bool:
        """
        Validate Brazilian CNPJ (Cadastro Nacional da Pessoa Jurídica)
        Format: XX.XXX.XXX/XXXX-XX
        """
        if not cnpj:
            return True  # Optional field

        # Remove formatting
        cnpj_digits = re.sub(r"[^0-9]", "", cnpj)

        # Check length
        if len(cnpj_digits) != 14:
            return False

        # Check if all digits are the same
        if cnpj_digits == cnpj_digits[0] * 14:
            return False

        # Validate check digits
        def calc_digit(cnpj_partial, weights):
            total = sum(
                int(digit) * weight for digit, weight in zip(cnpj_partial, weights)
            )
            remainder = total % 11
            return 0 if remainder < 2 else 11 - remainder

        # First check digit
        weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if int(cnpj_digits[12]) != calc_digit(cnpj_digits[:12], weights1):
            return False

        # Second check digit
        weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if int(cnpj_digits[13]) != calc_digit(cnpj_digits[:13], weights2):
            return False

        return True

    @staticmethod
    def validate_date(date_str: str) -> bool:
        """Validate ISO date format (YYYY-MM-DD)"""
        if not date_str:
            return True  # Optional field

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    @staticmethod
    def validate_document(doc: FinancialDocument) -> List[ValidationError]:
        """
        Validate a financial document
        Returns list of validation errors (empty if valid)
        """
        errors = []

        # 1. Validate total amount
        if doc.total_amount is None or doc.total_amount <= 0:
            errors.append(
                ValidationError(
                    "total_amount", "Total amount must be greater than zero", "error"
                )
            )

        # 2. Validate dates
        if doc.issue_date and not FinancialDataValidator.validate_date(doc.issue_date):
            errors.append(
                ValidationError(
                    "issue_date", "Invalid date format. Use YYYY-MM-DD", "error"
                )
            )

        if doc.payment_info and doc.payment_info.due_date:
            if not FinancialDataValidator.validate_date(doc.payment_info.due_date):
                errors.append(
                    ValidationError(
                        "payment_info.due_date",
                        "Invalid date format. Use YYYY-MM-DD",
                        "error",
                    )
                )

        if doc.payment_info and doc.payment_info.payment_date:
            if not FinancialDataValidator.validate_date(doc.payment_info.payment_date):
                errors.append(
                    ValidationError(
                        "payment_info.payment_date",
                        "Invalid date format. Use YYYY-MM-DD",
                        "error",
                    )
                )

        # 3. Validate tax IDs
        # CNPJ/CPF validation (can be disabled via config for testing)
        from config import settings
        if settings.enable_cnpj_validation:
            if doc.issuer and doc.issuer.tax_id:
                tax_id = doc.issuer.tax_id
                if len(re.sub(r"[^0-9]", "", tax_id)) == 11:
                    if not FinancialDataValidator.validate_cpf(tax_id):
                        errors.append(
                            ValidationError(
                                "issuer.tax_id",
                                "Invalid CPF format or check digits",
                                "warning",
                            )
                        )
                elif len(re.sub(r"[^0-9]", "", tax_id)) == 14:
                    if not FinancialDataValidator.validate_cnpj(tax_id):
                        errors.append(
                            ValidationError(
                                "issuer.tax_id",
                                "Invalid CNPJ format or check digits",
                                "warning",
                            )
                        )

            if doc.recipient and doc.recipient.tax_id:
                tax_id = doc.recipient.tax_id
                if len(re.sub(r"[^0-9]", "", tax_id)) == 11:
                    if not FinancialDataValidator.validate_cpf(tax_id):
                        errors.append(
                            ValidationError(
                                "recipient.tax_id",
                                "Invalid CPF format or check digits",
                                "warning",
                            )
                        )
                elif len(re.sub(r"[^0-9]", "", tax_id)) == 14:
                    if not FinancialDataValidator.validate_cnpj(tax_id):
                        errors.append(
                            ValidationError(
                                "recipient.tax_id",
                                "Invalid CNPJ format or check digits",
                                "warning",
                            )
                        )

        # 4. Validate line items sum
        if doc.line_items:
            line_items_total = Decimal("0")
            for item in doc.line_items:
                if item.total_price:
                    line_items_total += item.total_price

            # Check if line items total matches subtotal
            if doc.subtotal and line_items_total > 0:
                difference = abs(line_items_total - doc.subtotal)
                if difference > Decimal("0.01"):  # Allow small rounding differences
                    errors.append(
                        ValidationError(
                            "line_items",
                            f"Line items total ({line_items_total}) doesn't match subtotal ({doc.subtotal})",
                            "warning",
                        )
                    )

        # 5. Validate subtotal + tax = total
        if doc.subtotal and doc.tax_amount:
            calculated_total = doc.subtotal + doc.tax_amount
            if doc.discount:
                calculated_total -= doc.discount

            difference = abs(calculated_total - doc.total_amount)
            if difference > Decimal("0.01"):  # Allow small rounding differences
                errors.append(
                    ValidationError(
                        "total_amount",
                        f"Calculated total ({calculated_total}) doesn't match declared total ({doc.total_amount})",
                        "warning",
                    )
                )

        # 6. Validate tax rate
        if doc.tax_rate and doc.subtotal and doc.tax_amount:
            calculated_tax = doc.subtotal * Decimal(str(doc.tax_rate))
            difference = abs(calculated_tax - doc.tax_amount)
            if difference > Decimal("0.01"):
                errors.append(
                    ValidationError(
                        "tax_amount",
                        f"Tax rate {doc.tax_rate * 100}% doesn't match tax amount",
                        "info",
                    )
                )

        # 7. Validate payment status consistency
        if doc.payment_info:
            if doc.payment_info.status == "paid" and not doc.payment_info.payment_date:
                errors.append(
                    ValidationError(
                        "payment_info.payment_date",
                        "Paid documents should have a payment date",
                        "warning",
                    )
                )

        # 8. Check for missing critical data
        if not doc.issuer or not doc.issuer.name:
            errors.append(
                ValidationError("issuer.name", "Issuer name is missing", "warning")
            )

        if not doc.issue_date:
            errors.append(
                ValidationError("issue_date", "Issue date is missing", "info")
            )

        return errors

    @staticmethod
    def get_validation_summary(errors: List[ValidationError]) -> Dict[str, Any]:
        """Get a summary of validation results"""
        error_count = sum(1 for e in errors if e.severity == "error")
        warning_count = sum(1 for e in errors if e.severity == "warning")
        info_count = sum(1 for e in errors if e.severity == "info")

        return {
            "is_valid": error_count == 0,
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "total_issues": len(errors),
            "errors": [e.to_dict() for e in errors],
        }
