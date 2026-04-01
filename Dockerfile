# ─────────────────────────────────────────────────────────────────────────────
# controlladoria-jobs — AWS Lambda container image
#
# Each Lambda function uses the same image; the CMD is overridden per function
# in the Lambda configuration:
#
#   document-processing → handlers.process_document.handler
#   cleanup-files       → handlers.cleanup_files.handler
#   cleanup-tokens      → handlers.cleanup_tokens.handler
#   retry-documents     → handlers.retry_documents.handler
# ─────────────────────────────────────────────────────────────────────────────
FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

# Install OS-level dependencies:
#   gcc + libpq-devel → psycopg2 (PostgreSQL driver)
#   poppler-utils     → pdf2image / convert_from_path (PDF → PNG for AI extraction)
RUN dnf install -y \
    gcc \
    libpq-devel \
    poppler-utils \
    && dnf clean all

# Copy dependency manifest first (Docker layer cache friendly)
COPY requirements.txt .

# Install Python dependencies into Lambda's site-packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all application source (handlers, shared modules, accounting, auth, etc.)
COPY . .

# Default handler — overridden per Lambda function config
CMD ["handlers.process_document.handler"]
