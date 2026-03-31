"""
Error message translations for Brazilian Portuguese users
All user-facing errors should be in Portuguese
Technical logs remain in English for developers
"""

from typing import Dict


# Error message translations
ERROR_MESSAGES_PT: Dict[str, str] = {
    # AI Processing Errors
    "ai_processing_failed": "A IA teve problemas ao processar este documento. Tente novamente em alguns minutos.",
    "ai_timeout": "A IA demorou muito para responder. Tente novamente.",
    "ai_rate_limit": "Limite de processamento atingido. Aguarde alguns minutos e tente novamente.",
    "ai_invalid_response": "A IA retornou dados inválidos. Tente processar o documento novamente.",
    "openai_error": "Erro ao processar com OpenAI. Tente novamente em alguns minutos.",
    "anthropic_error": "Erro ao processar com Anthropic Claude. Tente novamente em alguns minutos.",

    # File Processing Errors
    "file_too_large": "Arquivo muito grande (máximo 30MB)",
    "invalid_file_type": "Tipo de arquivo não suportado. Formatos aceitos: PDF, Excel, XML, imagens",
    "file_corrupted": "Arquivo corrompido ou ilegível. Verifique se o arquivo está íntegro.",
    "pdf_processing_failed": "Erro ao processar PDF. Verifique se o arquivo não está protegido ou corrompido.",
    "excel_processing_failed": "Erro ao processar Excel. Verifique se o arquivo está no formato correto.",
    "xml_processing_failed": "Erro ao processar XML. Verifique se o arquivo está bem formatado.",
    "image_processing_failed": "Erro ao processar imagem. Verifique se a imagem está legível.",
    "poppler_not_installed": "Erro de configuração do sistema. Contate o suporte técnico.",

    # Upload Errors
    "upload_failed": "Erro ao fazer upload do arquivo. Tente novamente.",
    "duplicate_file": "Este arquivo já foi enviado anteriormente.",
    "storage_error": "Erro ao salvar arquivo. Tente novamente.",
    "file_not_found": "Arquivo não encontrado.",

    # Validation Errors
    "validation_error": "Erro ao validar dados do documento",
    "invalid_decimal": "Valor numérico inválido no documento",
    "invalid_date": "Formato de data inválido",
    "invalid_cnpj": "CNPJ inválido",
    "invalid_cpf": "CPF inválido",
    "required_field_missing": "Campo obrigatório ausente no documento",
    "total_amount_missing": "Valor total não encontrado no documento",
    "decimal_conversion_error": "Erro ao converter valor numérico. Verifique o formato dos números no documento.",

    # Authentication/Authorization Errors
    "unauthorized": "Acesso não autorizado",
    "invalid_credentials": "Credenciais inválidas",
    "session_expired": "Sessão expirada. Faça login novamente.",
    "insufficient_permissions": "Você não tem permissão para esta ação",

    # Subscription/Payment Errors
    "subscription_required": "Assinatura ativa necessária",
    "trial_expired": "Período de teste expirado. Assine para continuar usando.",
    "payment_failed": "Erro ao processar pagamento",

    # Generic Errors
    "unknown_error": "Erro inesperado ao processar documento. Tente novamente.",
    "server_error": "Erro no servidor. Tente novamente em alguns instantes.",
    "database_error": "Erro ao salvar dados. Tente novamente.",
    "network_error": "Erro de conexão. Verifique sua internet e tente novamente.",
}


def translate_error(error_key: str, default: str = None) -> str:
    """
    Translate error key to Portuguese message

    Args:
        error_key: Error identifier
        default: Default message if translation not found

    Returns:
        Portuguese error message
    """
    return ERROR_MESSAGES_PT.get(
        error_key,
        default or ERROR_MESSAGES_PT["unknown_error"]
    )


def translate_validation_error(error: Exception) -> str:
    """
    Translate Pydantic ValidationError to user-friendly Portuguese

    Args:
        error: ValidationError exception

    Returns:
        Portuguese error message
    """
    error_str = str(error).lower()

    # Map common Pydantic errors to Portuguese
    if "decimal" in error_str or "float" in error_str:
        if "total_amount" in error_str:
            return "Valor total inválido ou ausente no documento"
        return translate_error("invalid_decimal")

    if "date" in error_str:
        return translate_error("invalid_date")

    if "required" in error_str or "none is not an allowed value" in error_str:
        return translate_error("required_field_missing")

    # Generic validation error
    return translate_error("validation_error")


def translate_ai_error(error: Exception) -> str:
    """
    Translate AI API errors to user-friendly Portuguese
    Logs technical details in English for developers

    Args:
        error: Exception from AI API

    Returns:
        Portuguese error message
    """
    import logging
    logger = logging.getLogger(__name__)

    # Log technical details in English for developers
    logger.error(f"AI API Error: {type(error).__name__}: {str(error)}")

    error_str = str(error).lower()
    error_type = type(error).__name__

    # OpenAI specific errors
    if "openai" in error_type.lower():
        if "rate" in error_str or "limit" in error_str:
            return translate_error("ai_rate_limit")
        if "timeout" in error_str:
            return translate_error("ai_timeout")
        if "invalid" in error_str or "bad request" in error_str:
            return translate_error("ai_invalid_response")
        return translate_error("openai_error")

    # Anthropic specific errors
    if "anthropic" in error_type.lower():
        return translate_error("anthropic_error")

    # Generic AI error
    return translate_error("ai_processing_failed")


def get_friendly_error_message(error: Exception) -> str:
    """
    Convert any exception to user-friendly Portuguese message

    Args:
        error: Any exception

    Returns:
        Portuguese error message
    """
    error_type = type(error).__name__

    # Validation errors
    if "ValidationError" in error_type:
        return translate_validation_error(error)

    # AI errors
    if any(keyword in error_type.lower() for keyword in ["openai", "anthropic", "ai"]):
        return translate_ai_error(error)

    # HTTP errors
    if "HTTPException" in error_type:
        return str(error.detail) if hasattr(error, "detail") else translate_error("server_error")

    # File errors
    if "FileNotFoundError" in error_type:
        return translate_error("file_not_found")

    # Generic error
    return translate_error("unknown_error")
