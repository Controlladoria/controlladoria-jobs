"""
Email Service with Resend
Handles transactional emails for DreSystem
"""

import logging
from datetime import datetime
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# Resend will be imported only if API key is configured
try:
    import resend

    resend.api_key = settings.resend_api_key
    RESEND_AVAILABLE = bool(settings.resend_api_key)
except ImportError:
    RESEND_AVAILABLE = False
    logger.warning("Resend package not installed. Email sending disabled.")


class EmailService:
    """Service for sending transactional emails via Resend"""

    def __init__(self):
        self.from_email = settings.from_email
        self.frontend_url = settings.frontend_url

    async def send_email(
        self, to: str, subject: str, html: str, reply_to: Optional[str] = None
    ) -> bool:
        """
        Send an email via Resend

        Args:
            to: Recipient email address
            subject: Email subject
            html: HTML content
            reply_to: Optional reply-to address

        Returns:
            bool: True if sent successfully, False otherwise
        """
        if not RESEND_AVAILABLE:
            logger.warning(f"Email not sent (Resend not configured): {subject} to {to}")
            return False

        try:
            params = {
                "from": self.from_email,
                "to": [to],
                "subject": subject,
                "html": html,
            }

            if reply_to:
                params["reply_to"] = [reply_to]

            response = resend.Emails.send(params)
            logger.info(f"Email sent successfully to {to}: {response}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to}: {str(e)}", exc_info=True)
            return False

    async def send_password_reset_email(
        self, to: str, token: str, user_name: str
    ) -> bool:
        """
        Send password reset email

        Args:
            to: User email address
            token: Password reset token
            user_name: User's full name

        Returns:
            bool: True if sent successfully
        """
        reset_url = f"{self.frontend_url}/reset-password?token={token}"
        current_year = datetime.now().year

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Redefinir Senha - DreSystem</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: bold;">DreSystem</h1>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 20px; color: #111827; font-size: 24px; font-weight: 600;">
                                        Redefinir Senha
                                    </h2>

                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Olá, {user_name}!
                                    </p>

                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Recebemos uma solicitação para redefinir a senha da sua conta no DreSystem.
                                    </p>

                                    <p style="margin: 0 0 30px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Clique no botão abaixo para criar uma nova senha:
                                    </p>

                                    <!-- CTA Button -->
                                    <table role="presentation" style="margin: 0 auto;">
                                        <tr>
                                            <td style="border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                                                <a href="{reset_url}"
                                                   style="display: inline-block; padding: 16px 32px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 600; border-radius: 6px;">
                                                    Redefinir Senha
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Ou copie e cole este link no seu navegador:
                                    </p>
                                    <p style="margin: 10px 0 0; color: #667eea; font-size: 14px; word-break: break-all;">
                                        {reset_url}
                                    </p>

                                    <div style="margin: 30px 0 0; padding: 20px; background-color: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 4px;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.5;">
                                            <strong>⚠️ Importante:</strong> Este link expira em 1 hora por segurança.
                                        </p>
                                    </div>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Se você não solicitou esta redefinição, ignore este email. Sua senha permanecerá inalterada.
                                    </p>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px;">
                                        DreSystem - Processamento Inteligente de Documentos
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        © {current_year} DreSystem. Todos os direitos reservados.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=to, subject="Redefinir Senha - DreSystem", html=html
        )

    async def send_welcome_email(
        self, to: str, user_name: str, trial_days: int = 15
    ) -> bool:
        """
        Send welcome email to new users

        Args:
            to: User email address
            user_name: User's full name
            trial_days: Number of trial days

        Returns:
            bool: True if sent successfully
        """
        login_url = f"{self.frontend_url}/login"
        pricing_url = f"{self.frontend_url}/pricing"
        current_year = datetime.now().year

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bem-vindo ao DreSystem!</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 32px; font-weight: bold;">🎉 Bem-vindo!</h1>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 20px; color: #111827; font-size: 24px; font-weight: 600;">
                                        Olá, {user_name}!
                                    </h2>

                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Sua conta foi criada com sucesso! Estamos animados em ter você no DreSystem.
                                    </p>

                                    <!-- Trial Box -->
                                    <div style="margin: 30px 0; padding: 24px; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-radius: 8px; text-align: center;">
                                        <p style="margin: 0 0 10px; color: #78350f; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">
                                            Período de Teste Gratuito
                                        </p>
                                        <p style="margin: 0; color: #92400e; font-size: 32px; font-weight: bold;">
                                            {trial_days} dias
                                        </p>
                                        <p style="margin: 10px 0 0; color: #92400e; font-size: 14px;">
                                            Acesso total, sem cartão de crédito
                                        </p>
                                    </div>

                                    <h3 style="margin: 30px 0 15px; color: #111827; font-size: 18px; font-weight: 600;">
                                        O que você pode fazer:
                                    </h3>

                                    <ul style="margin: 0 0 30px; padding-left: 20px; color: #4b5563; font-size: 16px; line-height: 1.8;">
                                        <li>📄 Upload ilimitado de documentos (PDF, Excel, Imagens, XML)</li>
                                        <li>🤖 Extração automática de dados com IA</li>
                                        <li>📊 Relatórios financeiros (DRE, Fluxo de Caixa, Balanço)</li>
                                        <li>💾 Armazenamento seguro em nuvem</li>
                                        <li>📱 Acesso de qualquer dispositivo</li>
                                    </ul>

                                    <!-- CTA Button -->
                                    <table role="presentation" style="margin: 0 auto;">
                                        <tr>
                                            <td style="border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                                                <a href="{login_url}"
                                                   style="display: inline-block; padding: 16px 32px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 600; border-radius: 6px;">
                                                    Começar Agora
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5; text-align: center;">
                                        Precisa de ajuda? Responda este email ou acesse nossa central de suporte.
                                    </p>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px;">
                                        DreSystem - Processamento Inteligente de Documentos
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        © {current_year} DreSystem. Todos os direitos reservados.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=to,
            subject=f"Bem-vindo ao DreSystem! {trial_days} dias grátis 🎉",
            html=html,
        )

    async def send_verification_email(
        self, to: str, token: str, user_name: str
    ) -> bool:
        """
        Send email verification email

        Args:
            to: User email address
            token: Verification token
            user_name: User's full name

        Returns:
            bool: True if sent successfully
        """
        verify_url = f"{self.frontend_url}/verify-email?token={token}"
        current_year = datetime.now().year

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Verifique seu E-mail</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 32px; font-weight: bold;">✉️ Verifique seu E-mail</h1>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 20px; color: #111827; font-size: 24px; font-weight: 600;">
                                        Olá, {user_name}!
                                    </h2>

                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Obrigado por se cadastrar no DreSystem! Para garantir a segurança da sua conta,
                                        precisamos verificar seu endereço de e-mail.
                                    </p>

                                    <p style="margin: 0 0 30px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Clique no botão abaixo para confirmar seu e-mail:
                                    </p>

                                    <!-- CTA Button -->
                                    <table role="presentation" style="margin: 0 auto;">
                                        <tr>
                                            <td style="border-radius: 6px; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);">
                                                <a href="{verify_url}"
                                                   style="display: inline-block; padding: 16px 32px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 600; border-radius: 6px;">
                                                    Verificar E-mail
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <!-- Alternative Link -->
                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5; text-align: center;">
                                        Ou copie e cole este link no seu navegador:<br>
                                        <a href="{verify_url}" style="color: #3b82f6; word-break: break-all;">
                                            {verify_url}
                                        </a>
                                    </p>

                                    <!-- Expiry Notice -->
                                    <div style="margin: 30px 0 0; padding: 16px; background-color: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 4px;">
                                        <p style="margin: 0; color: #1e40af; font-size: 14px;">
                                            ⏰ Este link expira em <strong>24 horas</strong>. Caso expire, você pode solicitar um novo link diretamente no sistema.
                                        </p>
                                    </div>

                                    <!-- Warning Box -->
                                    <div style="margin: 16px 0 0; padding: 16px; background-color: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 4px;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                                            ⚠️ Se você não se cadastrou no DreSystem, ignore este e-mail.
                                        </p>
                                    </div>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px;">
                                        DreSystem - Processamento Inteligente de Documentos
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        © {current_year} DreSystem. Todos os direitos reservados.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=to,
            subject="Verifique seu e-mail - DreSystem",
            html=html,
        )

    async def send_contact_notification(
        self, admin_email: str, name: str, email: str, phone: str, message: str
    ) -> bool:
        """
        Send contact form notification to admin

        Args:
            admin_email: Admin email to receive notification
            name: Contact's name
            email: Contact's email
            phone: Contact's phone
            message: Contact's message

        Returns:
            bool: True if sent successfully
        """
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Nova Mensagem de Contato</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #111827; border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">
                                        📬 Nova Mensagem de Contato
                                    </h1>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <table style="width: 100%; border-collapse: collapse;">
                                        <tr>
                                            <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                                <strong style="color: #6b7280; font-size: 14px;">Nome:</strong>
                                            </td>
                                            <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                                <span style="color: #111827; font-size: 16px;">{name}</span>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                                <strong style="color: #6b7280; font-size: 14px;">E-mail:</strong>
                                            </td>
                                            <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                                <a href="mailto:{email}" style="color: #667eea; font-size: 16px; text-decoration: none;">
                                                    {email}
                                                </a>
                                            </td>
                                        </tr>
                                        <tr>
                                            <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                                <strong style="color: #6b7280; font-size: 14px;">Telefone:</strong>
                                            </td>
                                            <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                                                <a href="tel:{phone}" style="color: #667eea; font-size: 16px; text-decoration: none;">
                                                    {phone}
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <h3 style="margin: 30px 0 15px; color: #111827; font-size: 18px; font-weight: 600;">
                                        Mensagem:
                                    </h3>

                                    <div style="padding: 20px; background-color: #f9fafb; border-left: 4px solid #667eea; border-radius: 4px;">
                                        <p style="margin: 0; color: #374151; font-size: 16px; line-height: 1.6; white-space: pre-wrap;">
{message}
                                        </p>
                                    </div>

                                    <!-- Reply Button -->
                                    <table role="presentation" style="margin: 30px auto 0;">
                                        <tr>
                                            <td style="border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                                                <a href="mailto:{email}"
                                                   style="display: inline-block; padding: 12px 24px; color: #ffffff; text-decoration: none; font-size: 14px; font-weight: 600; border-radius: 6px;">
                                                    Responder por E-mail
                                                </a>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 20px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        Enviado via formulário de contato do DreSystem
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=admin_email,
            subject=f"Nova mensagem de contato: {name}",
            html=html,
            reply_to=email,
        )

    async def send_team_invitation_email(
        self,
        to: str,
        inviter_name: str,
        company_name: str,
        invitation_token: str,
        expires_days: int = 7,
    ) -> bool:
        """
        Send team invitation email

        Args:
            to: Email address of the person being invited
            inviter_name: Name of the person who sent the invitation
            company_name: Name of the company/team
            invitation_token: Unique invitation token
            expires_days: Number of days until invitation expires

        Returns:
            bool: True if sent successfully
        """
        invitation_url = f"{self.frontend_url}/team/accept-invitation/{invitation_token}"
        current_year = datetime.now().year

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Convite para Equipe - ControlladorIA</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 32px; font-weight: bold;">Você foi convidado!</h1>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 20px; color: #111827; font-size: 24px; font-weight: 600;">
                                        Junte-se à equipe
                                    </h2>

                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        <strong>{inviter_name}</strong> convidou você para fazer parte da equipe
                                        <strong>{company_name}</strong> no ControlladorIA.
                                    </p>

                                    <!-- Company Box -->
                                    <div style="margin: 30px 0; padding: 24px; background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border-radius: 8px; text-align: center; border: 2px solid #10b981;">
                                        <p style="margin: 0 0 10px; color: #065f46; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">
                                            Empresa
                                        </p>
                                        <p style="margin: 0; color: #047857; font-size: 24px; font-weight: bold;">
                                            {company_name}
                                        </p>
                                        <p style="margin: 10px 0 0; color: #059669; font-size: 14px;">
                                            Convidado por {inviter_name}
                                        </p>
                                    </div>

                                    <h3 style="margin: 30px 0 15px; color: #111827; font-size: 18px; font-weight: 600;">
                                        Como membro da equipe, você terá acesso a:
                                    </h3>

                                    <ul style="margin: 0 0 30px; padding-left: 20px; color: #4b5563; font-size: 16px; line-height: 1.8;">
                                        <li>Todos os documentos financeiros da empresa</li>
                                        <li>Relatórios e análises (DRE, Fluxo de Caixa, Balanço)</li>
                                        <li>Upload e edição de documentos</li>
                                        <li>Colaboração em tempo real com a equipe</li>
                                    </ul>

                                    <!-- CTA Button -->
                                    <table role="presentation" style="margin: 0 auto;">
                                        <tr>
                                            <td style="border-radius: 6px; background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
                                                <a href="{invitation_url}"
                                                   style="display: inline-block; padding: 16px 32px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 600; border-radius: 6px;">
                                                    Aceitar Convite
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Ou copie e cole este link no seu navegador:
                                    </p>
                                    <p style="margin: 10px 0 0; color: #10b981; font-size: 14px; word-break: break-all;">
                                        {invitation_url}
                                    </p>

                                    <div style="margin: 30px 0 0; padding: 20px; background-color: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 4px;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.5;">
                                            <strong>Importante:</strong> Este convite expira em {expires_days} dias.
                                            Se você não aceitar até lá, solicite um novo convite ao administrador.
                                        </p>
                                    </div>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Se você não conhece {inviter_name} ou não esperava este convite,
                                        você pode ignorar este email com segurança.
                                    </p>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px;">
                                        ControlladorIA - Gestão Financeira Inteligente
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        © {current_year} ControlladorIA. Todos os direitos reservados.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=to,
            subject=f"{inviter_name} convidou você para {company_name} - ControlladorIA",
            html=html,
        )

    async def send_org_invitation_email(
        self,
        to: str,
        inviter_name: str,
        inviter_email: str,
        org_name: str,
        role: str,
        invitation_token: str,
        expires_days: int = 7,
    ) -> bool:
        """
        Send cross-org invitation email (user already has an account).

        Args:
            to: Email address of the person being invited
            inviter_name: Name of the inviter
            inviter_email: Email of the inviter
            org_name: Organization name
            role: Role being offered
            invitation_token: Unique invitation token
            expires_days: Days until expiration

        Returns:
            bool: True if sent successfully
        """
        invitation_url = f"{self.frontend_url}/organizations/accept-invitation/{invitation_token}"
        current_year = datetime.now().year

        # Role display names in Portuguese
        role_names = {
            "admin": "Administrador",
            "accountant": "Contador",
            "bookkeeper": "Auxiliar Contábil",
            "viewer": "Visualizador",
            "api_user": "Usuário API",
        }
        role_display = role_names.get(role, role.title())

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Convite para Organização - ControlladorIA</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 32px; font-weight: bold;">Nova Organização!</h1>
                                    <p style="margin: 10px 0 0; color: rgba(255,255,255,0.9); font-size: 16px;">
                                        Você foi convidado para participar
                                    </p>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        <strong>{inviter_name}</strong> ({inviter_email}) quer adicionar você à organização
                                        <strong>{org_name}</strong> no ControlladorIA.
                                    </p>

                                    <!-- Org + Role Box -->
                                    <div style="margin: 30px 0; padding: 24px; background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%); border-radius: 8px; text-align: center; border: 2px solid #667eea;">
                                        <p style="margin: 0 0 10px; color: #3730a3; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">
                                            Organização
                                        </p>
                                        <p style="margin: 0; color: #4338ca; font-size: 24px; font-weight: bold;">
                                            {org_name}
                                        </p>
                                        <p style="margin: 10px 0 0; color: #4f46e5; font-size: 14px;">
                                            Função: <strong>{role_display}</strong>
                                        </p>
                                    </div>

                                    <p style="margin: 0 0 30px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Ao aceitar, você terá acesso aos documentos e relatórios da organização
                                        com as permissões da função <strong>{role_display}</strong>.
                                    </p>

                                    <!-- CTA Button -->
                                    <table role="presentation" style="margin: 0 auto;">
                                        <tr>
                                            <td style="border-radius: 6px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                                                <a href="{invitation_url}"
                                                   style="display: inline-block; padding: 16px 32px; color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 600; border-radius: 6px;">
                                                    Aceitar Convite
                                                </a>
                                            </td>
                                        </tr>
                                    </table>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Ou copie e cole este link no seu navegador:
                                    </p>
                                    <p style="margin: 10px 0 0; color: #667eea; font-size: 14px; word-break: break-all;">
                                        {invitation_url}
                                    </p>

                                    <div style="margin: 30px 0 0; padding: 20px; background-color: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 4px;">
                                        <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.5;">
                                            <strong>Importante:</strong> Este convite expira em {expires_days} dias.
                                        </p>
                                    </div>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Se você não conhece {inviter_name} ou não esperava este convite,
                                        você pode ignorar este email com segurança.
                                    </p>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px;">
                                        ControlladorIA - Gestão Financeira Inteligente
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        © {current_year} ControlladorIA. Todos os direitos reservados.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=to,
            subject=f"{inviter_name} quer adicionar você à organização {org_name} - ControlladorIA",
            html=html,
        )

    async def send_mfa_code_email(
        self, to: str, user_name: str, code: str
    ) -> bool:
        """
        Send MFA verification code email

        Args:
            to: User email address
            user_name: User's full name
            code: 6-digit MFA code

        Returns:
            bool: True if sent successfully
        """
        current_year = datetime.now().year

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Código de Verificação - ControlladorIA</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #f3f4f6;">
            <table role="presentation" style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 40px 0; text-align: center;">
                        <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <!-- Header -->
                            <tr>
                                <td style="padding: 40px 40px 20px; text-align: center; background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border-radius: 8px 8px 0 0;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 32px; font-weight: bold;">🔐 Verificação em Duas Etapas</h1>
                                </td>
                            </tr>

                            <!-- Content -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 20px; color: #111827; font-size: 24px; font-weight: 600;">
                                        Olá, {user_name}!
                                    </h2>

                                    <p style="margin: 0 0 20px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Você solicitou um código de verificação para acessar sua conta no ControlladorIA.
                                    </p>

                                    <p style="margin: 0 0 30px; color: #4b5563; font-size: 16px; line-height: 1.5;">
                                        Use o código abaixo para completar seu login:
                                    </p>

                                    <!-- MFA Code Box -->
                                    <div style="margin: 30px 0; padding: 32px; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-radius: 8px; text-align: center; border: 3px solid #f59e0b;">
                                        <p style="margin: 0 0 10px; color: #78350f; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">
                                            Código de Verificação
                                        </p>
                                        <p style="margin: 0; color: #92400e; font-size: 48px; font-weight: bold; letter-spacing: 8px; font-family: 'Courier New', monospace;">
                                            {code}
                                        </p>
                                        <p style="margin: 10px 0 0; color: #92400e; font-size: 14px;">
                                            Digite este código na tela de login
                                        </p>
                                    </div>

                                    <div style="margin: 30px 0 0; padding: 20px; background-color: #fee2e2; border-left: 4px solid #ef4444; border-radius: 4px;">
                                        <p style="margin: 0; color: #991b1b; font-size: 14px; line-height: 1.5;">
                                            <strong>⚠️ Importante:</strong> Este código expira em <strong>10 minutos</strong>.
                                            Nunca compartilhe este código com ninguém!
                                        </p>
                                    </div>

                                    <p style="margin: 30px 0 0; color: #6b7280; font-size: 14px; line-height: 1.5;">
                                        Se você não solicitou este código, ignore este email e verifique a segurança da sua conta.
                                    </p>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="padding: 30px 40px; background-color: #f9fafb; border-radius: 0 0 8px 8px; text-align: center;">
                                    <p style="margin: 0 0 10px; color: #6b7280; font-size: 14px;">
                                        ControlladorIA - Gestão Financeira Inteligente
                                    </p>
                                    <p style="margin: 0; color: #9ca3af; font-size: 12px;">
                                        © {current_year} ControlladorIA. Todos os direitos reservados.
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        return await self.send_email(
            to=to,
            subject="Seu código de verificação - ControlladorIA",
            html=html,
        )


# Singleton instance
email_service = EmailService()
