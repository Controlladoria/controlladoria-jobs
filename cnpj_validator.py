"""
CNPJ Validation for Document Uploads
Validates that uploaded Nota Fiscal documents contain the user's CNPJ
"""

import re
import io
import logging
from typing import Optional, Tuple
from openai import OpenAI
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


def _pdf_to_png_base64(file_path: str) -> str:
    """Convert first page of a PDF to a base64-encoded PNG image.

    OpenAI's vision API does not accept PDFs, so we render page 1 as an image.
    Requires poppler-utils (listed in Aptfile).
    """
    from pdf2image import convert_from_path

    pages = convert_from_path(file_path, first_page=1, last_page=1, dpi=200)
    buf = io.BytesIO()
    pages[0].save(buf, format="PNG")
    buf.seek(0)

    import base64
    return base64.b64encode(buf.read()).decode("utf-8")


def clean_cnpj(cnpj: str) -> str:
    """Remove formatting from CNPJ, keeping only numbers"""
    if not cnpj:
        return ""
    return re.sub(r'[^\d]', '', cnpj)


def extract_cnpj_from_document(file_path: str, ai_provider: str, api_key: str, model: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Quickly extract recipient and sender CNPJ from a document

    Returns:
        Tuple of (recipient_cnpj, sender_cnpj) - both can be None if not found
    """
    try:
        import base64

        prompt = """Extract ONLY the CNPJ numbers from this document.

This could be ANY type of Brazilian document:
- Nota Fiscal / NFe (has recipient and sender CNPJs)
- Cartão CNPJ / Comprovante de Inscrição (has ONE CNPJ - the company's)
- Recibo, Boleto, or any other commercial document

Look for:
- NUMERO DE INSCRICAO or CNPJ field on a Cartao CNPJ -> put in "recipient_cnpj"
- Destinatario/Cliente/Tomador CNPJ (recipient)
- Emitente/Prestador/Remetente CNPJ (sender/issuer)

Return ONLY a JSON object with these exact fields (no markdown, no explanation):
{
  "recipient_cnpj": "CNPJ number of recipient/company (numeros apenas)",
  "sender_cnpj": "CNPJ number of sender/issuer (numeros apenas)"
}

If this is a Cartao CNPJ with only one CNPJ, put it in "recipient_cnpj".
If CNPJ is not found for either field, use null.
Extract numeros apenas (only numbers), remove all formatting."""

        # Prepare image data for vision APIs
        if file_path.lower().endswith('.pdf'):
            file_data = _pdf_to_png_base64(file_path)
            media_type = "image/png"
        elif file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            with open(file_path, 'rb') as f:
                file_data = base64.b64encode(f.read()).decode('utf-8')
            if file_path.lower().endswith('.png'):
                media_type = "image/png"
            elif file_path.lower().endswith('.webp'):
                media_type = "image/webp"
            else:
                media_type = "image/jpeg"
        else:
            logger.warning(f"Unsupported file type for CNPJ extraction: {file_path}")
            return (None, None)

        if ai_provider == "gemini":
            from PIL import Image
            gemini_client = genai.Client(api_key=api_key)

            image_bytes = base64.b64decode(file_data)
            image = Image.open(io.BytesIO(image_bytes))
            response = gemini_client.models.generate_content(
                model=model,
                contents=[prompt, image],
                config=genai_types.GenerateContentConfig(max_output_tokens=300, temperature=0.1),
            )
            result_text = response.text

        elif ai_provider == "nova":
            import boto3 as _boto3
            import os as _os
            format_map = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp"}
            img_format = format_map.get(media_type, "png")

            bedrock = _boto3.client(
                "bedrock-runtime",
                region_name=_os.getenv("NOVA_REGION", _os.getenv("AWS_REGION", "us-east-2")),
            )
            response = bedrock.converse(
                modelId=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"image": {"format": img_format, "source": {"bytes": base64.b64decode(file_data)}}},
                        {"text": prompt},
                    ],
                }],
                inferenceConfig={"maxTokens": 300, "temperature": 0.1},
            )
            result_text = response["output"]["message"]["content"][0]["text"]

        elif ai_provider == "openai":
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{file_data}"}},
                    ],
                }],
                max_completion_tokens=300,
                store=False,
            )
            result_text = response.choices[0].message.content

        else:
            logger.error(f"Unknown AI provider for CNPJ extraction: {ai_provider}")
            return (None, None)

        # Parse JSON response
        import json
        # Remove markdown code blocks if present
        result_text = re.sub(r'```json\s*|\s*```', '', result_text)
        result_data = json.loads(result_text)

        recipient_cnpj = clean_cnpj(result_data.get('recipient_cnpj') or '')
        sender_cnpj = clean_cnpj(result_data.get('sender_cnpj') or '')

        logger.info(f"📋 Extracted CNPJs - Recipient: {recipient_cnpj or 'Not found'}, Sender: {sender_cnpj or 'Not found'}")

        return (
            recipient_cnpj if recipient_cnpj else None,
            sender_cnpj if sender_cnpj else None
        )

    except Exception as e:
        logger.error(f"❌ Error extracting CNPJ: {e}")
        return (None, None)


def validate_document_cnpj(
    file_path: str,
    user_cnpj: str,
    ai_provider: str,
    api_key: str,
    model: str,
    skip_validation: bool = False
) -> Tuple[bool, str]:
    """
    Validate that the document contains the user's CNPJ

    Args:
        file_path: Path to the uploaded document
        user_cnpj: User's CNPJ (from database)
        ai_provider: "openai" or "anthropic"
        api_key: API key for the AI provider
        model: Model to use for extraction
        skip_validation: If True, always returns success (for non-Nota Fiscal docs)

    Returns:
        Tuple of (is_valid: bool, error_message: str)
        If is_valid is False, error_message contains the reason
    """
    if skip_validation:
        return (True, "")

    # Clean user CNPJ
    user_cnpj_clean = clean_cnpj(user_cnpj)

    if not user_cnpj_clean:
        return (False, "CNPJ do usuário não encontrado. Entre em contato com o suporte.")

    # Extract CNPJs from document
    recipient_cnpj, sender_cnpj = extract_cnpj_from_document(
        file_path, ai_provider, api_key, model
    )

    # Check if user CNPJ matches either recipient or sender
    if recipient_cnpj and user_cnpj_clean == recipient_cnpj:
        logger.info(f"✅ CNPJ validation passed - User is recipient")
        return (True, "")

    if sender_cnpj and user_cnpj_clean == sender_cnpj:
        logger.info(f"✅ CNPJ validation passed - User is sender")
        return (True, "")

    # Validation failed
    logger.warning(
        f"❌ CNPJ validation failed - User: {user_cnpj_clean}, "
        f"Document recipient: {recipient_cnpj or 'N/A'}, "
        f"Document sender: {sender_cnpj or 'N/A'}"
    )

    error_msg = f"""⛔ Documento rejeitado: O CNPJ do documento não corresponde ao seu CNPJ.

Seu CNPJ: {user_cnpj}
CNPJ encontrado no documento: {format_cnpj(recipient_cnpj or sender_cnpj or '')}

Para segurança, apenas documentos onde você é o remetente ou destinatário podem ser enviados.
Se você acredita que este é um erro, entre em contato com o suporte."""

    return (False, error_msg)


def format_cnpj(cnpj: str) -> str:
    """Format CNPJ with standard Brazilian formatting: XX.XXX.XXX/XXXX-XX"""
    if not cnpj:
        return "Não encontrado"

    clean = clean_cnpj(cnpj)
    if len(clean) != 14:
        return cnpj

    return f"{clean[:2]}.{clean[2:5]}.{clean[5:8]}/{clean[8:12]}-{clean[12:14]}"
