# adapters/infrastructure/services/email_service.py
import logging
from typing import List, Tuple, Any
from django.core.mail import EmailMessage
from django.conf import settings

from core.interfaces.services import IEmailService

logger = logging.getLogger(__name__)

class DjangoEmailService(IEmailService):
    def __init__(self):
        self.remitente = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@elarbolito.com')

    def enviar_con_adjuntos(
        self, 
        destinatario: str, 
        asunto: str, 
        cuerpo: str, 
        adjuntos: List[Tuple[str, bytes, str]]
    ) -> bool:
        """
        Método utilitario robusto para enviar un correo con N adjuntos.
        adjuntos: Lista de tuplas (nombre_archivo, contenido_bytes, mime_type)
        """
        try:
            email = EmailMessage(
                subject=asunto,
                body=cuerpo,
                from_email=self.remitente,
                to=[destinatario],
            )
            
            # Formatear el cuerpo como HTML (opcional pero recomendado)
            email.content_subtype = "html"

            # Iterar y adjuntar
            if adjuntos:
                for nombre_archivo, contenido, mime_type in adjuntos:
                    email.attach(nombre_archivo, contenido, mime_type)
            
            email.send(fail_silently=False)
            logger.info(f"Correo exitoso a: {destinatario} | Asunto: {asunto}")
            return True
            
        except Exception as e:
            logger.error(f"Error enviando correo a {destinatario}: {e}")
            return False

    def enviar_notificacion_factura(
        self, 
        email_destinatario: str, 
        nombre_socio: str, 
        numero_factura: int, 
        xml_autorizado: Any
    ) -> bool:
        """Implementación del método exigido por IEmailService."""
        
        # Validar destinatario
        if not email_destinatario or "@" not in email_destinatario:
            logger.warning(f"No se envía email a {nombre_socio} por dirección inválida: {email_destinatario}")
            return False

        asunto = f"El Arbolito - Factura Electrónica N° {numero_factura}"
        cuerpo = f"""
        <html>
            <body>
                <h2>Hola, <strong>{nombre_socio}</strong>,</h2>
                <p>Su factura electrónica número <strong>{numero_factura}</strong> ha sido emitida y autorizada con éxito por el Servicio de Rentas Internas (SRI).</p>
                <p>Adjunto a este correo encontrará el Documento Electrónico en formato XML.</p>
                <br>
                <p>Atentamente,<br><strong>Servicio de Gestión El Arbolito</strong></p>
            </body>
        </html>
        """

        adjuntos = []
        if xml_autorizado:
            # Asegurarse de que sea string y luego pasarlo a bytes
            if isinstance(xml_autorizado, dict):
                import json
                xml_str = json.dumps(xml_autorizado)
            else:
                xml_str = str(xml_autorizado)
            
            # Adjunto: Nombre, Contenido en BINARIO, MimeType
            adjuntos.append((f"FACTURA_{numero_factura}.xml", xml_str.encode('utf-8'), 'application/xml'))
            
            # Nota: Si se requiere el PDF también, tendríamos que generar el RIDE en memoria aquí y sumarlo a la tupla.
        
        return self.enviar_con_adjuntos(
            destinatario=email_destinatario,
            asunto=asunto,
            cuerpo=cuerpo,
            adjuntos=adjuntos
        )

    def enviar_notificacion_multa(
        self, 
        email_destinatario: str, 
        nombre_socio: str, 
        evento_nombre: str, 
        valor_multa: float
    ) -> bool:
        """Implementación del método exigido por IEmailService."""
        if not email_destinatario or "@" not in email_destinatario:
            return False

        asunto = "Notificación de Multa - El Arbolito"
        cuerpo = f"""
        <html>
            <body>
                <p>Estimado/a <strong>{nombre_socio}</strong>,</p>
                <p>Le informamos que se ha registrado una multa de <strong>${valor_multa:.2f}</strong> por inasistencia al evento: <strong>{evento_nombre}</strong>.</p>
                <p>Por favor regularice su situación en ventanilla en su próximo cobro.</p>
            </body>
        </html>
        """
        return self.enviar_con_adjuntos(
            destinatario=email_destinatario,
            asunto=asunto,
            cuerpo=cuerpo,
            adjuntos=[]
        )
