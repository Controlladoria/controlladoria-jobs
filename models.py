"""
Data models for financial documents
Defines the structure of extracted data from Brazilian financial documents
(Notas Fiscais, Recibos, Boletos, etc.)

Note: All field names, variable names, and code are in English (best practice)
Only user-facing messages are translated to Portuguese
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional, Union

import bleach
from pydantic import BaseModel, EmailStr, Field, validator


def normalize_brazilian_decimal(value: str) -> str:
    """
    Normalize Brazilian decimal format to English format
    Brazilian: 1.234.567,89 (period for thousands, comma for decimal)
    English: 1234567.89 (no thousands separator, period for decimal)

    IMPORTANT: This handles BOTH formats:
    - Brazilian: "1.234,56" -> "1234.56"
    - Standard: "1234.56" -> "1234.56" (no change)

    Also handles common invalid formats:
    - Currency symbols: "$1,234.56" -> "1234.56"
    - Empty/whitespace: "" -> "0"
    - Text: "N/A", "---" -> "0"
    """
    if not isinstance(value, str):
        return str(value)

    value = value.strip()

    # Handle empty or invalid values
    if not value or value.lower() in ["", "n/a", "na", "none", "null", "---", "-"]:
        return "0"

    # Remove currency symbols and whitespace
    value = value.replace("$", "").replace("R$", "").replace("€", "").replace("£", "").strip()

    # Remove any non-numeric characters except period, comma, and minus
    import re
    value = re.sub(r'[^\d.,-]', '', value)

    # Handle empty after cleanup
    if not value:
        return "0"

    # If value has comma, it's Brazilian format (comma = decimal separator)
    if "," in value:
        # Remove all periods (thousands separators in Brazilian format)
        normalized = value.replace(".", "")
        # Replace comma with period (decimal separator)
        normalized = normalized.replace(",", ".")
        return normalized

    # If no comma, check if it's already in standard format (period = decimal)
    # Standard format examples: "1234.56", "102.37", "4724.38"
    # We DON'T want to remove the decimal point!
    # Only remove periods if there are multiple (thousands separators)
    if value.count(".") > 1:
        # Multiple periods = thousands separators (e.g., "1.234.567")
        return value.replace(".", "")

    # Single period or no period = already standard format
    return value


class LineItem(BaseModel):
    """Individual line item in an invoice or receipt"""

    description: str
    quantity: Optional[float] = None
    unit_price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    product_code: Optional[str] = None
    category: Optional[str] = None
    transaction_type: Optional[str] = None

    @validator("transaction_type", pre=True)
    def normalize_transaction_type(cls, v):
        """Normalize transaction types to 5 canonical Portuguese types"""
        if v is None:
            return None
        if isinstance(v, str):
            v_lower = v.lower().strip()
            income_aliases = {"income", "receita", "entrada", "crédito", "credito", "revenue", "credit"}
            expense_aliases = {"expense", "despesa", "saída", "saida", "débito", "debito", "debit", "gasto"}
            cost_aliases = {"custo", "cost"}
            if v_lower in income_aliases:
                return "receita"
            if v_lower == "investimento":
                return "investimento"
            if v_lower == "perda":
                return "perda"
            if v_lower in cost_aliases:
                return "custo"
            if v_lower in expense_aliases:
                return "despesa"
            return "despesa"
        return v

    @validator("unit_price", "total_price", pre=True)
    def normalize_decimal_fields(cls, v):
        """Normalize Brazilian decimal format before validation with error handling"""
        if v is None or isinstance(v, (int, float, Decimal)):
            return v
        if isinstance(v, str):
            try:
                normalized = normalize_brazilian_decimal(v)
                return Decimal(normalized) if normalized else None
            except (ValueError, Decimal.InvalidOperation) as e:
                # Log the error but don't fail - return None
                import logging
                logging.warning(f"Failed to convert decimal value '{v}': {e}")
                return None
        return v


class PaymentInfo(BaseModel):
    """Payment information"""

    status: Literal["paid", "unpaid", "partial", "pending"] = "pending"
    method: Optional[str] = None  # pix, boleto, credit_card, transfer, cash, etc.
    due_date: Optional[str] = None  # ISO format date (YYYY-MM-DD)
    payment_date: Optional[str] = None  # ISO format date (YYYY-MM-DD)

    @validator("status", pre=True)
    def normalize_status(cls, v):
        """Normalize status - convert None to default 'pending'"""
        if v is None or (isinstance(v, str) and v.strip().lower() in ["none", "null", "unknown", ""]):
            return "pending"
        return v


class CompanyInfo(BaseModel):
    """Company/Entity information (Brazilian format)"""

    name: Optional[str] = None  # Nome fantasia
    legal_name: Optional[str] = None  # Razão social
    tax_id: Optional[str] = None  # CNPJ (XX.XXX.XXX/XXXX-XX) or CPF (XXX.XXX.XXX-XX)
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class FinancialDocument(BaseModel):
    """
    Structured financial document model
    Represents invoices, receipts, expense reports, etc.
    """

    # Document metadata
    document_type: Literal[
        "invoice", "receipt", "expense", "statement", "transaction_ledger", "other"
    ]
    document_number: Optional[str] = None
    issue_date: Optional[str] = None  # ISO format date

    # Transaction classification
    transaction_type: Literal["receita", "despesa", "custo", "investimento", "perda"] = "despesa"
    category: Optional[str] = None  # e.g., "office_supplies", "utilities", "sales"
    department: Optional[str] = None  # Department/cost center for hospital tracking

    @validator("document_type", pre=True)
    def normalize_document_type(cls, v):
        """Normalize document_type from AI output to valid enum values"""
        valid_types = {"invoice", "receipt", "expense", "statement", "transaction_ledger", "other"}
        if v and isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in valid_types:
                return v_lower
            # Map AI-generated types to valid types
            type_mapping = {
                "boleto": "expense",
                "check": "expense",
                "cheque": "expense",
                "promissory_note": "expense",
                "fiscal_coupon": "receipt",
                "payment_proof": "receipt",
                "darf": "expense",
                "nota_fiscal": "invoice",
                "nfe": "invoice",
                "tax_payment": "expense",
                "bank_statement": "statement",
                "extrato": "statement",
                "comprovante": "receipt",
            }
            return type_mapping.get(v_lower, "other")
        return v

    @validator("transaction_type", pre=True)
    def normalize_transaction_type(cls, v):
        """Normalize transaction types to 5 canonical Portuguese types"""
        if v is None:
            return "despesa"
        if isinstance(v, str):
            v_lower = v.lower().strip()
            income_aliases = {"income", "receita", "entrada", "crédito", "credito", "revenue", "credit"}
            expense_aliases = {"expense", "despesa", "saída", "saida", "débito", "debito", "debit", "gasto", "other", "unknown", "unclear"}
            cost_aliases = {"custo", "cost"}
            if v_lower in income_aliases:
                return "receita"
            if v_lower == "investimento":
                return "investimento"
            if v_lower == "perda":
                return "perda"
            if v_lower in cost_aliases:
                return "custo"
            if v_lower in expense_aliases:
                return "despesa"
            return "despesa"
        return "despesa"

    # Parties involved
    issuer: Optional[CompanyInfo] = None  # Who issued the document
    recipient: Optional[CompanyInfo] = None  # Who received it

    # Financial details
    line_items: List[LineItem] = Field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_rate: Optional[float] = None
    discount: Optional[Decimal] = None
    total_amount: Optional[Decimal] = None  # Will be calculated by validator if not provided
    currency: str = "BRL"

    # Payment information
    payment_info: Optional[PaymentInfo] = None

    # Ledger-specific fields (for transaction_ledger documents)
    transactions: Optional[List["Transaction"]] = None
    total_transactions: Optional[int] = None
    total_income: Optional[Decimal] = None
    total_expense: Optional[Decimal] = None
    net_balance: Optional[Decimal] = None

    # NFe cancellation support (Item 4)
    is_cancellation: bool = False  # True if this is a cancellation document
    original_document_number: Optional[str] = None  # Number of the NF being cancelled

    # Additional data
    notes: Optional[str] = None
    raw_text: Optional[str] = None  # Original extracted text for reference
    confidence_score: Optional[float] = None  # AI confidence in extraction

    @validator("subtotal", "tax_amount", "discount", "total_amount", "total_income", "total_expense", "net_balance", pre=True)
    def normalize_decimal_fields(cls, v):
        """Normalize Brazilian decimal format before validation with error handling"""
        if v is None or isinstance(v, (int, float, Decimal)):
            return v
        if isinstance(v, str):
            try:
                normalized = normalize_brazilian_decimal(v)
                return Decimal(normalized) if normalized else None
            except (ValueError, Decimal.InvalidOperation) as e:
                # Log the error but don't fail - return None
                import logging
                logging.warning(f"Failed to convert decimal value '{v}': {e}")
                return None
        return v

    @validator("total_amount", pre=False, always=True)
    def calculate_total_amount(cls, v, values):
        """Calculate total_amount if None - try line_items, then subtotal+tax-discount, else 0"""
        if v is not None:
            return v

        # Try to calculate from line_items
        line_items = values.get("line_items", [])
        if line_items:
            total = sum(
                item.total_price for item in line_items
                if item.total_price is not None
            )
            if total > 0:
                return Decimal(str(total))

        # Try to calculate from subtotal + tax - discount
        subtotal = values.get("subtotal")
        tax_amount = values.get("tax_amount")
        discount = values.get("discount")

        if subtotal is not None:
            total = subtotal
            if tax_amount is not None:
                total += tax_amount
            if discount is not None:
                total -= discount
            return total

        # Default to 0 if no calculation possible
        return Decimal("0.00")


class Transaction(BaseModel):
    """Individual transaction from a ledger row"""

    date: Optional[str] = None  # ISO format date
    description: Optional[str] = None
    category: Optional[str] = None
    department: Optional[str] = None  # Department/cost center
    amount: Decimal
    transaction_type: Literal["receita", "despesa", "custo", "investimento", "perda"] = "despesa"
    reference: Optional[str] = None  # Reference number, invoice number, etc.
    account: Optional[str] = None  # Account name or code
    counterparty: Optional[str] = None  # Supplier/client name for this transaction
    notes: Optional[str] = None

    @validator("transaction_type", pre=True)
    def normalize_transaction_type(cls, v):
        """Normalize transaction types to 5 canonical Portuguese types"""
        if v is None:
            return "despesa"
        if isinstance(v, str):
            v_lower = v.lower().strip()
            income_aliases = {"income", "receita", "entrada", "crédito", "credito", "revenue", "credit"}
            expense_aliases = {"expense", "despesa", "saída", "saida", "débito", "debito", "debit", "gasto"}
            cost_aliases = {"custo", "cost"}
            if v_lower in income_aliases:
                return "receita"
            if v_lower == "investimento":
                return "investimento"
            if v_lower == "perda":
                return "perda"
            if v_lower in cost_aliases:
                return "custo"
            if v_lower in expense_aliases:
                return "despesa"
            return "despesa"
        return "despesa"

    @validator("amount", pre=True)
    def normalize_decimal_fields(cls, v):
        """Normalize Brazilian decimal format before validation"""
        if v is None or isinstance(v, (int, float, Decimal)):
            return v
        if isinstance(v, str):
            return normalize_brazilian_decimal(v)
        return v


class CategorySummary(BaseModel):
    """Summary of transactions by category"""

    category: str
    total_amount: Decimal
    count: int
    transaction_type: str
    percentage: Optional[float] = None  # Percentage of total

    @validator("total_amount", pre=True)
    def normalize_decimal_fields(cls, v):
        """Normalize Brazilian decimal format before validation"""
        if v is None or isinstance(v, (int, float, Decimal)):
            return v
        if isinstance(v, str):
            return normalize_brazilian_decimal(v)
        return v


class DateRangeSummary(BaseModel):
    """Date range information"""

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_days: Optional[int] = None


class TransactionLedger(BaseModel):
    """
    Multi-transaction ledger from Excel files
    Contains many transactions with aggregated summaries
    """

    # Ledger metadata
    document_type: Literal["transaction_ledger"] = "transaction_ledger"
    file_name: str
    total_transactions: int

    # Date range
    date_range: DateRangeSummary

    # Summary totals
    total_income: Decimal = Decimal("0")
    total_expense: Decimal = Decimal("0")
    net_balance: Decimal = Decimal("0")
    currency: str = "BRL"

    # Breakdowns
    by_category: List[CategorySummary] = Field(default_factory=list)

    # All individual transactions
    transactions: List[Transaction] = Field(default_factory=list)

    # Additional metadata
    notes: Optional[str] = None
    confidence_score: Optional[float] = None

    @validator("total_income", "total_expense", "net_balance", pre=True)
    def normalize_decimal_fields(cls, v):
        """Normalize Brazilian decimal format before validation"""
        if v is None or isinstance(v, (int, float, Decimal)):
            return v
        if isinstance(v, str):
            return normalize_brazilian_decimal(v)
        return v


class DocumentRecord(BaseModel):
    """
    Database record for a processed document
    Combines the extracted data with file metadata
    """

    id: Optional[int] = None

    # File information
    file_name: str
    file_type: str  # pdf, jpg, png, xlsx
    file_size: Optional[int] = None
    upload_date: datetime = Field(default_factory=datetime.utcnow)

    # Processing status
    status: Literal["pending", "processing", "pending_validation", "completed", "failed", "cancelled"] = "pending"
    error_message: Optional[str] = None

    # Extracted data - can be either a single document or a ledger
    extracted_data: Optional[Union[FinancialDocument, TransactionLedger]] = None

    # Metadata
    processed_date: Optional[datetime] = None
    user_id: Optional[int] = None  # For future multi-user support

    # Client/Customer tracking
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    client_type: Optional[str] = None

    # CNPJ validation warning (Item 7)
    cnpj_mismatch: bool = False
    cnpj_warning_message: Optional[str] = None

    # Background retry info
    retry_count: int = 0
    max_retries_exhausted: bool = False
    last_retry_at: Optional[datetime] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat(), Decimal: lambda v: str(v)}


class DocumentUploadResponse(BaseModel):
    """API response for document upload"""

    id: int
    file_name: str
    status: str
    message: str


class DocumentListResponse(BaseModel):
    """API response for listing documents"""

    total: int
    documents: List[DocumentRecord]


class ContactFormSubmission(BaseModel):
    """Contact form submission with validation and sanitization"""

    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr  # Validates email format
    phone: Optional[str] = Field(None, max_length=20)
    message: str = Field(..., min_length=10, max_length=1000)

    @validator("name", "message")
    def sanitize_text(cls, v):
        """Remove HTML tags and dangerous characters"""
        if v:
            # Remove HTML tags
            cleaned = bleach.clean(v, tags=[], strip=True)
            # Remove excessive whitespace
            cleaned = " ".join(cleaned.split())
            return cleaned
        return v

    @validator("phone")
    def validate_phone(cls, v):
        """Validate Brazilian phone format"""
        if v:
            # Remove all non-numeric characters
            digits = re.sub(r"\D", "", v)
            # Brazilian phone should have 10-11 digits (with area code)
            if len(digits) < 10 or len(digits) > 11:
                raise ValueError("Telefone inválido. Use o formato: (11) 98765-4321")
        return v


class ContactFormResponse(BaseModel):
    """API response for contact form submission"""

    success: bool
    message: str
    submission_id: Optional[int] = None


# Rebuild models to resolve forward references
FinancialDocument.model_rebuild()
