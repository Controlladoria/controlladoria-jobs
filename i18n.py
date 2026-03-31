"""
Internacionalização (i18n) - Mensagens em Português BR
Portuguese Brazilian translations for API responses
"""

MESSAGES_PT_BR = {
    # API Info
    "api_running": "DreSystem API - Sistema de Processamento de Documentos Financeiros",
    "api_version": "0.2.0",
    # Upload
    "upload_success": "Documento enviado e processado com sucesso",
    "upload_success_pending": "Documento enviado, processamento em andamento",
    "upload_failed": "Falha no processamento do documento",
    "file_saved": "Arquivo salvo com sucesso",
    # Errors
    "file_not_found": "Arquivo não encontrado",
    "document_not_found": "Documento não encontrado",
    "unsupported_file_type": "Tipo de arquivo não suportado. Formatos permitidos: PDF, JPG, JPEG, PNG, WEBP, GIF",
    "upload_error": "Erro ao fazer upload do arquivo",
    "processing_error": "Erro ao processar documento",
    "database_error": "Erro no banco de dados",
    "invalid_status": "Status inválido",
    # Status
    "status_pending": "pendente",
    "status_processing": "processando",
    "status_completed": "concluído",
    "status_failed": "falhou",
    # Document operations
    "document_deleted": "Documento excluído com sucesso",
    "document_updated": "Documento atualizado com sucesso",
    # Stats
    "total_documents": "Total de documentos",
    "completed": "Concluídos",
    "failed": "Falhou",
    "pending": "Pendentes",
    "processing": "Processando",
}

MESSAGES_EN = {
    # API Info
    "api_running": "DreSystem API - Financial Document Processing System",
    "api_version": "0.2.0",
    # Upload
    "upload_success": "Document uploaded and processed successfully",
    "upload_success_pending": "Document uploaded, processing in progress",
    "upload_failed": "Document processing failed",
    "file_saved": "File saved successfully",
    # Errors
    "file_not_found": "File not found",
    "document_not_found": "Document not found",
    "unsupported_file_type": "Unsupported file type. Allowed formats: PDF, JPG, JPEG, PNG, WEBP, GIF",
    "upload_error": "Error uploading file",
    "processing_error": "Error processing document",
    "database_error": "Database error",
    "invalid_status": "Invalid status",
    # Status
    "status_pending": "pending",
    "status_processing": "processing",
    "status_completed": "completed",
    "status_failed": "failed",
    # Document operations
    "document_deleted": "Document deleted successfully",
    "document_updated": "Document updated successfully",
    # Stats
    "total_documents": "Total documents",
    "completed": "Completed",
    "failed": "Failed",
    "pending": "Pending",
    "processing": "Processing",
}


class Messages:
    """Message manager with language support"""

    def __init__(self, lang: str = "pt-BR"):
        self.lang = lang
        self.messages = MESSAGES_PT_BR if lang == "pt-BR" else MESSAGES_EN

    def get(self, key: str, default: str = None) -> str:
        """Get translated message by key"""
        return self.messages.get(key, default or key)

    def __getitem__(self, key: str) -> str:
        """Allow dict-style access"""
        return self.get(key)


# Default instance for Brazilian Portuguese
msg = Messages("pt-BR")
