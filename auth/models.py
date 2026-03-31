"""
Pydantic models for authentication requests and responses
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, validator


class UserRegister(BaseModel):
    """User registration request"""

    email: EmailStr
    password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description="A senha deve ter no mínimo 8 caracteres e conter: 1 letra maiúscula, 1 letra minúscula e 1 número. Exemplo: MinhaSenh@123"
    )
    full_name: str = Field(..., max_length=255, description="Nome completo do responsável")
    company_name: str = Field(..., max_length=255, description="Nome da empresa/razão social")
    cnpj: str = Field(..., min_length=14, max_length=50, description="CNPJ da empresa (apenas números ou formatado XX.XXX.XXX/XXXX-XX)")
    agreed_to_terms: bool = Field(..., description="Deve concordar com os Termos de Serviço")
    agreed_to_privacy: bool = Field(..., description="Deve concordar com a Política de Privacidade (LGPD)")

    # Optional company data (auto-filled from CNPJ lookup)
    trade_name: Optional[str] = Field(None, max_length=255, description="Nome fantasia")
    cnae_code: Optional[str] = Field(None, max_length=20, description="CNAE principal")
    cnae_description: Optional[str] = Field(None, max_length=500, description="Descrição CNAE")
    company_address_street: Optional[str] = Field(None, max_length=500, description="Logradouro")
    company_address_number: Optional[str] = Field(None, max_length=20, description="Número")
    company_address_complement: Optional[str] = Field(None, max_length=255, description="Complemento")
    company_address_district: Optional[str] = Field(None, max_length=255, description="Bairro")
    company_address_city: Optional[str] = Field(None, max_length=255, description="Município")
    company_address_state: Optional[str] = Field(None, max_length=2, description="UF")
    company_address_zip: Optional[str] = Field(None, max_length=10, description="CEP")
    capital_social: Optional[float] = Field(None, description="Capital social")
    company_size: Optional[str] = Field(None, max_length=100, description="Porte da empresa")
    legal_nature: Optional[str] = Field(None, max_length=255, description="Natureza jurídica")
    company_phone: Optional[str] = Field(None, max_length=50, description="Telefone")
    company_email: Optional[str] = Field(None, max_length=255, description="Email comercial")
    company_status: Optional[str] = Field(None, max_length=50, description="Situação cadastral")
    company_opened_at: Optional[str] = Field(None, max_length=20, description="Data de abertura")
    is_simples_nacional: Optional[bool] = Field(None, description="Optante pelo Simples Nacional")
    is_mei: Optional[bool] = Field(None, description="MEI")

    # Additional company data (from BrasilAPI full response)
    qsa_partners: Optional[List[Dict[str, Any]]] = Field(None, description="QSA partners array")
    cnaes_secundarios: Optional[List[Dict[str, Any]]] = Field(None, description="CNAEs secundários")
    company_address_type: Optional[str] = Field(None, max_length=50, description="Tipo de logradouro")
    is_headquarters: Optional[bool] = Field(None, description="Matriz (true) ou Filial (false)")
    ibge_code: Optional[str] = Field(None, max_length=10, description="Código IBGE do município")
    regime_tributario: Optional[str] = Field(None, max_length=100, description="Regime tributário")
    simples_desde: Optional[str] = Field(None, max_length=20, description="Data de opção pelo Simples")
    simples_excluido_em: Optional[str] = Field(None, max_length=20, description="Data de exclusão do Simples")
    main_partner_name: Optional[str] = Field(None, max_length=500, description="Sócio-administrador principal")
    main_partner_qualification: Optional[str] = Field(None, max_length=255, description="Qualificação do sócio principal")

    @validator("agreed_to_terms")
    def validate_terms(cls, v):
        """Valida que o usuário concordou com os termos"""
        if not v:
            raise ValueError("Você deve concordar com os Termos de Serviço para criar uma conta")
        return v

    @validator("agreed_to_privacy")
    def validate_privacy(cls, v):
        """Valida que o usuário concordou com a política de privacidade (LGPD)"""
        if not v:
            raise ValueError("Você deve concordar com a Política de Privacidade para criar uma conta")
        return v

    @validator("password")
    def validate_password(cls, v):
        """Valida a força da senha"""
        if len(v) < 8:
            raise ValueError("A senha deve ter no mínimo 8 caracteres")
        if not any(c.isupper() for c in v):
            raise ValueError("A senha deve conter pelo menos uma letra maiúscula")
        if not any(c.islower() for c in v):
            raise ValueError("A senha deve conter pelo menos uma letra minúscula")
        if not any(c.isdigit() for c in v):
            raise ValueError("A senha deve conter pelo menos um número")
        return v

    @validator("cnpj")
    def validate_cnpj(cls, v):
        """Valida o formato e checksum do CNPJ"""
        if not v:
            raise ValueError("CNPJ é obrigatório")

        # Remove formatting
        cnpj_digits = re.sub(r'\D', '', v)

        if len(cnpj_digits) != 14:
            raise ValueError("CNPJ deve ter 14 dígitos")

        # Check if all digits are the same (invalid CNPJ)
        if len(set(cnpj_digits)) == 1:
            raise ValueError("CNPJ inválido")

        # Validate checksum digits
        def calc_digit(cnpj_partial, weights):
            total = sum(int(digit) * weight for digit, weight in zip(cnpj_partial, weights))
            remainder = total % 11
            return 0 if remainder < 2 else 11 - remainder

        # First digit
        weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        digit_1 = calc_digit(cnpj_digits[:12], weights_1)

        # Second digit
        weights_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        digit_2 = calc_digit(cnpj_digits[:13], weights_2)

        if int(cnpj_digits[12]) != digit_1 or int(cnpj_digits[13]) != digit_2:
            raise ValueError("CNPJ inválido - dígitos verificadores não conferem")

        # Return formatted CNPJ
        return f"{cnpj_digits[:2]}.{cnpj_digits[2:5]}.{cnpj_digits[5:8]}/{cnpj_digits[8:12]}-{cnpj_digits[12:14]}"


class UserLogin(BaseModel):
    """User login request"""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Authentication token response"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 minutes in seconds


class MFARequiredResponse(BaseModel):
    """MFA verification required response"""

    mfa_required: bool = True
    mfa_method: str  # "totp" or "email"
    temp_token: str  # Temporary token for MFA verification
    message: str = "MFA verification required"


class RefreshTokenRequest(BaseModel):
    """Refresh token request"""

    refresh_token: str


class PasswordResetRequest(BaseModel):
    """Password reset request"""

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation"""

    token: str
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=100,
        description="A senha deve ter no mínimo 8 caracteres e conter: 1 letra maiúscula, 1 letra minúscula e 1 número. Exemplo: MinhaSenh@123"
    )

    @validator("new_password")
    def validate_password(cls, v):
        """Valida a força da senha"""
        if len(v) < 8:
            raise ValueError("A senha deve ter no mínimo 8 caracteres")
        if not any(c.isupper() for c in v):
            raise ValueError("A senha deve conter pelo menos uma letra maiúscula")
        if not any(c.islower() for c in v):
            raise ValueError("A senha deve conter pelo menos uma letra minúscula")
        if not any(c.isdigit() for c in v):
            raise ValueError("A senha deve conter pelo menos um número")
        return v


class UserResponse(BaseModel):
    """User response model"""

    id: int
    email: str
    full_name: str
    company_name: str
    cnpj: str
    is_active: bool
    is_verified: bool
    is_admin: bool
    role: str
    parent_user_id: Optional[int] = None
    created_at: datetime
    trial_end_date: Optional[datetime] = None
    theme_preference: str = "system"
    font_size_mobile: str = "medium"
    font_size_desktop: str = "medium"
    report_tab_order: str = "dre,balanco,fluxo"

    # Company data from CNPJ lookup
    trade_name: Optional[str] = None
    cnae_code: Optional[str] = None
    cnae_description: Optional[str] = None
    company_address_street: Optional[str] = None
    company_address_number: Optional[str] = None
    company_address_complement: Optional[str] = None
    company_address_district: Optional[str] = None
    company_address_city: Optional[str] = None
    company_address_state: Optional[str] = None
    company_address_zip: Optional[str] = None
    capital_social: Optional[float] = None
    company_size: Optional[str] = None
    legal_nature: Optional[str] = None
    company_phone: Optional[str] = None
    company_email: Optional[str] = None
    company_status: Optional[str] = None
    company_opened_at: Optional[str] = None
    is_simples_nacional: Optional[bool] = None
    is_mei: Optional[bool] = None

    # Additional company data
    qsa_partners: Optional[List[Dict[str, Any]]] = None
    cnaes_secundarios: Optional[List[Dict[str, Any]]] = None
    company_address_type: Optional[str] = None
    is_headquarters: Optional[bool] = None
    ibge_code: Optional[str] = None
    regime_tributario: Optional[str] = None
    simples_desde: Optional[str] = None
    simples_excluido_em: Optional[str] = None
    main_partner_name: Optional[str] = None
    main_partner_qualification: Optional[str] = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """User profile update request"""

    full_name: Optional[str] = Field(None, max_length=255)
    company_name: Optional[str] = Field(None, max_length=255)
    cnpj: Optional[str] = Field(None, max_length=50)

    # Company data fields (updatable)
    trade_name: Optional[str] = Field(None, max_length=255)
    cnae_code: Optional[str] = Field(None, max_length=20)
    cnae_description: Optional[str] = Field(None, max_length=500)
    company_address_street: Optional[str] = Field(None, max_length=500)
    company_address_number: Optional[str] = Field(None, max_length=20)
    company_address_complement: Optional[str] = Field(None, max_length=255)
    company_address_district: Optional[str] = Field(None, max_length=255)
    company_address_city: Optional[str] = Field(None, max_length=255)
    company_address_state: Optional[str] = Field(None, max_length=2)
    company_address_zip: Optional[str] = Field(None, max_length=10)
    capital_social: Optional[float] = None
    company_size: Optional[str] = Field(None, max_length=100)
    legal_nature: Optional[str] = Field(None, max_length=255)
    company_phone: Optional[str] = Field(None, max_length=50)
    company_email: Optional[str] = Field(None, max_length=255)
    company_status: Optional[str] = Field(None, max_length=50)
    company_opened_at: Optional[str] = Field(None, max_length=20)
    is_simples_nacional: Optional[bool] = None
    is_mei: Optional[bool] = None

    # Additional company data
    qsa_partners: Optional[List[Dict[str, Any]]] = None
    cnaes_secundarios: Optional[List[Dict[str, Any]]] = None
    company_address_type: Optional[str] = Field(None, max_length=50)
    is_headquarters: Optional[bool] = None
    ibge_code: Optional[str] = Field(None, max_length=10)
    regime_tributario: Optional[str] = Field(None, max_length=100)
    simples_desde: Optional[str] = Field(None, max_length=20)
    simples_excluido_em: Optional[str] = Field(None, max_length=20)
    main_partner_name: Optional[str] = Field(None, max_length=500)
    main_partner_qualification: Optional[str] = Field(None, max_length=255)


# ============= MFA Models =============

class MFASetupResponse(BaseModel):
    """MFA setup response with TOTP secret and QR code URI"""

    secret: str
    provisioning_uri: str
    qr_code_data_url: Optional[str] = None  # Base64 encoded QR code image


class MFAVerifyRequest(BaseModel):
    """MFA verification request"""

    code: str = Field(..., min_length=6, max_length=6, description="6-digit MFA code")


class MFAEnableRequest(BaseModel):
    """Enable MFA request"""

    secret: str = Field(..., description="TOTP secret from setup")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")


class MFAEnableResponse(BaseModel):
    """MFA enable response with backup codes"""

    backup_codes: list[str] = Field(..., description="10 backup codes for account recovery")
    message: str = "Verificação em duas etapas ativada"


class MFAStatusResponse(BaseModel):
    """MFA status response"""

    enabled: bool
    method: Optional[str] = None  # "totp" or "email"
    enabled_at: Optional[datetime] = None
    backup_codes_remaining: int = 0

    class Config:
        from_attributes = True


class MFALoginRequest(BaseModel):
    """MFA verification during login"""

    email: EmailStr
    password: str
    mfa_code: str = Field(..., min_length=6, max_length=6)
    mfa_type: str = Field(..., description="Type of MFA code: 'totp', 'email', or 'backup'")


# ============= Preference Models =============

class ThemeUpdateRequest(BaseModel):
    """Theme preference update request"""

    theme: Literal["light", "dark", "system"] = "system"


class FontSizeUpdateRequest(BaseModel):
    """Font size preference update request (per device)"""

    size: Literal["small", "medium", "large"] = "medium"
    device: Literal["mobile", "desktop"] = "desktop"


class ReportTabOrderRequest(BaseModel):
    """Report tab order update request"""

    order: str = Field("dre,balanco,fluxo,indicadores", max_length=100)

    @validator("order")
    def validate_tab_order(cls, v):
        valid_tabs = {"dre", "balanco", "fluxo", "indicadores"}
        tabs = [t.strip() for t in v.split(",")]
        if not set(tabs).issubset(valid_tabs) or len(tabs) != len(set(tabs)):
            raise ValueError("Deve conter tabs válidas sem duplicatas: dre, balanco, fluxo, indicadores")
        return ",".join(tabs)


# ============= Known Items Models =============

class KnownItemResponse(BaseModel):
    """Known item response model"""

    id: int
    name: str
    alias: Optional[str] = None
    category: Optional[str] = None
    transaction_type: Optional[str] = None
    times_appeared: int = 1
    first_seen_at: datetime
    last_seen_at: datetime

    class Config:
        from_attributes = True


class KnownItemUpdate(BaseModel):
    """Known item update request"""

    alias: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    transaction_type: Optional[str] = Field(None, max_length=20)
