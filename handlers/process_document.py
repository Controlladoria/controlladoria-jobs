"""
Lambda handler for document processing (triggered by SQS).

Receives messages from SQS with document_id and file_path (S3 key),
downloads the file from S3, processes it with AI extraction,
and updates the database with results.

This is the same logic that was in ControlladorIA's routers/documents.py
process_document_background(), now running as a Lambda function.
"""

import json
import logging
import os
import sys
import tempfile

# Add parent directory to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    SQS-triggered Lambda handler for document processing.

    Expected SQS message body:
    {
        "document_id": 123,
        "file_path": "users/1/uuid-filename.pdf"  (S3 key)
    }
    """
    from database import SessionLocal

    # Process each SQS record (batch size should be 1 for doc processing)
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        document_id = body["document_id"]
        file_path = body["file_path"]

        logger.info(f"Processing document {document_id} from S3: {file_path}")

        # Download file from S3 to /tmp
        local_path = _download_from_s3(file_path)
        if not local_path:
            logger.error(f"Failed to download {file_path} from S3")
            _mark_document_failed(document_id, "Falha ao baixar arquivo do S3")
            continue

        try:
            # Run the actual document processing (pass Lambda context for timeout awareness)
            _process_document(document_id, local_path, lambda_context=context)
        except Exception as e:
            logger.error(f"Document {document_id} processing failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            _mark_document_failed(document_id, f"Erro no processamento: {e}")
        finally:
            # Clean up temp file
            try:
                os.unlink(local_path)
            except OSError:
                pass

    return {"statusCode": 200, "body": "OK"}


def _download_from_s3(s3_key: str) -> str | None:
    """Download a file from S3 to a temp location. Returns local path or None."""
    import boto3
    from pathlib import Path

    try:
        # Always let boto3 handle credentials automatically.
        # In Lambda: uses execution role (STS temp creds with session token).
        # Locally: uses ~/.aws/credentials or env vars.
        # NEVER pass settings.aws_access_key_id — pydantic picks up Lambda's
        # auto-injected AWS_ACCESS_KEY_ID (STS temp creds) but without the
        # session token, causing 403.
        s3 = boto3.client("s3", region_name=settings.aws_region)

        # Preserve file extension for processor detection
        ext = Path(s3_key).suffix
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir="/tmp")
        tmp.close()

        logger.debug(f"Downloading from bucket={settings.s3_bucket_name} key={s3_key}")
        s3.download_file(settings.s3_bucket_name, s3_key, tmp.name)
        logger.debug(f"Downloaded {s3_key} to {tmp.name}")
        return tmp.name
    except Exception as e:
        logger.error(f"S3 download failed: bucket={settings.s3_bucket_name} key={s3_key} error={e}")
        return None


def _mark_document_failed(document_id: int, error_message: str):
    """Mark a document as FAILED in the database."""
    from database import SessionLocal, Document, DocumentStatus

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc:
            doc.status = DocumentStatus.FAILED
            doc.error_message = error_message
            db.commit()
    finally:
        db.close()


def _process_document(document_id: int, file_path: str, lambda_context=None):
    """
    Process a document with AI extraction.

    Supports incremental chunk saving for large spreadsheets:
    - Each chunk's transactions are saved as validation rows immediately
    - Progress tracked in Document.extracted_data_json
    - On Lambda timeout + SQS retry, resumes from last completed chunk
    """
    from datetime import datetime
    from database import (
        SessionLocal, Document, DocumentStatus, DocumentValidationRow,
        User, Client, AuditLog, KnownItem, Organization, OrgMembership,
    )
    from structured_processor import StructuredDocumentProcessor
    from validation import FinancialValidator
    from routers.documents import (
        _get_known_items_for_prompt,
        _handle_nfe_cancellation,
        _create_validation_rows,
        _batch_categorize_uncategorized_rows,
        _normalize_nf_number,
        find_or_create_client,
    )
    from i18n_errors import get_friendly_error_message
    from auth.team_management import get_organization_owner_id
    from accounting.categories import resolve_category_name
    from accounting import is_income_type
    from sqlalchemy import func

    processor = StructuredDocumentProcessor()
    db = SessionLocal()

    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"Document {document_id} not found")
            return

        user = db.query(User).filter(User.id == doc.user_id).first()
        user_company_info = None
        if user:
            user_company_info = {
                "company_name": user.company_name or user.full_name,
                "legal_name": user.full_name,
                "cnpj": user.cnpj,
            }

        # Check for resume — if we have progress from a previous run
        progress = {}
        skip_chunks = None
        try:
            if doc.extracted_data_json:
                progress = json.loads(doc.extracted_data_json)
                if isinstance(progress, dict) and "chunks_completed" in progress:
                    skip_chunks = set(progress["chunks_completed"])
                    logger.info(
                        f"Resuming document {document_id}: "
                        f"{len(skip_chunks)}/{progress.get('chunks_total', '?')} chunks already done"
                    )
        except (json.JSONDecodeError, TypeError):
            pass

        # Update status to processing
        doc.status = DocumentStatus.PROCESSING
        db.commit()

        # Fetch known items for AI context
        known_items_context = []
        try:
            owner_id = get_organization_owner_id(user) if user else None
            if owner_id:
                known_items_context = _get_known_items_for_prompt(db, owner_id)
        except Exception as e:
            logger.warning(f"Failed to load known items: {e}")

        # --- Incremental chunk saving callback ---
        # Count existing validation rows (from previous partial run)
        existing_row_count = (
            db.query(func.count(DocumentValidationRow.id))
            .filter(DocumentValidationRow.document_id == document_id)
            .scalar() or 0
        )
        row_offset = existing_row_count  # Start row_index after existing rows

        def on_chunk_complete(chunk_index, transactions):
            """Save this chunk's transactions as validation rows immediately."""
            nonlocal row_offset
            for i, txn in enumerate(transactions):
                amt = txn.amount if hasattr(txn, 'amount') else float(txn.get('amount', 0) if isinstance(txn, dict) else 0)
                desc = txn.description if hasattr(txn, 'description') else (txn.get('description', '') if isinstance(txn, dict) else '')
                date = txn.date if hasattr(txn, 'date') else (txn.get('date', '') if isinstance(txn, dict) else '')
                cat = txn.category if hasattr(txn, 'category') else (txn.get('category', '') if isinstance(txn, dict) else '')
                txn_type = txn.transaction_type if hasattr(txn, 'transaction_type') else (txn.get('transaction_type', '') if isinstance(txn, dict) else '')
                counterparty = txn.counterparty if hasattr(txn, 'counterparty') else (txn.get('counterparty', '') if isinstance(txn, dict) else '')

                row = DocumentValidationRow(
                    document_id=document_id,
                    row_index=row_offset + i,
                    description=(desc or '').upper()[:500],
                    transaction_date=str(date) if date else None,
                    amount=int(float(amt) * 100) if amt else 0,
                    category=cat or 'nao_categorizado',
                    transaction_type=txn_type or 'despesa',
                    is_validated=False,
                    original_data_json=json.dumps(
                        txn.model_dump() if hasattr(txn, 'model_dump') else txn,
                        default=str
                    ) if txn else None,
                )
                db.add(row)
            row_offset += len(transactions)
            db.flush()

            # Update progress tracker on document
            progress.setdefault("chunks_completed", []).append(chunk_index)
            doc.extracted_data_json = json.dumps(progress, default=str)
            db.commit()
            logger.debug(f"  Saved {len(transactions)} rows for chunk {chunk_index} (total rows: {row_offset})")

        # --- Lambda timeout awareness ---
        def should_stop():
            """Return True if Lambda has < 60 seconds remaining."""
            if lambda_context and hasattr(lambda_context, 'get_remaining_time_in_millis'):
                remaining = lambda_context.get_remaining_time_in_millis()
                return remaining < 60000  # 60 seconds buffer
            return False

        # Wire up the callbacks on the processor
        processor._on_chunk_complete = on_chunk_complete
        processor._skip_chunks = skip_chunks
        processor._should_stop = should_stop

        # Process document with AI
        try:
            result = processor.process_document(
                file_path,
                user_company_info=user_company_info,
                known_items=known_items_context if known_items_context else None,
            )

            if result["status"] == "partial":
                # Chunked processing stopped early (Lambda timeout) — rows already saved
                # Keep status as PROCESSING so the SQS retry picks it up
                logger.info(
                    f"Document {document_id} partially processed — "
                    f"{row_offset} rows saved so far. Will resume on retry."
                )
                # Don't change status — stays PROCESSING, SQS will retry
                db.commit()
                return

            if result["status"] == "success":
                extracted_data = result["extracted_data"]

                # Fix temp filename in document_number (FinancialDocument only, TransactionLedger doesn't have it)
                if hasattr(extracted_data, "document_number"):
                    doc_num = extracted_data.document_number
                    if doc_num and ("tmp" in doc_num.lower() and doc_num.lower().endswith((".xlsx", ".xls", ".csv"))):
                        extracted_data.document_number = doc.file_name

                data_dict = extracted_data.model_dump()

                validator = FinancialValidator()
                is_valid, errors, warnings = validator.validate_document(data_dict)

                doc.extracted_data_json = extracted_data.model_dump_json()
                doc.status = DocumentStatus.PENDING_VALIDATION
                doc.processed_date = datetime.utcnow()

                # Extract department/category
                if "category" in data_dict:
                    doc.category = resolve_category_name(data_dict.get("category"))
                if "department" in data_dict:
                    doc.department = data_dict.get("department")

                # Auto-create/match client
                transaction_type = data_dict.get("transaction_type")
                if transaction_type and not is_income_type(transaction_type):
                    issuer = data_dict.get("issuer")
                    if issuer:
                        client_id = find_or_create_client(db, doc.user_id, issuer, "supplier")
                        if client_id:
                            doc.client_id = client_id
                elif transaction_type and is_income_type(transaction_type):
                    recipient = data_dict.get("recipient")
                    if recipient:
                        client_id = find_or_create_client(db, doc.user_id, recipient, "customer")
                        if client_id:
                            doc.client_id = client_id

                # Force descriptions to UPPERCASE
                if data_dict.get("line_items"):
                    for item in data_dict["line_items"]:
                        if item.get("description"):
                            item["description"] = item["description"].upper()
                    doc.extracted_data_json = json.dumps(data_dict, default=str)

                if data_dict.get("transactions"):
                    for txn in data_dict["transactions"]:
                        if txn.get("description"):
                            txn["description"] = txn["description"].upper()
                    doc.extracted_data_json = json.dumps(data_dict, default=str)

                # Post-processing CNPJ check
                if user and user.cnpj and not doc.cnpj_mismatch:
                    import re as _re
                    user_cnpj_clean = _re.sub(r'\D', '', user.cnpj or '')
                    doc_cnpjs = set()
                    for party_key in ('issuer', 'recipient'):
                        party = data_dict.get(party_key)
                        if isinstance(party, dict) and party.get('tax_id'):
                            clean = _re.sub(r'\D', '', party['tax_id'])
                            if len(clean) == 14:
                                doc_cnpjs.add(clean)

                    known_cnpjs = {user_cnpj_clean} if user_cnpj_clean else set()
                    try:
                        org_ids = [m.organization_id for m in db.query(OrgMembership).filter(OrgMembership.user_id == user.id).all()]
                        if org_ids:
                            orgs = db.query(Organization).filter(Organization.id.in_(org_ids)).all()
                            for org in orgs:
                                if org.cnpj:
                                    known_cnpjs.add(_re.sub(r'\D', '', org.cnpj))
                    except Exception:
                        pass

                    unknown_cnpjs = doc_cnpjs - known_cnpjs - {''}
                    if unknown_cnpjs:
                        mismatched = list(unknown_cnpjs)[0]
                        formatted = f"{mismatched[:2]}.{mismatched[2:5]}.{mismatched[5:8]}/{mismatched[8:12]}-{mismatched[12:]}"
                        doc.cnpj_mismatch = True
                        doc.cnpj_warning_message = f"CNPJ {formatted} nao esta cadastrado na sua conta."

                # Check for duplicate NFe
                doc_number = data_dict.get("document_number")
                doc_type = data_dict.get("document_type", "")
                if doc_number and doc_type in ("invoice", "nfe", "nota_fiscal"):
                    normalized = _normalize_nf_number(doc_number)
                    if normalized:
                        existing_docs = db.query(Document).filter(
                            Document.user_id == doc.user_id,
                            Document.id != doc.id,
                            Document.status.in_([DocumentStatus.COMPLETED, DocumentStatus.PENDING_VALIDATION]),
                            Document.is_cancellation == False,
                        ).all()
                        for existing in existing_docs:
                            if not existing.extracted_data_json:
                                continue
                            try:
                                existing_data = json.loads(existing.extracted_data_json)
                                if _normalize_nf_number(existing_data.get("document_number", "")) == normalized:
                                    doc.status = DocumentStatus.FAILED
                                    doc.error_message = f"NFe duplicada: numero {doc_number} ja existe (ID: {existing.id})"
                                    db.commit()
                                    return
                            except (json.JSONDecodeError, TypeError):
                                continue

                # Handle NFe cancellation
                if data_dict.get("is_cancellation") and data_dict.get("original_document_number"):
                    _handle_nfe_cancellation(db, doc, data_dict)

                # Create validation rows (skip if already saved incrementally by chunk callback)
                existing_rows = (
                    db.query(func.count(DocumentValidationRow.id))
                    .filter(DocumentValidationRow.document_id == document_id)
                    .scalar() or 0
                )
                if existing_rows == 0:
                    _create_validation_rows(db, doc, data_dict)
                else:
                    logger.debug(f"Skipping _create_validation_rows — {existing_rows} rows already saved incrementally")

                # Batch-categorize uncategorized rows
                try:
                    _batch_categorize_uncategorized_rows(db, doc, processor)
                except Exception as e:
                    logger.warning(f"Post-processing categorization failed: {e}")

                # Audit trail
                audit_entry = AuditLog(
                    user_id=doc.user_id,
                    document_id=doc.id,
                    action="create",
                    entity_type="document",
                    entity_id=doc.id,
                    after_value=doc.extracted_data_json,
                    changes_summary=f"Document processed via Lambda: {doc.file_name}",
                )
                db.add(audit_entry)

            else:
                error_msg = result.get("error", "Unknown error")
                doc.status = DocumentStatus.FAILED
                doc.error_message = error_msg
                if doc.retry_count >= settings.document_max_retries:
                    doc.max_retries_exhausted = True

            db.commit()
            logger.info(f"Document {document_id} processed: status={doc.status.value}")

        except Exception as e:
            logger.error(f"Exception processing document {document_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())

            error_msg = get_friendly_error_message(e)
            doc.status = DocumentStatus.FAILED
            doc.error_message = error_msg
            if doc.retry_count >= settings.document_max_retries:
                doc.max_retries_exhausted = True
            db.commit()

    except Exception as e:
        logger.error(f"Critical error for document {document_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        db.close()
