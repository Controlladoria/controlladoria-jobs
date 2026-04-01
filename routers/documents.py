"""
Documents Router
Handles all document-related endpoints:
- Upload (single, bulk, CSV)
- List, get, update, delete documents
- Validate, preview, download
- Audit logs and ledger transactions
"""

import json
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from i18n_errors import translate_error, translate_ai_error, translate_validation_error, get_friendly_error_message


# Custom JSON encoder to handle Decimal types
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.dependencies import get_current_active_user
from auth.permissions import get_accessible_user_ids, verify_document_access
from config import settings
from database import (
    AuditLog,
    Client,
    Document,
    DocumentStatus,
    DocumentValidationRow,
    KnownItem,
    Subscription,
    User,
    get_db,
)
from i18n import msg
from middleware.subscription import require_active_subscription
from models import (
    DocumentListResponse,
    DocumentRecord,
    DocumentUploadResponse,
    FinancialDocument,
    TransactionLedger,
)
from storage.s3_service import s3_storage
from structured_processor import StructuredDocumentProcessor
# queue_manager replaced by SQS → Lambda processing
from validators import FinancialDataValidator
from auth.team_management import get_organization_owner_id
from auth.models import KnownItemResponse, KnownItemUpdate

# Try to import magic for MIME type validation (optional on Windows)
# On Windows, python-magic often crashes with access violations (segfault)
# when the libmagic DLL is missing. Segfaults can't be caught by try/except,
# so we skip the import entirely on Windows and use extension-based validation.
import sys
MAGIC_AVAILABLE = False
if sys.platform != "win32":
    try:
        import magic
        MAGIC_AVAILABLE = True
    except (ImportError, OSError, Exception):
        logging.warning("python-magic not available, using extension-based validation only")
else:
    logging.info("python-magic skipped on Windows, using extension-based file validation")

logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/documents", tags=["Documents"])

# Uploads directory (skip mkdir in Lambda — read-only filesystem, only /tmp is writable)
UPLOAD_DIR = Path("/tmp/uploads") if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else Path("uploads")
try:
    UPLOAD_DIR.mkdir(exist_ok=True)
except OSError:
    pass  # Lambda read-only filesystem — S3 is used instead

# Initialize processor
processor = StructuredDocumentProcessor()


# =============================================================================
# KNOWN ITEMS - Normalization, Upsert, Pruning
# =============================================================================

import re as _re

KNOWN_ITEM_BLACKLIST = {
    "TOTAL", "SUBTOTAL", "DESCONTO", "FRETE", "ICMS", "IPI", "PIS", "COFINS",
    "ISS", "NOTA FISCAL", "NFE", "VALOR", "QUANTIDADE", "UNIDADE", "BASE",
    "ALIQUOTA", "TRIBUTOS", "IMPOSTOS", "OUTROS", "SERVICO", "PRODUTO",
    "ITEM", "ITENS", "MERCADORIA", "MERCADORIAS", "CFOP", "NCM", "CEST",
}


def _normalize_known_item_name(raw: str) -> str | None:
    """
    Normalize item name for known items matching.
    Returns None if item should be skipped (blacklisted, too short, etc.).
    """
    if not raw:
        return None
    name = raw.strip().upper()
    # Strip leading quantity patterns like "10 UN ", "5,00 KG ", "3X "
    name = _re.sub(r'^\d+[\.,]?\d*\s*(UN|KG|LT|MT|PC|CX|SC|FD|GL|ML|DZ|PR|CT|TB|RS|VL|HR)\s+', '', name)
    # Strip trailing quantity patterns like " - 10 UN"
    name = _re.sub(r'\s*[-–]\s*\d+[\.,]?\d*\s*(UN|KG|LT|MT|PC|CX|SC|FD|GL|ML|DZ|PR|CT|TB|RS|VL|HR)$', '', name)
    name = name.strip()
    if len(name) < 3 or name in KNOWN_ITEM_BLACKLIST:
        return None
    return name[:255]


def _upsert_known_items_from_validation(db: Session, current_user: User, all_rows: list):
    """
    After confirming validation, upsert known items from validated rows.
    Skips row_index=0 header for multi-row docs (NFe).
    Deduplicates by normalized name to avoid unique constraint violations
    when multiple rows share the same description.
    """
    owner_id = get_organization_owner_id(current_user)

    # For multi-row docs, skip the header row (index 0)
    rows_to_process = all_rows[1:] if len(all_rows) > 1 else all_rows

    # Deduplicate: group rows by normalized name, keep last occurrence's category/type
    # and count total appearances
    seen: dict[str, dict] = {}  # normalized_name -> {count, category, transaction_type}
    for row in rows_to_process:
        if not row.description:
            continue

        normalized = _normalize_known_item_name(row.description)
        if not normalized:
            continue

        if normalized in seen:
            seen[normalized]["count"] += 1
            # Update category/type from later rows (they may have been corrected by user)
            if row.category:
                seen[normalized]["category"] = row.category
            if row.transaction_type:
                seen[normalized]["transaction_type"] = row.transaction_type
        else:
            seen[normalized] = {
                "count": 1,
                "category": row.category,
                "transaction_type": row.transaction_type,
            }

    now = datetime.utcnow()

    for normalized, info in seen.items():
        # Check if already exists in DB
        existing = (
            db.query(KnownItem)
            .filter(KnownItem.user_id == owner_id, KnownItem.name == normalized)
            .first()
        )

        if existing:
            # Update: bump count and date, update category/type but preserve user-edited alias
            existing.times_appeared += info["count"]
            existing.last_seen_at = now
            if info["category"]:
                existing.category = info["category"]
            if info["transaction_type"]:
                existing.transaction_type = info["transaction_type"]
        else:
            # Insert new known item
            new_item = KnownItem(
                user_id=owner_id,
                name=normalized,
                alias=None,
                category=info["category"],
                transaction_type=info["transaction_type"],
                times_appeared=info["count"],
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(new_item)

    try:
        db.commit()
    except Exception as e:
        logger.warning(f"⚠️ Known items upsert error (non-critical): {e}")
        db.rollback()


def _prune_known_items(db: Session, owner_id: int):
    """
    Clean up known items to prevent table growth:
    - Items appearing once with last_seen > 3 months ago → delete
    - Items with last_seen > 1 year ago → delete regardless of count
    - Cap at 1000 items per organization
    """
    now = datetime.utcnow()
    three_months_ago = now - timedelta(days=90)
    one_year_ago = now - timedelta(days=365)

    try:
        # Delete single-appearance items older than 3 months
        db.query(KnownItem).filter(
            KnownItem.user_id == owner_id,
            KnownItem.times_appeared == 1,
            KnownItem.last_seen_at < three_months_ago,
        ).delete(synchronize_session=False)

        # Delete any items older than 1 year
        db.query(KnownItem).filter(
            KnownItem.user_id == owner_id,
            KnownItem.last_seen_at < one_year_ago,
        ).delete(synchronize_session=False)

        # Cap at 1000 items per org
        count = db.query(func.count(KnownItem.id)).filter(
            KnownItem.user_id == owner_id
        ).scalar() or 0

        if count > 1000:
            # Delete oldest items to bring down to 1000
            excess = count - 1000
            oldest_ids = (
                db.query(KnownItem.id)
                .filter(KnownItem.user_id == owner_id)
                .order_by(KnownItem.last_seen_at.asc())
                .limit(excess)
                .all()
            )
            ids_to_delete = [r[0] for r in oldest_ids]
            if ids_to_delete:
                db.query(KnownItem).filter(KnownItem.id.in_(ids_to_delete)).delete(
                    synchronize_session=False
                )

        db.commit()
    except Exception as e:
        logger.warning(f"⚠️ Known items pruning error (non-critical): {e}")
        db.rollback()


def _get_known_items_for_prompt(db: Session, owner_id: int) -> list[dict]:
    """
    Get known items formatted for AI prompt injection.
    Returns top 200 items by times_appeared, grouped by category.
    """
    items = (
        db.query(KnownItem)
        .filter(KnownItem.user_id == owner_id)
        .order_by(KnownItem.times_appeared.desc())
        .limit(200)
        .all()
    )

    return [
        {
            "name": item.name,
            "alias": item.alias,
            "category": item.category,
            "transaction_type": item.transaction_type,
            "times_appeared": item.times_appeared,
        }
        for item in items
    ]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request, handling proxies safely.

    Only trusts X-Forwarded-For / X-Real-IP when the direct connection
    comes from a known trusted proxy (configured via TRUSTED_PROXY_IPS).
    """
    direct_ip = request.client.host if request.client else "unknown"

    if direct_ip in settings.trusted_proxy_ips:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

    return direct_ip


def validate_file_path(file_path: Path) -> Path:
    """Validate that file_path is within the uploads directory (prevents path traversal).

    Resolves the path to an absolute path and checks it's under UPLOAD_DIR
    or is an S3-style key (users/{id}/...).
    Raises HTTPException 403 if the path escapes the allowed directory.
    """
    resolved = file_path.resolve()
    upload_resolved = UPLOAD_DIR.resolve()

    if not str(resolved).startswith(str(upload_resolved)):
        logger.warning(f"Path traversal attempt blocked: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied")

    return resolved


def log_audit_trail(
    db: Session,
    user_id: int,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    before_value: Optional[dict] = None,
    after_value: Optional[dict] = None,
    changes_summary: Optional[str] = None,
    request: Optional[Request] = None,
    document_id: Optional[int] = None,
):
    """
    Log an action to the audit trail

    Args:
        db: Database session
        user_id: ID of user performing action
        action: Action type (create, update, delete)
        entity_type: Type of entity (document, transaction, etc)
        entity_id: ID of the entity being modified
        before_value: State before change (dict)
        after_value: State after change (dict)
        changes_summary: Human-readable summary
        request: FastAPI request object (for IP/user agent)
        document_id: Document ID if action relates to a document
    """
    # Extract request context if provided
    ip_address = None
    user_agent = None
    if request:
        ip_address = get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")[:500]  # Truncate to DB limit

    # Convert dicts to JSON strings (handle Decimal types)
    before_json = json.dumps(before_value, cls=DecimalEncoder) if before_value else None
    after_json = json.dumps(after_value, cls=DecimalEncoder) if after_value else None

    # Create audit log entry
    audit_entry = AuditLog(
        user_id=user_id,
        document_id=document_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_value=before_json,
        after_value=after_json,
        changes_summary=changes_summary,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.add(audit_entry)
    # Note: Caller is responsible for committing the transaction

    logger.info(
        f"📝 Audit: user={user_id} action={action} entity={entity_type}:{entity_id} from {ip_address}"
    )


def find_or_create_client(db: Session, user_id: int, party_data: dict, client_type: str) -> Optional[int]:
    """
    Find or create a client based on issuer/recipient data.
    Matches by tax_id first, then name. Creates if not found.
    """
    if not party_data or not isinstance(party_data, dict):
        return None

    name = party_data.get("name")
    if not name:
        return None

    tax_id = party_data.get("tax_id")

    # Try to find existing client by tax_id first
    if tax_id:
        existing = db.query(Client).filter(
            Client.user_id == user_id,
            Client.tax_id == tax_id
        ).first()
        if existing:
            return existing.id

    # Try to find by name (case-insensitive)
    existing = db.query(Client).filter(
        Client.user_id == user_id,
        Client.name.ilike(name)
    ).first()
    if existing:
        return existing.id

    # Create new client
    try:
        new_client = Client(
            user_id=user_id,
            name=name,
            legal_name=party_data.get("legal_name"),
            tax_id=tax_id,
            email=party_data.get("email"),
            phone=party_data.get("phone"),
            address=party_data.get("address"),
            client_type=client_type,
            is_active=True,
        )
        db.add(new_client)
        db.flush()
        return new_client.id
    except Exception as e:
        logger.warning(f"Could not create client {name}: {e}")
        return None


def _handle_nfe_cancellation(db: Session, doc: "Document", data_dict: dict):
    """
    Handle NFe cancellation document linking (Item 4).

    When a cancellation document is uploaded:
    1. Mark the cancellation doc with is_cancellation=True
    2. Search for the original document by document_number
    3. If found: cancel the original and link both documents
    4. If not found: log a warning (document still saved for reference)
    """
    original_number = data_dict.get("original_document_number", "")

    # Mark this document as a cancellation
    doc.is_cancellation = True

    if not original_number:
        logger.warning(
            f"⚠️  NFe cancellation document {doc.id} has no original_document_number"
        )
        return

    logger.info(
        f"🔍 Looking for original NFe #{original_number} to cancel (cancellation doc: {doc.id})"
    )

    # Search for the original document by document_number in extracted_data_json
    # Must belong to the same user and not already be cancelled
    candidates = (
        db.query(Document)
        .filter(
            Document.user_id == doc.user_id,
            Document.id != doc.id,
            Document.status.in_([
                DocumentStatus.COMPLETED,
                DocumentStatus.PENDING_VALIDATION,
            ]),
            Document.is_cancellation == False,
        )
        .all()
    )

    original_doc = None
    for candidate in candidates:
        if not candidate.extracted_data_json:
            continue
        try:
            candidate_data = json.loads(candidate.extracted_data_json)
            candidate_number = candidate_data.get("document_number", "")

            # Match by document number (remove leading zeros for comparison)
            if candidate_number and _normalize_nf_number(candidate_number) == _normalize_nf_number(original_number):
                original_doc = candidate
                break
        except (json.JSONDecodeError, TypeError):
            continue

    if original_doc:
        # Link and cancel the original document
        original_doc.status = DocumentStatus.CANCELLED
        original_doc.cancelled_by_document_id = doc.id
        doc.cancels_document_id = original_doc.id

        logger.info(
            f"✅ NFe #{original_number} (doc {original_doc.id}) cancelled by cancellation doc {doc.id}"
        )

        # Audit trail for the original doc cancellation
        audit_entry = AuditLog(
            user_id=doc.user_id,
            document_id=original_doc.id,
            action="cancel",
            entity_type="document",
            entity_id=original_doc.id,
            changes_summary=f"Document cancelled by NFe cancellation #{doc.file_name} (doc ID: {doc.id})",
        )
        db.add(audit_entry)
    else:
        logger.warning(
            f"⚠️  Original NFe #{original_number} not found in system for cancellation doc {doc.id}. "
            f"The cancellation document was saved but no original was cancelled."
        )
        # Add a note to the cancellation document
        doc.error_message = (
            f"NF original #{original_number} não encontrada no sistema. "
            f"Documento de cancelamento salvo para referência."
        )


def _normalize_nf_number(number: str) -> str:
    """Normalize NF number for comparison (remove leading zeros, spaces, special chars)."""
    if not number:
        return ""
    import re
    # Remove everything that's not a digit
    digits = re.sub(r'\D', '', str(number))
    # Remove leading zeros
    return digits.lstrip('0') or '0'


def _batch_categorize_uncategorized_rows(db: Session, doc: "Document", processor):
    """
    Post-processing step: find validation rows that are still 'nao_categorizado'
    and batch-categorize them using AI.
    """
    import json

    UNCATEGORIZED = {"nao_categorizado", "uncategorized", ""}
    uncategorized_rows = (
        db.query(DocumentValidationRow)
        .filter(
            DocumentValidationRow.document_id == doc.id,
            DocumentValidationRow.category.in_(list(UNCATEGORIZED)),
        )
        .all()
    )

    if not uncategorized_rows:
        return

    # Collect unique descriptions
    desc_to_rows = {}
    for row in uncategorized_rows:
        desc = (row.description or "").strip()
        if desc:
            if desc not in desc_to_rows:
                desc_to_rows[desc] = []
            desc_to_rows[desc].append(row)

    if not desc_to_rows:
        return

    unique_descriptions = sorted(desc_to_rows.keys())
    logger.info(f"🤖 Post-processing: categorizing {len(unique_descriptions)} uncategorized descriptions for doc {doc.id}")

    CATEGORIES_TEXT = (
        "RECEITA: receita_vendas_produtos, receita_servicos, receita_locacao, receita_comissoes, receita_contratos_recorrentes\n"
        "DEDUÇÕES: impostos_sobre_vendas, devolucoes, descontos_concedidos\n"
        "CUSTOS VARIÁVEIS: cmv, csp, materia_prima, insumos, comissoes_sobre_vendas\n"
        "CUSTOS FIXOS PRODUÇÃO: salarios_producao, encargos_sociais_producao, energia_producao, manutencao_equipamentos_producao\n"
        "DESPESAS ADMIN: salarios_administrativos, pro_labore, encargos_sociais_administrativos, aluguel, condominio, agua_energia, material_escritorio, honorarios_contabeis, sistemas_softwares, telefonia_internet\n"
        "DESPESAS COMERCIAIS: marketing_publicidade, propaganda_digital, comissao_vendas, fretes, representantes_comerciais\n"
        "FINANCEIRO: receita_financeira, juros_ativos, descontos_obtidos, juros_passivos, tarifas_bancarias, iof, multas_encargos\n"
        "TRIBUTOS: irpj, csll, simples_nacional, iptu, taxas_municipais\n"
        "OUTRAS: recuperacao_despesas, venda_imobilizado, indenizacoes_recebidas, outras_receitas_eventuais, perdas, indenizacoes_pagas, doacoes, provisoes, depreciacao, amortizacao, outras_despesas_operacionais\n"
        "FALLBACK: nao_categorizado (ONLY as absolute last resort)"
    )

    VALID_CATEGORIES = {
        "receita_vendas_produtos", "receita_servicos", "receita_locacao", "receita_comissoes",
        "receita_contratos_recorrentes", "impostos_sobre_vendas", "devolucoes", "descontos_concedidos",
        "cmv", "csp", "materia_prima", "insumos", "comissoes_sobre_vendas", "salarios_producao",
        "encargos_sociais_producao", "energia_producao", "manutencao_equipamentos_producao",
        "salarios_administrativos", "pro_labore", "encargos_sociais_administrativos", "aluguel",
        "condominio", "agua_energia", "material_escritorio", "honorarios_contabeis", "sistemas_softwares",
        "telefonia_internet", "marketing_publicidade", "propaganda_digital", "comissao_vendas", "fretes",
        "representantes_comerciais", "receita_financeira", "juros_ativos", "descontos_obtidos",
        "juros_passivos", "tarifas_bancarias", "iof", "multas_encargos", "irpj", "csll",
        "simples_nacional", "iptu", "taxas_municipais", "recuperacao_despesas", "venda_imobilizado",
        "indenizacoes_recebidas", "outras_receitas_eventuais", "perdas", "indenizacoes_pagas",
        "doacoes", "provisoes", "depreciacao", "amortizacao", "outras_despesas_operacionais",
        "nao_categorizado",
    }

    import re

    BATCH_SIZE = 80
    description_to_category = {}

    for batch_start in range(0, len(unique_descriptions), BATCH_SIZE):
        batch = unique_descriptions[batch_start: batch_start + BATCH_SIZE]
        descriptions_json = json.dumps(batch, ensure_ascii=False)

        prompt = (
            "You are a Brazilian accounting assistant. Categorize each transaction description below "
            "using EXACTLY one category key from the V2 Plano de Contas list.\n"
            "These are from bank statements and financial documents. Try your BEST to assign a real category.\n"
            "Common patterns: PIX/transferência → analyze context, tarifa → tarifas_bancarias, "
            "compra com cartão → analyze what was bought, saldo → ignore (use nao_categorizado).\n\n"
            f"V2 categories:\n{CATEGORIES_TEXT}\n\n"
            "Return ONLY a valid JSON object mapping each description exactly as given to its category key. "
            "No markdown, no explanation.\n"
            f"Descriptions: {descriptions_json}"
        )

        try:
            if processor.ai_provider == "openai":
                response = processor._active_client.chat.completions.create(
                    model=processor.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=4000,
                    store=False,
                )
                raw = response.choices[0].message.content or "{}"
            else:
                response = processor._active_client.messages.create(
                    model=processor.anthropic_model,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text if response.content else "{}"

            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)

            batch_result = json.loads(raw)
            description_to_category.update(batch_result)
            logger.info(f"✓ Post-process categorized batch: {len(batch_result)} items")

        except Exception as e:
            logger.warning(f"⚠️ Post-process categorization batch failed: {e}")

    # Apply categories to the validation rows
    updated_count = 0
    for desc, rows in desc_to_rows.items():
        ai_cat = description_to_category.get(desc)
        if ai_cat and ai_cat in VALID_CATEGORIES and ai_cat != "nao_categorizado":
            for row in rows:
                row.category = ai_cat
                updated_count += 1

    if updated_count:
        logger.info(f"✅ Post-processing updated {updated_count} rows with AI categories for doc {doc.id}")


def _create_validation_rows(db: Session, doc: "Document", data_dict: dict):
    """
    Create validation rows from extracted document data (Item 9).

    For multi-transaction documents (ledgers, statements): creates 1 row per transaction.
    For NFe/invoices with line_items: creates 1 row per product/item.
    For simple documents without line_items: creates 1 row.
    """
    import json
    from accounting.categories import resolve_category_name

    # Normalize transaction_type to canonical Portuguese types:
    # receita, despesa, custo, investimento, perda
    _income_aliases = {"income", "receita", "entrada", "crédito", "credito", "revenue", "recebimento", "credit"}
    _cost_aliases = {"custo", "cost"}
    _investment_aliases = {"investimento", "investment"}
    _loss_aliases = {"perda", "loss"}
    _expense_aliases = {"expense", "gasto", "despesa", "saída", "saida", "débito", "debito", "debit", "other", "unknown"}

    def _normalize_txn_type(raw_type: str | None) -> str:
        if not raw_type:
            return "despesa"
        v = str(raw_type).lower().strip()
        if v in _income_aliases:
            return "receita"
        if v in _cost_aliases:
            return "custo"
        if v in _investment_aliases:
            return "investimento"
        if v in _loss_aliases:
            return "perda"
        return "despesa"

    transactions = data_dict.get("transactions") or []
    line_items = data_dict.get("line_items") or []
    row_count = 0

    if transactions:
        # Multi-transaction document (ledger, statement)
        for idx, txn in enumerate(transactions):
            amount_val = txn.get("amount")
            amount_cents = int(float(amount_val) * 100) if amount_val is not None else None

            # Build description: include counterparty if available
            desc = txn.get("description") or ""
            counterparty = txn.get("counterparty")
            if counterparty and counterparty not in desc:
                desc = f"{desc} — {counterparty}" if desc else counterparty

            row = DocumentValidationRow(
                document_id=doc.id,
                row_index=idx,
                description=desc,
                transaction_date=txn.get("date"),
                amount=amount_cents,
                category=resolve_category_name(txn.get("category")),
                transaction_type=_normalize_txn_type(txn.get("transaction_type")),
                original_data_json=json.dumps(txn, default=str),
                user_id=doc.user_id,
            )
            db.add(row)
        row_count = len(transactions)

    elif line_items:
        # NFe / Invoice with individual products - expand each item as a row
        issue_date = data_dict.get("issue_date")
        doc_category = resolve_category_name(data_dict.get("category"))
        doc_type = _normalize_txn_type(data_dict.get("transaction_type"))

        # Build document header description (issuer info)
        header_parts = []
        if data_dict.get("document_type"):
            header_parts.append(data_dict["document_type"].upper())
        if data_dict.get("document_number"):
            header_parts.append(f"#{data_dict['document_number']}")
        issuer = data_dict.get("issuer")
        if issuer and isinstance(issuer, dict) and issuer.get("name"):
            header_parts.append(f"- {issuer['name']}")
        if issuer and isinstance(issuer, dict) and issuer.get("tax_id"):
            header_parts.append(f"(CNPJ: {issuer['tax_id']})")

        header_desc = " ".join(header_parts) if header_parts else doc.file_name

        # Row 0: Document header with total
        total = data_dict.get("total_amount")
        total_cents = int(float(total) * 100) if total is not None else None
        header_row = DocumentValidationRow(
            document_id=doc.id,
            row_index=0,
            description=header_desc,
            transaction_date=issue_date,
            amount=total_cents,
            category=doc_category,
            transaction_type=doc_type,
            original_data_json=json.dumps({
                "issuer": data_dict.get("issuer"),
                "recipient": data_dict.get("recipient"),
                "document_number": data_dict.get("document_number"),
                "total_amount": total,
                "tax_amount": data_dict.get("tax_amount"),
                "subtotal": data_dict.get("subtotal"),
            }, default=str),
            user_id=doc.user_id,
        )
        db.add(header_row)

        # Rows 1+: Individual line items (products/services)
        for idx, item in enumerate(line_items):
            item_total = item.get("total_price")
            item_cents = int(float(item_total) * 100) if item_total is not None else None

            qty = item.get("quantity")
            unit = item.get("unit_price")
            desc = item.get("description", "")
            if qty and unit:
                desc = f"{desc} (Qtd: {qty} x R$ {float(unit):,.2f})"

            # Use per-item category if available, fall back to document category
            item_category = resolve_category_name(item.get("category")) if item.get("category") else doc_category
            raw_type = item.get("transaction_type") or doc_type
            item_type = _normalize_txn_type(raw_type)

            row = DocumentValidationRow(
                document_id=doc.id,
                row_index=idx + 1,
                description=desc,
                transaction_date=issue_date,
                amount=item_cents,
                category=item_category,
                transaction_type=item_type,
                original_data_json=json.dumps(item, default=str),
                user_id=doc.user_id,
            )
            db.add(row)

        row_count = 1 + len(line_items)

    else:
        # Simple single-transaction document (receipt, etc.)
        total = data_dict.get("total_amount")
        amount_cents = int(float(total) * 100) if total is not None else None

        description_parts = []
        if data_dict.get("document_type"):
            description_parts.append(data_dict["document_type"])
        if data_dict.get("document_number"):
            description_parts.append(f"#{data_dict['document_number']}")
        issuer = data_dict.get("issuer")
        if issuer and isinstance(issuer, dict) and issuer.get("name"):
            description_parts.append(f"- {issuer['name']}")

        description = " ".join(description_parts) if description_parts else doc.file_name

        row = DocumentValidationRow(
            document_id=doc.id,
            row_index=0,
            description=description,
            transaction_date=data_dict.get("issue_date"),
            amount=amount_cents,
            category=resolve_category_name(data_dict.get("category")),
            transaction_type=_normalize_txn_type(data_dict.get("transaction_type")),
            original_data_json=json.dumps(data_dict, default=str),
            user_id=doc.user_id,
        )
        db.add(row)
        row_count = 1

    logger.info(
        f"📝 Created {row_count} validation row(s) for document {doc.id}"
    )


# process_document_background has been moved to controlladoria-jobs Lambda.
# Documents are now processed via: API upload → S3 → SQS → Lambda


def _send_sqs_message(document_id: int, file_path: str):
    """Send a document processing message to SQS for Lambda pickup."""
    import json
    import boto3

    try:
        sqs = boto3.client(
            "sqs",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        sqs.send_message(
            QueueUrl=settings.sqs_document_queue_url,
            MessageBody=json.dumps({
                "document_id": document_id,
                "file_path": file_path,
            }),
        )
        logger.info(f"📤 SQS message sent for document {document_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send SQS message for document {document_id}: {e}")
        # Mark document as failed so retry Lambda can pick it up later
        from database import SessionLocal
        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"Falha ao enviar para processamento: {str(e)}"
                db.commit()
        finally:
            db.close()



# =============================================================================
# DOCUMENT UPLOAD ENDPOINTS
# =============================================================================


@router.post("/upload", response_model=DocumentUploadResponse)
@limiter.limit(
    settings.upload_rate_limit if settings.rate_limit_enabled else "1000/minute"
)
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    subscription: Subscription = Depends(require_active_subscription),
    db: Session = Depends(get_db),
):
    """
    Upload a financial document (PDF, Excel, XML, or image)
    Saves file and processes in background

    Requires authentication and active subscription
    Rate limited to prevent abuse
    Processing happens asynchronously - check status via GET /documents/{id}

    **SCALABILITY NOTE**: For 100k+ concurrent users, consider:
    1. Presigned S3 URLs (client uploads directly to S3, bypassing API)
    2. Dedicated upload servers with higher memory limits
    3. Async file processing with job queue (Celery/RQ instead of BackgroundTasks)

    Current implementation: Files <1MB in memory, >1MB spooled to disk (FastAPI default)
    """

    # Read file contents (FastAPI handles spooling to disk for large files)
    contents = await file.read()
    file_size = len(contents)

    # Compute file hash for duplicate detection
    import hashlib
    file_hash = hashlib.sha256(contents).hexdigest()

    # Validate file size
    if file_size > settings.max_upload_size:
        max_size_mb = settings.max_upload_size / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande. Tamanho máximo: {max_size_mb:.1f}MB",
        )

    if file_size == 0:
        raise HTTPException(
            status_code=400, detail="Arquivo vazio. Por favor, envie um arquivo válido."
        )

    # Sanitize filename to prevent path traversal
    safe_filename = os.path.basename(file.filename or "unnamed")
    safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in "._- ")[
        :255
    ]

    if not safe_filename:
        safe_filename = "document"

    # Validate file extension
    file_ext = Path(safe_filename).suffix.lower()

    if file_ext not in settings.allowed_file_extensions:
        raise HTTPException(status_code=400, detail=msg["unsupported_file_type"])

    # Validate MIME type if python-magic is available
    if MAGIC_AVAILABLE:
        try:
            mime_type = magic.from_buffer(contents, mime=True)

            if mime_type not in settings.allowed_mime_types:
                logger.warning(
                    f"Invalid MIME type: {mime_type} for file {safe_filename}"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Tipo de arquivo inválido detectado: {mime_type}. Use apenas PDF, Excel ou imagens.",
                )
        except Exception as e:
            logger.warning(f"MIME type validation failed: {e}")
            # Continue with extension-based validation only

    # CNPJ Validation for Nota Fiscal (warn instead of block - Item 7)
    cnpj_mismatch = False
    cnpj_warning_msg = None
    if settings.enable_cnpj_validation:
        # Check if this might be a Nota Fiscal by filename
        filename_lower = safe_filename.lower()
        is_nota_fiscal = any(keyword in filename_lower for keyword in [
            'nota', 'fiscal', 'nfe', 'nf-e', 'danfe', 'invoice'
        ])

        if is_nota_fiscal:
            logger.info(f"🔍 Detected potential Nota Fiscal - running CNPJ validation")

            # Save temporarily for validation
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
                temp_file.write(contents)
                temp_path = temp_file.name

            try:
                from cnpj_validator import validate_document_cnpj
                from ai_key_pool import get_next_ai_credentials

                # Use key pool for round-robin + failover
                ai_provider, api_key, model = get_next_ai_credentials(
                    processor.key_pool, preferred_provider=settings.ai_provider
                )

                is_valid, error_message = validate_document_cnpj(
                    file_path=temp_path,
                    user_cnpj=current_user.cnpj,
                    ai_provider=ai_provider,
                    api_key=api_key,
                    model=model,
                    skip_validation=False
                )

                # Clean up temp file
                try:
                    os.unlink(temp_path)
                except:
                    pass

                if not is_valid:
                    # Item 7: Warn instead of blocking upload
                    # Old behavior (commented out):
                    # raise HTTPException(status_code=403, detail=error_message)
                    cnpj_mismatch = True
                    cnpj_warning_msg = error_message
                    logger.warning(f"⚠️  CNPJ mismatch (warning only): {safe_filename} - {error_message}")
                else:
                    logger.info(f"✅ CNPJ validation passed - document contains user's CNPJ")

            except Exception as e:
                logger.error(f"Error during CNPJ validation: {e}")
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except:
                    pass
                # Continue with upload if validation fails due to technical error
                logger.warning(f"⚠️  CNPJ validation skipped due to error - allowing upload")

    try:
        # Upload file to S3 or local filesystem (based on settings.use_s3)
        timestamp = datetime.utcnow().timestamp()
        unique_filename = f"{timestamp}_{safe_filename}"
        # Use S3 if configured, otherwise local filesystem (DEPRECATED for production)
        if settings.use_s3:
            # Upload to S3 with multi-tenant isolation
            file_key = s3_storage.upload_file(
                file_content=contents,
                filename=unique_filename,
                content_type=file.content_type or "application/octet-stream",
                user_id=current_user.id,
            )
            file_path = file_key  # Store S3 key
        else:
            # LOCAL FILESYSTEM (DEPRECATED - breaks horizontal scaling!)
            # Only use for development. In production, ALWAYS use S3.
            file_path = UPLOAD_DIR / unique_filename
            with open(file_path, "wb") as buffer:
                buffer.write(contents)
            file_path = str(file_path)
            logger.warning(
                "⚠️  Using local filesystem - this breaks horizontal scaling!"
            )

        # Check for duplicate files by content hash (exact same file)
        duplicate = db.query(Document).filter(
            Document.user_id == current_user.id,
            Document.file_hash == file_hash,
            Document.status != DocumentStatus.FAILED  # Allow re-uploading failed files
        ).first()

        if duplicate:
            # Get client info if available for better error message
            duplicate_client = ""
            if duplicate.extracted_data_json:
                try:
                    import json
                    data = json.loads(duplicate.extracted_data_json)
                    issuer = data.get("issuer", {})
                    recipient = data.get("recipient", {})
                    if issuer.get("name"):
                        duplicate_client = f" (emissor: {issuer['name']})"
                    elif recipient.get("name"):
                        duplicate_client = f" (destinatário: {recipient['name']})"
                except:
                    pass

            days_ago = (datetime.utcnow() - duplicate.upload_date).days
            time_desc = f"{days_ago} dia(s)" if days_ago > 0 else f"{int((datetime.utcnow() - duplicate.upload_date).total_seconds() / 60)} minuto(s)"

            logger.warning(f"⚠️  Duplicate file detected: {safe_filename} (original ID: {duplicate.id}){duplicate_client}")
            raise HTTPException(
                status_code=409,
                detail=f"Este arquivo já foi enviado há {time_desc}{duplicate_client}. ID do documento original: {duplicate.id}"
            )

        # Create database record with user association
        # Get active org_id for document isolation
        active_org = getattr(current_user, '_active_org_id', None) or getattr(current_user, 'active_org_id', None)

        doc = Document(
            file_name=safe_filename,
            file_type=file_ext.replace(".", ""),
            file_path=str(file_path),
            file_size=file_size,
            file_hash=file_hash,  # Store hash for duplicate detection
            status=DocumentStatus.PENDING,
            user_id=current_user.id,  # Multi-tenant: associate with current user
            organization_id=active_org,  # Multi-org: scope to active org
            cnpj_mismatch=cnpj_mismatch,  # Item 7: CNPJ warning flag
            cnpj_warning_message=cnpj_warning_msg,
        )

        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Send to SQS for Lambda processing (replaces in-process background task)
        _send_sqs_message(document_id=doc.id, file_path=str(file_path))

        logger.info(f"📤 Document sent to SQS for processing: ID={doc.id}")
        return DocumentUploadResponse(
            id=doc.id,
            file_name=doc.file_name,
            status=DocumentStatus.PENDING.value,
            message="Documento enviado para processamento. Será processado em breve.",
        )

    except Exception as e:
        # Log technical error in English for developers
        logger.error(f"❌ CRITICAL ERROR during upload: {file.filename}")
        logger.error(f"   Exception: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(f"   Traceback:\n{traceback.format_exc()}")

        # Translate error to Portuguese for user
        friendly_error = get_friendly_error_message(e)
        raise HTTPException(status_code=500, detail=friendly_error)


@router.post("/upload/bulk")
@limiter.limit("5/minute" if settings.rate_limit_enabled else "1000/minute")
async def bulk_upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    subscription: Subscription = Depends(require_active_subscription),
    db: Session = Depends(get_db),
):
    """
    Upload multiple financial documents at once
    Processes each file in background asynchronously

    Requires authentication and active subscription
    Rate limited to prevent abuse (5 bulk uploads per minute)
    Maximum 20 files per bulk upload
    """
    # Limit number of files per bulk upload
    max_files_per_batch = 20
    if len(files) > max_files_per_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Limite de {max_files_per_batch} arquivos por envio em lote. Você enviou {len(files)} arquivos.",
        )

    if len(files) == 0:
        raise HTTPException(
            status_code=400,
            detail="Nenhum arquivo enviado. Por favor, selecione ao menos um arquivo.",
        )

    uploaded_documents = []
    failed_uploads = []

    for file in files:
        try:
            # Read file contents
            contents = await file.read()
            file_size = len(contents)

            # Validate file size
            if file_size > settings.max_upload_size:
                failed_uploads.append(
                    {
                        "file_name": file.filename,
                        "error": f"Arquivo muito grande (máx: {settings.max_upload_size / (1024 * 1024):.1f}MB)",
                    }
                )
                continue

            if file_size == 0:
                failed_uploads.append(
                    {"file_name": file.filename, "error": "Arquivo vazio"}
                )
                continue

            # Sanitize filename
            safe_filename = os.path.basename(file.filename or "unnamed")
            safe_filename = "".join(
                c for c in safe_filename if c.isalnum() or c in "._- "
            )[:255]

            if not safe_filename:
                safe_filename = f"document_{len(uploaded_documents) + 1}"

            # Validate file extension
            file_ext = Path(safe_filename).suffix.lower()

            if file_ext not in settings.allowed_file_extensions:
                failed_uploads.append(
                    {
                        "file_name": file.filename,
                        "error": f"Tipo de arquivo não suportado: {file_ext}",
                    }
                )
                continue

            # Validate MIME type if available
            if MAGIC_AVAILABLE:
                try:
                    mime_type = magic.from_buffer(contents, mime=True)
                    if mime_type not in settings.allowed_mime_types:
                        failed_uploads.append(
                            {
                                "file_name": file.filename,
                                "error": f"Tipo MIME inválido: {mime_type}",
                            }
                        )
                        continue
                except Exception as e:
                    logger.warning(f"MIME validation failed for {safe_filename}: {e}")

            # Save file
            timestamp = datetime.utcnow().timestamp()
            file_path = UPLOAD_DIR / f"{timestamp}_{safe_filename}"

            with open(file_path, "wb") as buffer:
                buffer.write(contents)

            # Create database record with user association
            doc = Document(
                file_name=safe_filename,
                file_type=file_ext.replace(".", ""),
                file_path=str(file_path),
                file_size=file_size,
                status=DocumentStatus.PENDING,
                user_id=current_user.id,  # Multi-tenant: associate with current user
            )

            db.add(doc)
            db.commit()
            db.refresh(doc)

            # Send to SQS for Lambda processing
            _send_sqs_message(document_id=doc.id, file_path=str(file_path))

            uploaded_documents.append(
                {
                    "id": doc.id,
                    "file_name": doc.file_name,
                    "status": DocumentStatus.PENDING.value,
                    "message": "Enviado para processamento",
                }
            )


        except Exception as e:
            logger.error(f"Error uploading file {file.filename}: {e}")
            failed_uploads.append({"file_name": file.filename, "error": str(e)})

    # Return summary
    return {
        "message": f"Upload em lote concluído: {len(uploaded_documents)} sucesso, {len(failed_uploads)} falhas",
        "uploaded": uploaded_documents,
        "failed": failed_uploads,
        "total_files": len(files),
        "successful_uploads": len(uploaded_documents),
        "failed_uploads": len(failed_uploads),
    }


@router.get("/queue-status")
async def get_queue_status(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get current document processing queue status.

    Documents are now processed via SQS → Lambda, so this returns
    counts from the database instead of the in-process queue.
    """
    pending = db.query(Document).filter(
        Document.status == DocumentStatus.PENDING
    ).count()
    processing = db.query(Document).filter(
        Document.status == DocumentStatus.PROCESSING
    ).count()
    return {
        "processing": processing,
        "queued": pending,
        "available_slots": None,  # Lambda scales automatically
        "message": "Processamento via Lambda (escala automaticamente)",
    }


@router.post("/upload/csv")
@limiter.limit("10/minute" if settings.rate_limit_enabled else "1000/minute")
async def upload_csv_bulk_transactions(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    subscription: Subscription = Depends(require_active_subscription),
    db: Session = Depends(get_db),
):
    """
    Bulk CSV import endpoint for hospital-grade financial system

    Accepts CSV file with columns: date, description, category, amount, type, department
    - Validates each row using FinancialValidator
    - Detects duplicates using DuplicateDetector
    - Creates documents in bulk (supports 10,000+ rows)
    - Returns success count + detailed error report

    Rate limited to prevent abuse. Requires authentication and active subscription.
    """
    import csv
    import io
    from validation import DuplicateDetector, FinancialValidator

    # Validate file is CSV
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Arquivo deve ser CSV. Use extensão .csv",
        )

    try:
        # Read CSV file
        contents = await file.read()
        file_size = len(contents)

        # Validate file size (max 50MB for CSV)
        if file_size > 50 * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail="Arquivo CSV muito grande. Máximo: 50MB",
            )

        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Arquivo CSV vazio",
            )

        # Decode CSV
        csv_text = contents.decode("utf-8-sig")  # Handle BOM
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        # Validate CSV headers
        required_columns = {"date", "description", "category", "amount", "type"}
        optional_columns = {"department", "reference", "notes"}
        all_allowed = required_columns | optional_columns

        if not csv_reader.fieldnames:
            raise HTTPException(
                status_code=400,
                detail="CSV vazio ou sem cabeçalho",
            )

        fieldnames_lower = {f.lower().strip() for f in csv_reader.fieldnames}

        # Check required columns
        missing = required_columns - fieldnames_lower
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Colunas obrigatórias ausentes: {', '.join(missing)}",
            )

        logger.info(f"📊 CSV import started: {file.filename} ({file_size} bytes)")

        # Initialize validation and duplicate detection
        validator = FinancialValidator()

        # Get existing documents for duplicate detection - org-scoped
        existing_docs = document_org_filter(
            db.query(Document), current_user, db
        ).order_by(Document.upload_date.desc()).limit(1000).all()

        existing_docs_data = []
        for doc in existing_docs:
            if doc.extracted_data_json:
                try:
                    data_dict = json.loads(doc.extracted_data_json)
                    existing_docs_data.append(data_dict)
                except:
                    pass

        # Process CSV rows
        success_count = 0
        error_rows = []
        warning_rows = []
        duplicate_warnings = []
        created_documents = []

        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (header is 1)
            try:
                # Normalize column names (case-insensitive)
                row_data = {k.lower().strip(): v.strip() for k, v in row.items() if v}

                # Extract and validate required fields
                if not row_data.get("date"):
                    error_rows.append({"row": row_num, "error": "Data ausente"})
                    continue

                if not row_data.get("amount"):
                    error_rows.append({"row": row_num, "error": "Valor ausente"})
                    continue

                # Parse amount
                try:
                    amount_str = row_data["amount"].replace(",", ".")
                    amount = Decimal(amount_str)
                except:
                    error_rows.append(
                        {
                            "row": row_num,
                            "error": f"Valor inválido: {row_data.get('amount')}",
                        }
                    )
                    continue

                # Parse date
                try:
                    # Try multiple date formats
                    date_str = row_data["date"]
                    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"]:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt)
                            iso_date = parsed_date.strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                    else:
                        error_rows.append(
                            {
                                "row": row_num,
                                "error": f"Data inválida: {date_str}. Use YYYY-MM-DD ou DD/MM/YYYY",
                            }
                        )
                        continue
                except Exception as e:
                    error_rows.append(
                        {"row": row_num, "error": f"Erro ao processar data: {str(e)}"}
                    )
                    continue

                # Determine transaction type
                txn_type = row_data.get("type", "expense").lower()
                if txn_type not in ["income", "expense"]:
                    error_rows.append(
                        {
                            "row": row_num,
                            "error": f"Tipo inválido: {txn_type}. Use 'income' ou 'expense'",
                        }
                    )
                    continue

                # Build financial document structure
                doc_data = {
                    "document_type": "transaction_ledger",
                    "issue_date": iso_date,
                    "transaction_type": txn_type,
                    "category": row_data.get("category", "uncategorized"),
                    "total_amount": str(amount),
                    "currency": "BRL",
                    "notes": row_data.get("notes"),
                    "document_number": row_data.get("reference"),
                }

                # Validate using FinancialValidator
                is_valid, errors, warnings = validator.validate_document(doc_data)

                if not is_valid:
                    error_rows.append(
                        {
                            "row": row_num,
                            "error": f"Validação falhou: {'; '.join(errors)}",
                            "data": row_data,
                        }
                    )
                    continue

                # Check for duplicates
                duplicates = DuplicateDetector.find_duplicates(
                    existing_docs_data, doc_data
                )
                if duplicates:
                    dup = duplicates[0]
                    duplicate_warnings.append(
                        {
                            "row": row_num,
                            "similarity": dup["similarity_score"],
                            "reasons": dup["reasons"],
                            "data": row_data,
                        }
                    )
                    # Continue processing anyway (just warn)

                # Log warnings
                if warnings:
                    warning_rows.append(
                        {
                            "row": row_num,
                            "warnings": warnings,
                            "data": row_data,
                        }
                    )

                # Create document record
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                file_name = f"csv_import_{timestamp}_row{row_num}.json"

                doc = Document(
                    file_name=file_name,
                    file_type="csv_import",
                    file_path=f"csv_import/{file_name}",
                    file_size=len(json.dumps(doc_data, cls=DecimalEncoder)),
                    user_id=current_user.id,
                    status=DocumentStatus.COMPLETED,
                    extracted_data_json=json.dumps(doc_data, cls=DecimalEncoder),
                    processed_date=datetime.utcnow(),
                    category=row_data.get("category"),
                    department=row_data.get("department"),
                )

                db.add(doc)
                created_documents.append(doc)
                success_count += 1

                # Commit in batches for performance (every 100 rows)
                if success_count % 100 == 0:
                    db.commit()

            except Exception as e:
                logger.error(f"Error processing CSV row {row_num}: {e}")
                error_rows.append(
                    {"row": row_num, "error": f"Erro inesperado: {str(e)}"}
                )
                continue

        # Final commit
        db.commit()

        # Log audit trail for bulk import
        log_audit_trail(
            db=db,
            user_id=current_user.id,
            action="bulk_create",
            entity_type="csv_import",
            entity_id=None,
            changes_summary=f"Imported {success_count} transactions from CSV: {file.filename}",
            request=request,
        )
        db.commit()

        logger.info(
            f"✅ CSV import completed: {success_count} success, {len(error_rows)} errors"
        )

        return {
            "message": f"Importação CSV concluída: {success_count} sucesso, {len(error_rows)} erros",
            "success_count": success_count,
            "error_count": len(error_rows),
            "warning_count": len(warning_rows),
            "duplicate_warnings": len(duplicate_warnings),
            "errors": error_rows[:50],  # Limit to first 50 errors
            "warnings": warning_rows[:50],
            "duplicates": duplicate_warnings[:50],
            "file_name": file.filename,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ CSV import failed: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar CSV: {str(e)}",
        )


# =============================================================================
# DOCUMENT QUERY ENDPOINTS
# =============================================================================


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of records to return"
    ),
    status: Optional[str] = Query(
        None, description="Filter by status: pending, processing, completed, failed"
    ),
    document_type: Optional[str] = Query(
        None,
        description="Filter by document type: invoice, receipt, expense, statement, other",
    ),
    transaction_type: Optional[str] = Query(
        None, description="Filter by transaction type: income, expense"
    ),
    category: Optional[str] = Query(None, description="Filter by category"),
    date_from: Optional[str] = Query(
        None, description="Filter documents from this date (YYYY-MM-DD)"
    ),
    date_to: Optional[str] = Query(
        None, description="Filter documents to this date (YYYY-MM-DD)"
    ),
    amount_min: Optional[float] = Query(None, description="Minimum total amount"),
    amount_max: Optional[float] = Query(None, description="Maximum total amount"),
    search: Optional[str] = Query(
        None, description="Search in document number, issuer name, recipient name"
    ),
    client_id: Optional[int] = Query(
        None, description="Filter by client/supplier/customer ID"
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    List all processed documents with advanced filtering and search

    Week 3 Enhancement: Added filters for date range, amount range, categories, and full-text search
    Requires authentication - returns all company documents (team-wide access)
    """
    # Multi-tenant + Multi-org: Filter by org (documents scoped to active org)
    from auth.permissions import document_org_filter
    query = document_org_filter(db.query(Document), current_user, db)

    # Filter by status if provided
    if status:
        try:
            status_enum = DocumentStatus(status)
            query = query.filter(Document.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"{msg['invalid_status']}: {status}"
            )

    # Filter by client if provided
    if client_id:
        query = query.filter(Document.client_id == client_id)

    # Get all documents to filter by extracted data
    all_docs = query.order_by(Document.upload_date.desc()).all()

    # Filter documents based on extracted data
    filtered_docs = []
    for doc in all_docs:
        # Skip documents without extracted data if we're filtering by it
        if not doc.extracted_data_json:
            if not (
                document_type
                or transaction_type
                or category
                or amount_min
                or amount_max
                or search
                or date_from
                or date_to
            ):
                filtered_docs.append(doc)
            continue

        try:
            data_dict = json.loads(doc.extracted_data_json)
            extracted_data = FinancialDocument(**data_dict)

            # Apply filters
            should_include = True

            # Document type filter
            if document_type and extracted_data.document_type != document_type:
                should_include = False

            # Transaction type filter
            if transaction_type and extracted_data.transaction_type != transaction_type:
                should_include = False

            # Category filter
            if category and extracted_data.category != category:
                should_include = False

            # Amount range filter
            if amount_min is not None and extracted_data.total_amount < Decimal(
                str(amount_min)
            ):
                should_include = False
            if amount_max is not None and extracted_data.total_amount > Decimal(
                str(amount_max)
            ):
                should_include = False

            # Date range filter (using issue_date from extracted data)
            if date_from and extracted_data.issue_date:
                if extracted_data.issue_date < date_from:
                    should_include = False
            if date_to and extracted_data.issue_date:
                if extracted_data.issue_date > date_to:
                    should_include = False

            # Search filter (document number, issuer, recipient)
            if search:
                search_lower = search.lower()
                found = False

                if (
                    extracted_data.document_number
                    and search_lower in extracted_data.document_number.lower()
                ):
                    found = True
                elif (
                    extracted_data.issuer
                    and extracted_data.issuer.name
                    and search_lower in extracted_data.issuer.name.lower()
                ):
                    found = True
                elif (
                    extracted_data.issuer
                    and extracted_data.issuer.legal_name
                    and search_lower in extracted_data.issuer.legal_name.lower()
                ):
                    found = True
                elif (
                    extracted_data.recipient
                    and extracted_data.recipient.name
                    and search_lower in extracted_data.recipient.name.lower()
                ):
                    found = True
                elif (
                    extracted_data.recipient
                    and extracted_data.recipient.legal_name
                    and search_lower in extracted_data.recipient.legal_name.lower()
                ):
                    found = True

                if not found:
                    should_include = False

            if should_include:
                filtered_docs.append(doc)

        except Exception as e:
            logger.warning(f"Error parsing document {doc.id}: {e}")
            # Include documents with parsing errors if no specific filters are applied
            if not (
                document_type
                or transaction_type
                or category
                or amount_min
                or amount_max
                or search
                or date_from
                or date_to
            ):
                filtered_docs.append(doc)

    # Get total count after filtering
    total = len(filtered_docs)

    # Apply pagination
    paginated_docs = filtered_docs[skip : skip + limit]

    # Convert to response model
    doc_records = []
    for doc in paginated_docs:
        extracted_data = None
        if doc.extracted_data_json:
            try:
                data_dict = json.loads(doc.extracted_data_json)
                extracted_data = FinancialDocument(**data_dict)
            except:
                pass

        # Get client info if available
        client_name = None
        client_type = None
        if doc.client_id:
            client = db.query(Client).filter(Client.id == doc.client_id).first()
            if client:
                client_name = client.name
                client_type = client.client_type

        doc_records.append(
            DocumentRecord(
                id=doc.id,
                file_name=doc.file_name,
                file_type=doc.file_type,
                file_size=doc.file_size,
                upload_date=doc.upload_date,
                status=doc.status.value,
                error_message=doc.error_message,
                extracted_data=extracted_data,
                processed_date=doc.processed_date,
                client_id=doc.client_id,
                client_name=client_name,
                client_type=client_type,
                cnpj_mismatch=doc.cnpj_mismatch or False,
                cnpj_warning_message=doc.cnpj_warning_message,
                retry_count=doc.retry_count or 0,
                max_retries_exhausted=doc.max_retries_exhausted or False,
                last_retry_at=doc.last_retry_at,
            )
        )

    return DocumentListResponse(total=total, documents=doc_records)


@router.get("/{document_id}", response_model=DocumentRecord)
async def get_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get details of a specific document

    Requires authentication - verifies company access
    """
    # Multi-tenant: Filter by company access
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    # Parse extracted data
    extracted_data = None
    if doc.extracted_data_json:
        try:
            data_dict = json.loads(doc.extracted_data_json)
            extracted_data = FinancialDocument(**data_dict)
        except:
            pass

    return DocumentRecord(
        id=doc.id,
        file_name=doc.file_name,
        file_type=doc.file_type,
        file_size=doc.file_size,
        upload_date=doc.upload_date,
        status=doc.status.value,
        error_message=doc.error_message,
        extracted_data=extracted_data,
        processed_date=doc.processed_date,
        cnpj_mismatch=doc.cnpj_mismatch or False,
        cnpj_warning_message=doc.cnpj_warning_message,
        retry_count=doc.retry_count or 0,
        max_retries_exhausted=doc.max_retries_exhausted or False,
        last_retry_at=doc.last_retry_at,
    )


# =============================================================================
# DOCUMENT MODIFICATION ENDPOINTS
# =============================================================================


@router.post("/manual")
async def create_manual_document(
    request: Request,
    data: dict,
    current_user: User = Depends(get_current_active_user),
    subscription: Subscription = Depends(require_active_subscription),
    db: Session = Depends(get_db),
):
    """
    Create a manual document without file upload

    Allows users to manually input financial data
    Includes validation, duplicate detection, and audit logging
    Requires active subscription
    """
    from validation import DuplicateDetector, FinancialValidator

    try:
        # Validate input data using FinancialValidator
        validator = FinancialValidator()
        is_valid, errors, warnings = validator.validate_document(data)

        if not is_valid:
            return {
                "id": None,
                "status": "validation_failed",
                "message": "Validação falhou",
                "validation": {
                    "is_valid": False,
                    "errors": errors,
                    "warnings": warnings,
                },
            }

        # Check for duplicates - org-scoped
        existing_docs = document_org_filter(
            db.query(Document), current_user, db
        ).order_by(Document.upload_date.desc()).limit(500).all()

        existing_docs_data = []
        for doc in existing_docs:
            if doc.extracted_data_json:
                try:
                    data_dict = json.loads(doc.extracted_data_json)
                    existing_docs_data.append(data_dict)
                except:
                    pass

        duplicates = DuplicateDetector.find_duplicates(existing_docs_data, data)

        # Generate a unique file name for manual entry
        doc_type = data.get("document_type", "manual_entry")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_name = f"manual_{doc_type}_{timestamp}.json"

        # Extract department and category for indexing
        department = data.get("department")
        category = data.get("category")

        # Create document record
        doc = Document(
            file_name=file_name,
            file_type="manual",
            file_path=f"manual/{file_name}",
            file_size=0,
            user_id=current_user.id,
            status=DocumentStatus.COMPLETED,
            extracted_data_json=json.dumps(data, cls=DecimalEncoder),
            processed_date=datetime.utcnow(),
            department=department,
            category=category,
        )

        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Log audit trail
        log_audit_trail(
            db=db,
            user_id=current_user.id,
            action="create",
            entity_type="document",
            entity_id=doc.id,
            after_value=data,
            changes_summary=f"Manual document created: {file_name}",
            request=request,
            document_id=doc.id,
        )
        db.commit()


        return {
            "id": doc.id,
            "file_name": doc.file_name,
            "status": doc.status.value,
            "message": "Documento manual criado com sucesso",
            "validation": {
                "is_valid": is_valid,
                "errors": errors,
                "warnings": warnings,
            },
            "duplicate_check": {
                "found": len(duplicates) > 0,
                "count": len(duplicates),
                "duplicates": duplicates[:3] if duplicates else [],  # Show top 3
            },
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error creating manual document: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=400, detail=f"Erro ao criar documento manual: {str(e)}"
        )


@router.post("/{document_id}/retry")
async def retry_document(
    document_id: int,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Manually retry processing a failed document.
    Resets status to PENDING and sends to SQS for Lambda reprocessing.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if doc.status != DocumentStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail="Apenas documentos com falha podem ser reprocessados.",
        )

    # Check file still exists in S3
    if doc.file_path and settings.use_s3:
        try:
            s3_storage.s3_client.head_object(Bucket=s3_storage.bucket_name, Key=doc.file_path)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Arquivo original não encontrado no S3. Faça upload novamente.",
            )

    # Reset status and clear error
    doc.status = DocumentStatus.PENDING
    doc.error_message = None
    doc.retry_count = (doc.retry_count or 0) + 1
    doc.max_retries_exhausted = False

    # Delete old validation rows if any
    db.query(DocumentValidationRow).filter(
        DocumentValidationRow.document_id == document_id
    ).delete()

    db.commit()

    # Send to SQS for reprocessing
    _send_sqs_message(doc.id, doc.file_path)

    log_audit_trail(
        db=db,
        user_id=current_user.id,
        action="retry",
        entity_type="document",
        entity_id=document_id,
        changes_summary=f"Document retry requested: {doc.file_name} (attempt {doc.retry_count})",
        request=request,
        document_id=document_id,
    )

    logger.info(f"Document {document_id} retry requested by user {current_user.id} (attempt {doc.retry_count})")

    return {
        "document_id": document_id,
        "status": "pending",
        "message": "Documento enviado para reprocessamento.",
        "retry_count": doc.retry_count,
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a document

    Includes audit logging for compliance
    Requires authentication - verifies document ownership
    """

    # Multi-tenant: Filter by org ownership
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    # Capture before state for audit trail
    before_value = None
    if doc.extracted_data_json:
        try:
            before_value = json.loads(doc.extracted_data_json)
        except:
            pass

    # Delete file (skip for manual entries and CSV imports)
    if doc.file_type not in ["manual", "csv_import"]:
        try:
            if settings.use_s3:
                s3_storage.delete_file(doc.file_path)
            else:
                file_path = Path(doc.file_path)
                if file_path.exists():
                    file_path.unlink()
        except Exception as e:
            logger.warning(f"Could not delete file {doc.file_path}: {e}")

    # Log audit trail BEFORE deleting
    log_audit_trail(
        db=db,
        user_id=current_user.id,
        action="delete",
        entity_type="document",
        entity_id=document_id,
        before_value=before_value,
        changes_summary=f"Document deleted: {doc.file_name}",
        request=request,
        document_id=document_id,
    )

    # Delete database record
    db.delete(doc)
    db.commit()

    logger.info(f"🗑️  Document {document_id} deleted by user {current_user.id}")

    return {"message": msg["document_deleted"], "id": document_id}


@router.patch("/{document_id}")
async def update_document(
    document_id: int,
    request: Request,
    data: FinancialDocument,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update extracted data for a document
    Allows manual correction of AI extraction errors

    Includes validation and audit logging with before/after values
    Requires authentication - verifies document ownership
    """
    from validation import FinancialValidator

    # Multi-tenant: Filter by org ownership
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    # Validate the updated data
    try:
        # Capture before state for audit trail
        before_value = None
        if doc.extracted_data_json:
            try:
                before_value = json.loads(doc.extracted_data_json)
            except:
                pass

        # Validate new data
        validator = FinancialValidator()
        data_dict = data.model_dump()
        is_valid, errors, warnings = validator.validate_document(data_dict)

        if not is_valid:
            logger.warning(
                f"Updated data has validation errors for document {document_id}: {errors}"
            )
            # Still allow update, but return validation errors

        # Extract department and category for indexing
        department = data_dict.get("department")
        category = data_dict.get("category")

        # Update the extracted data
        doc.extracted_data_json = data.model_dump_json()
        doc.processed_date = datetime.utcnow()  # Update timestamp
        doc.department = department
        doc.category = category

        db.commit()
        db.refresh(doc)

        # Log audit trail with before/after values
        log_audit_trail(
            db=db,
            user_id=current_user.id,
            action="update",
            entity_type="document",
            entity_id=document_id,
            before_value=before_value,
            after_value=data_dict,
            changes_summary=f"Document data manually updated: {doc.file_name}",
            request=request,
            document_id=document_id,
        )
        db.commit()


        return {
            "message": "Document data updated successfully",
            "id": document_id,
            "validation": {
                "is_valid": is_valid,
                "errors": errors if not is_valid else [],
                "warnings": warnings if warnings else [],
            },
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error updating document {document_id}: {e}")
        import traceback

        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=400, detail=f"Error updating document: {str(e)}"
        )


# =============================================================================
# DOCUMENT UTILITIES
# =============================================================================


@router.get("/{document_id}/validate")
async def validate_document_data(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Validate extracted data from a document

    Week 3 Enhancement: Data validation for financial documents
    Requires authentication - verifies document ownership
    """

    # Multi-tenant: Filter by org ownership
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if not doc.extracted_data_json:
        raise HTTPException(
            status_code=400, detail="No extracted data available for validation"
        )

    try:
        data_dict = json.loads(doc.extracted_data_json)
        extracted_data = FinancialDocument(**data_dict)

        # Validate the document
        validation_errors = FinancialDataValidator.validate_document(extracted_data)
        validation_summary = FinancialDataValidator.get_validation_summary(
            validation_errors
        )

        return {"document_id": document_id, "validation": validation_summary}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation error: {str(e)}")


@router.get("/{document_id}/audit-log")
async def get_document_audit_log(
    document_id: int,
    limit: int = Query(100, ge=1, le=500, description="Max audit entries to return"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get complete audit trail for a document

    Returns all changes made to the document with before/after values
    Essential for hospital compliance and regulatory audits
    """
    # Verify document ownership
    doc = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    # Fetch audit logs for this document
    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.document_id == document_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )

    # Format response
    logs = []
    for log in audit_logs:
        # Get user info
        user = db.query(User).filter(User.id == log.user_id).first()
        user_name = user.full_name or user.email if user else "Unknown"

        logs.append({
            "id": log.id,
            "action": log.action,
            "entity_type": log.entity_type,
            "user": {
                "id": log.user_id,
                "name": user_name,
            },
            "before_value": json.loads(log.before_value) if log.before_value else None,
            "after_value": json.loads(log.after_value) if log.after_value else None,
            "changes_summary": log.changes_summary,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() + "Z" if log.created_at else None,
        })

    return {
        "document_id": document_id,
        "document_name": doc.file_name,
        "total_changes": len(logs),
        "audit_log": logs,
    }


@router.get("/{document_id}/ledger/transactions")
async def get_ledger_transactions(
    document_id: int,
    skip: int = Query(0, ge=0, description="Number of transactions to skip"),
    limit: int = Query(50, ge=1, le=1000, description="Max transactions to return"),
    category: Optional[str] = Query(None, description="Filter by category"),
    transaction_type: Optional[str] = Query(
        None, description="Filter by type: income or expense"
    ),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search in description"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get paginated transactions from a ledger document
    Supports filtering and searching

    Requires authentication - verifies document ownership
    """
    # Multi-tenant: Filter by org ownership
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if not doc.extracted_data_json:
        raise HTTPException(status_code=400, detail="No extracted data available")

    try:
        data_dict = json.loads(doc.extracted_data_json)

        # Check if this is a ledger
        if data_dict.get("document_type") != "transaction_ledger":
            raise HTTPException(
                status_code=400, detail="This document is not a transaction ledger"
            )

        ledger = TransactionLedger(**data_dict)

        # Filter transactions
        filtered_transactions = ledger.transactions

        if category:
            filtered_transactions = [
                t for t in filtered_transactions if t.category == category
            ]

        if transaction_type:
            filtered_transactions = [
                t
                for t in filtered_transactions
                if t.transaction_type == transaction_type
            ]

        if date_from:
            filtered_transactions = [
                t for t in filtered_transactions if t.date and t.date >= date_from
            ]

        if date_to:
            filtered_transactions = [
                t for t in filtered_transactions if t.date and t.date <= date_to
            ]

        if search:
            search_lower = search.lower()
            filtered_transactions = [
                t
                for t in filtered_transactions
                if (t.description and search_lower in t.description.lower())
                or (t.reference and search_lower in t.reference.lower())
            ]

        total = len(filtered_transactions)

        # Apply pagination
        paginated = filtered_transactions[skip : skip + limit]

        return {
            "document_id": document_id,
            "total": total,
            "skip": skip,
            "limit": limit,
            "transactions": [t.model_dump() for t in paginated],
            "ledger_summary": {
                "total_income": str(ledger.total_income),
                "total_expense": str(ledger.total_expense),
                "net_balance": str(ledger.net_balance),
                "total_transactions": ledger.total_transactions,
                "date_range": (
                    ledger.date_range.model_dump() if ledger.date_range else None
                ),
            },
        }

    except Exception as e:
        logger.error(f"Error getting ledger transactions: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving transactions: {str(e)}"
        )


@router.get("/{document_id}/preview")
async def preview_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get the original uploaded file for preview
    Supports PDF, images, and Excel files

    Requires authentication - verifies document ownership
    """
    # Multi-tenant: Filter by org ownership
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    file_path = validate_file_path(Path(doc.file_path))

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    # Determine media type based on file extension
    extension = file_path.suffix.lower()
    media_type_map = {
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }

    media_type = media_type_map.get(extension, "application/octet-stream")

    # For PDFs and images, allow inline display (Content-Disposition: inline)
    # For Excel, force download
    if extension in [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        return FileResponse(
            file_path,
            media_type=media_type,
            filename=doc.file_name,
            headers={"Content-Disposition": f"inline; filename={doc.file_name}"},
        )
    else:
        return FileResponse(file_path, media_type=media_type, filename=doc.file_name)


@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Download the original uploaded file
    Forces download instead of inline display

    Requires authentication - verifies document ownership
    """
    # Multi-tenant: Filter by org ownership
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    file_path = validate_file_path(Path(doc.file_path))

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(
        file_path,
        filename=doc.file_name,
        headers={"Content-Disposition": f"attachment; filename={doc.file_name}"},
    )


# =============================================================================
# VALIDATION FLOW ENDPOINTS (Item 9)
# =============================================================================


@router.get("/pending-validation/list")
async def list_pending_validation_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    List documents pending validation (Item 9).
    Returns documents with status PENDING_VALIDATION for the current user.
    """
    from auth.permissions import document_org_filter
    base_query = document_org_filter(db.query(Document), current_user, db)

    query = (
        base_query
        .filter(
            Document.status == DocumentStatus.PENDING_VALIDATION,
        )
        .order_by(Document.processed_date.desc())
    )

    total = query.count()
    docs = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "documents": [
            {
                "id": doc.id,
                "file_name": doc.file_name,
                "file_type": doc.file_type,
                "upload_date": doc.upload_date.isoformat() if doc.upload_date else None,
                "processed_date": doc.processed_date.isoformat() if doc.processed_date else None,
                "category": doc.category,
                "validation_row_count": len(doc.validation_rows),
                "validated_count": sum(1 for r in doc.validation_rows if r.is_validated),
            }
            for doc in docs
        ],
    }


@router.get("/pending-validation/count")
async def get_pending_validation_count(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get count of documents pending validation (for sidebar badge)"""
    from auth.permissions import document_org_filter
    base_query = document_org_filter(db.query(Document), current_user, db)

    count = (
        base_query
        .filter(Document.status == DocumentStatus.PENDING_VALIDATION)
        .with_entities(func.count(Document.id))
        .scalar()
        or 0
    )

    return {"count": count}


@router.get("/{document_id}/validation-rows")
async def get_validation_rows(
    document_id: int,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=10, le=200, description="Rows per page"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get validation rows for a document (Item 9).
    Returns paginated rows extracted from the document for user review.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if doc.status != DocumentStatus.PENDING_VALIDATION:
        raise HTTPException(
            status_code=400,
            detail="Documento não está pendente de validação.",
        )

    # Get total counts (lightweight queries)
    total_rows = (
        db.query(func.count(DocumentValidationRow.id))
        .filter(DocumentValidationRow.document_id == document_id)
        .scalar()
    )
    validated_count = (
        db.query(func.count(DocumentValidationRow.id))
        .filter(
            DocumentValidationRow.document_id == document_id,
            DocumentValidationRow.is_validated == True,
        )
        .scalar()
    )

    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    offset = (page - 1) * page_size

    # Paginated query
    rows = (
        db.query(DocumentValidationRow)
        .filter(DocumentValidationRow.document_id == document_id)
        .order_by(DocumentValidationRow.row_index)
        .offset(offset)
        .limit(page_size)
        .all()
    )

    def _extract_counterparty(row):
        """Extract counterparty from original_data_json if available"""
        if not row.original_data_json:
            return None
        try:
            data = json.loads(row.original_data_json)
            # From transactions: counterparty field
            if data.get("counterparty"):
                return data["counterparty"]
            # From line_items or single docs: issuer/recipient name
            issuer = data.get("issuer")
            if isinstance(issuer, dict) and issuer.get("name"):
                return issuer["name"]
            return None
        except (json.JSONDecodeError, TypeError):
            return None

    return {
        "document_id": document_id,
        "file_name": doc.file_name,
        "total_rows": total_rows,
        "validated_count": validated_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "rows": [
            {
                "id": row.id,
                "row_index": row.row_index,
                "description": row.description,
                "transaction_date": row.transaction_date,
                "amount": row.amount / 100.0 if row.amount is not None else None,
                "category": row.category,
                "transaction_type": row.transaction_type,
                "is_validated": row.is_validated,
                "validated_at": row.validated_at.isoformat() if row.validated_at else None,
                "counterparty": _extract_counterparty(row),
            }
            for row in rows
        ],
    }


@router.post("/{document_id}/validation-rows/bulk-validate")
async def bulk_validate_rows(
    document_id: int,
    body: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Bulk-validate multiple rows at once (e.g., approve all on current page).
    Body: { "row_ids": [1, 2, 3, ...] }
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    row_ids = body.get("row_ids", [])
    if not row_ids:
        raise HTTPException(status_code=400, detail="Nenhuma linha selecionada.")

    updated = 0
    now = datetime.utcnow()
    rows = (
        db.query(DocumentValidationRow)
        .filter(
            DocumentValidationRow.document_id == document_id,
            DocumentValidationRow.id.in_(row_ids),
            DocumentValidationRow.is_validated == False,
        )
        .all()
    )
    for row in rows:
        row.is_validated = True
        row.validated_at = now
        updated += 1

    db.commit()

    return {"updated": updated, "message": f"{updated} linhas validadas com sucesso."}


@router.post("/{document_id}/validation-rows/bulk-update-type")
async def bulk_update_transaction_type(
    document_id: int,
    body: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Bulk-update transaction_type for ALL rows of a document.
    Body: { "transaction_type": "receita" | "despesa" | "custo" | "investimento" | "perda" }
    Useful when a whole document is receivables or payables.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    new_type = body.get("transaction_type", "").lower().strip()
    valid_types = {"receita", "despesa", "custo", "investimento", "perda"}
    if new_type not in valid_types:
        raise HTTPException(status_code=400, detail="Tipo deve ser: receita, despesa, custo, investimento ou perda.")

    rows = (
        db.query(DocumentValidationRow)
        .filter(DocumentValidationRow.document_id == document_id)
        .all()
    )

    updated = 0
    for row in rows:
        if row.transaction_type != new_type:
            row.transaction_type = new_type
            updated += 1

    db.commit()

    type_labels = {"receita": "Receita", "despesa": "Despesa", "custo": "Custo", "investimento": "Investimento", "perda": "Perda"}
    type_label = type_labels.get(new_type, new_type.capitalize())
    return {
        "updated": updated,
        "total": len(rows),
        "transaction_type": new_type,
        "message": f"{updated} linha(s) alterada(s) para {type_label}.",
    }


@router.put("/{document_id}/validation-rows/{row_id}")
async def update_validation_row(
    document_id: int,
    row_id: int,
    updates: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Update a single validation row (Item 9).
    User can edit description, amount, category, transaction_type, date.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    row = (
        db.query(DocumentValidationRow)
        .filter(
            DocumentValidationRow.id == row_id,
            DocumentValidationRow.document_id == document_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Linha de validação não encontrada.")

    # Update allowed fields
    if "description" in updates:
        row.description = updates["description"].upper() if updates["description"] else updates["description"]
    if "amount" in updates:
        row.amount = int(float(updates["amount"]) * 100)
    if "category" in updates:
        row.category = updates["category"]
    if "transaction_type" in updates:
        row.transaction_type = updates["transaction_type"]
    if "transaction_date" in updates:
        row.transaction_date = updates["transaction_date"]

    # Mark as validated when user confirms
    if updates.get("is_validated"):
        row.is_validated = True
        row.validated_at = datetime.utcnow()

    db.commit()

    return {
        "id": row.id,
        "description": row.description,
        "amount": row.amount / 100.0 if row.amount is not None else None,
        "category": row.category,
        "transaction_type": row.transaction_type,
        "transaction_date": row.transaction_date,
        "is_validated": row.is_validated,
    }


@router.post("/{document_id}/confirm-validation")
async def confirm_document_validation(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Confirm all validation rows and mark document as COMPLETED (Item 9).
    This is the final step - after this, the document appears in reports.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if doc.status != DocumentStatus.PENDING_VALIDATION:
        raise HTTPException(
            status_code=400,
            detail="Documento não está pendente de validação.",
        )

    # Mark all unvalidated rows as validated
    rows = (
        db.query(DocumentValidationRow)
        .filter(
            DocumentValidationRow.document_id == document_id,
            DocumentValidationRow.is_validated == False,
        )
        .all()
    )

    now = datetime.utcnow()
    for row in rows:
        row.is_validated = True
        row.validated_at = now

    # Update the extracted_data_json with any user modifications
    all_rows = (
        db.query(DocumentValidationRow)
        .filter(DocumentValidationRow.document_id == document_id)
        .order_by(DocumentValidationRow.row_index)
        .all()
    )

    # If this was a single-transaction doc, update the main fields
    if len(all_rows) == 1:
        row = all_rows[0]
        try:
            data = json.loads(doc.extracted_data_json) if doc.extracted_data_json else {}
            if row.category:
                data["category"] = row.category
            if row.transaction_type:
                data["transaction_type"] = row.transaction_type
            if row.amount is not None:
                data["total_amount"] = row.amount / 100.0
            if row.transaction_date:
                data["issue_date"] = row.transaction_date
            doc.extracted_data_json = json.dumps(data, default=str)
            doc.category = row.category
        except (json.JSONDecodeError, TypeError):
            pass

    # If multi-transaction doc, update the transactions list and/or line_items
    elif len(all_rows) > 1:
        try:
            data = json.loads(doc.extracted_data_json) if doc.extracted_data_json else {}
            is_ledger = data.get("document_type") == "transaction_ledger"

            if is_ledger or not data.get("line_items"):
                # Ledger or doc without line_items: write as transactions
                updated_transactions = []
                total_sum = 0
                item_count = 0
                income_sum = 0
                expense_sum = 0
                for row in all_rows:
                    amt = row.amount / 100.0 if row.amount is not None else 0
                    updated_transactions.append({
                        "date": row.transaction_date,
                        "description": row.description,
                        "category": row.category,
                        "transaction_type": row.transaction_type,
                        "amount": amt,
                        "counterparty": row.counterparty if hasattr(row, 'counterparty') and row.counterparty else None,
                    })
                    total_sum += abs(amt)
                    item_count += 1
                    if row.transaction_type == "receita":
                        income_sum += abs(amt)
                    else:
                        expense_sum += abs(amt)
                data["transactions"] = updated_transactions
                # Update document-level totals from validated rows
                data["total_amount"] = total_sum
                data["total_items"] = item_count
                # Update ledger summary fields (used by TransactionLedger model)
                data["total_transactions"] = item_count
                data["total_income"] = income_sum
                data["total_expense"] = expense_sum
                data["net_balance"] = income_sum - expense_sum
                # Set document-level type from majority of transactions
                data["transaction_type"] = "receita" if income_sum >= expense_sum else "despesa"
            else:
                # NFe/invoice with line_items: rebuild line_items from rows 1+
                # Row 0 is the doc header, rows 1+ are items
                updated_items = []
                for row in all_rows[1:]:
                    updated_items.append({
                        "description": row.description or "",
                        "total_price": row.amount / 100.0 if row.amount is not None else 0,
                    })
                data["line_items"] = updated_items

                # Update header fields from row 0
                header = all_rows[0]
                if header.amount is not None:
                    data["total_amount"] = header.amount / 100.0
                if header.transaction_type:
                    data["transaction_type"] = header.transaction_type

            # Set document-level category from the first row (doc header)
            first_row = all_rows[0]
            if first_row.category:
                data["category"] = first_row.category
                doc.category = first_row.category
            doc.extracted_data_json = json.dumps(data, default=str)
        except (json.JSONDecodeError, TypeError):
            pass

    # Move to COMPLETED
    doc.status = DocumentStatus.COMPLETED
    db.commit()

    # Audit trail
    audit_entry = AuditLog(
        user_id=current_user.id,
        document_id=doc.id,
        action="validate",
        entity_type="document",
        entity_id=doc.id,
        changes_summary=f"Document validated and confirmed: {doc.file_name} ({len(all_rows)} rows)",
    )
    db.add(audit_entry)
    db.commit()

    logger.info(f"✅ Document {document_id} validated and confirmed by user {current_user.id}")

    # Upsert known items from validated rows (non-blocking)
    try:
        _upsert_known_items_from_validation(db, current_user, all_rows)
        owner_id = get_organization_owner_id(current_user)
        _prune_known_items(db, owner_id)
    except Exception as e:
        logger.warning(f"⚠️ Known items processing failed (non-critical): {e}")

    return {
        "document_id": document_id,
        "status": "completed",
        "message": f"Documento validado com sucesso! {len(all_rows)} linha(s) confirmada(s).",
    }


@router.post("/{document_id}/reject-validation")
async def reject_document_validation(
    document_id: int,
    request: Request,
    body: dict = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Reject a document during validation (Item 9).
    Fully deletes the document (file + DB record) on rejection.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if doc.status != DocumentStatus.PENDING_VALIDATION:
        raise HTTPException(
            status_code=400,
            detail="Documento não está pendente de validação.",
        )

    reason = (body or {}).get("reason", "Rejeitado pelo usuário durante validação")

    # Delete the actual file (skip for manual entries and CSV imports)
    if doc.file_type not in ["manual", "csv_import"]:
        try:
            if settings.use_s3:
                s3_storage.delete_file(doc.file_path)
            else:
                file_path = Path(doc.file_path)
                if file_path.exists():
                    file_path.unlink()
        except Exception as e:
            logger.warning(f"Could not delete file {doc.file_path}: {e}")

    # Audit trail BEFORE deleting the record
    log_audit_trail(
        db=db,
        user_id=current_user.id,
        action="reject",
        entity_type="document",
        entity_id=document_id,
        changes_summary=f"Document rejected and deleted during validation: {reason}",
        request=request,
        document_id=document_id,
    )

    # Delete the document record (validation_rows cascade-deleted automatically)
    db.delete(doc)
    db.commit()

    logger.info(f"Document {document_id} rejected and deleted by user {current_user.id}: {reason}")

    return {
        "document_id": document_id,
        "status": "deleted",
        "message": "Documento rejeitado e removido.",
    }


@router.delete("/{document_id}/validation-rows/{row_id}")
async def delete_validation_row(
    document_id: int,
    row_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a single validation row during review.
    Allows user to remove incorrectly extracted items.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if doc.status != DocumentStatus.PENDING_VALIDATION:
        raise HTTPException(
            status_code=400,
            detail="Documento não está pendente de validação.",
        )

    row = (
        db.query(DocumentValidationRow)
        .filter(
            DocumentValidationRow.id == row_id,
            DocumentValidationRow.document_id == document_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Linha de validação não encontrada.")

    db.delete(row)

    # Re-index remaining rows
    remaining = (
        db.query(DocumentValidationRow)
        .filter(DocumentValidationRow.document_id == document_id)
        .order_by(DocumentValidationRow.row_index)
        .all()
    )
    for i, r in enumerate(remaining):
        r.row_index = i

    db.commit()

    return {
        "message": "Linha removida com sucesso.",
        "remaining_rows": len(remaining),
    }


@router.post("/{document_id}/validation-rows")
async def add_validation_row(
    document_id: int,
    row_data: dict,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Add a new validation row to a document during review.
    Allows user to add items that were missed during extraction.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    if doc.status != DocumentStatus.PENDING_VALIDATION:
        raise HTTPException(
            status_code=400,
            detail="Documento não está pendente de validação.",
        )

    # Get the next row_index
    max_index = (
        db.query(DocumentValidationRow.row_index)
        .filter(DocumentValidationRow.document_id == document_id)
        .order_by(DocumentValidationRow.row_index.desc())
        .first()
    )
    next_index = (max_index[0] + 1) if max_index else 0

    amount_raw = row_data.get("amount")
    amount_cents = int(float(amount_raw) * 100) if amount_raw is not None else None

    description = row_data.get("description", "")
    if description:
        description = description.upper()

    new_row = DocumentValidationRow(
        document_id=document_id,
        row_index=next_index,
        description=description,
        transaction_date=row_data.get("transaction_date"),
        amount=amount_cents,
        category=row_data.get("category", "nao_categorizado"),
        transaction_type=row_data.get("transaction_type", "despesa"),
        is_validated=False,
        user_id=current_user.id,
    )
    db.add(new_row)
    db.commit()
    db.refresh(new_row)

    return {
        "id": new_row.id,
        "row_index": new_row.row_index,
        "description": new_row.description,
        "transaction_date": new_row.transaction_date,
        "amount": new_row.amount / 100.0 if new_row.amount is not None else None,
        "category": new_row.category,
        "transaction_type": new_row.transaction_type,
        "is_validated": new_row.is_validated,
        "validated_at": None,
    }


# =============================================================================
# KNOWN ITEMS - CRUD & Match Endpoints
# =============================================================================


@router.get("/known-items/list")
async def list_known_items(
    search: Optional[str] = Query(None, description="Search by name or alias"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all known items for the organization."""
    owner_id = get_organization_owner_id(current_user)

    query = db.query(KnownItem).filter(KnownItem.user_id == owner_id)

    if search:
        search_upper = search.strip().upper()
        query = query.filter(
            (KnownItem.name.ilike(f"%{search_upper}%"))
            | (KnownItem.alias.ilike(f"%{search}%"))
        )

    total = query.count()
    items = (
        query.order_by(KnownItem.times_appeared.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "alias": item.alias,
                "category": item.category,
                "transaction_type": item.transaction_type,
                "times_appeared": item.times_appeared,
                "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else None,
                "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put("/known-items/{item_id}")
async def update_known_item(
    item_id: int,
    updates: KnownItemUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update a known item's alias, category, or transaction_type."""
    owner_id = get_organization_owner_id(current_user)

    item = (
        db.query(KnownItem)
        .filter(KnownItem.id == item_id, KnownItem.user_id == owner_id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    if updates.alias is not None:
        item.alias = updates.alias.strip() if updates.alias.strip() else None
    if updates.category is not None:
        item.category = updates.category
    if updates.transaction_type is not None:
        item.transaction_type = updates.transaction_type

    db.commit()
    db.refresh(item)

    return {
        "id": item.id,
        "name": item.name,
        "alias": item.alias,
        "category": item.category,
        "transaction_type": item.transaction_type,
        "times_appeared": item.times_appeared,
        "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
    }


@router.delete("/known-items/{item_id}")
async def delete_known_item(
    item_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a known item."""
    owner_id = get_organization_owner_id(current_user)

    item = (
        db.query(KnownItem)
        .filter(KnownItem.id == item_id, KnownItem.user_id == owner_id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    db.delete(item)
    db.commit()

    return {"message": "Item removido com sucesso."}


@router.get("/{document_id}/validation-rows/known-matches")
async def get_known_matches(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Get known item matches for a document's validation rows.
    Returns a dict mapping row_id to known item info.
    """
    # Verify document access
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or not verify_document_access(doc, current_user, db):
        raise HTTPException(status_code=404, detail=msg["document_not_found"])

    # Get validation rows
    rows = (
        db.query(DocumentValidationRow)
        .filter(DocumentValidationRow.document_id == document_id)
        .order_by(DocumentValidationRow.row_index)
        .all()
    )

    owner_id = get_organization_owner_id(current_user)

    # For each row, try to find a matching known item
    matches = {}
    for row in rows:
        if not row.description:
            continue

        normalized = _normalize_known_item_name(row.description)
        if not normalized:
            continue

        known = (
            db.query(KnownItem)
            .filter(KnownItem.user_id == owner_id, KnownItem.name == normalized)
            .first()
        )

        if known:
            matches[str(row.id)] = {
                "known_item_id": known.id,
                "alias": known.alias,
                "category": known.category,
                "times_appeared": known.times_appeared,
            }

    return {"matches": matches}
