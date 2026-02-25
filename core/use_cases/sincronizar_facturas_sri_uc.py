# core/use_cases/sincronizar_facturas_sri_uc.py
import logging
from typing import Dict, Any
from core.interfaces.repositories import IFacturaRepository
from core.interfaces.services import ISRIService, IEmailService

logger = logging.getLogger(__name__)

class SincronizarFacturasSRIUseCase:
    def __init__(
        self,
        factura_repo: IFacturaRepository,
        sri_service: ISRIService,
        email_service: IEmailService
    ):
        self.factura_repo = factura_repo
        self.sri_service = sri_service
        self.email_service = email_service

    def ejecutar_por_id(self, factura_id: int) -> Dict[str, Any]:
        """Sincroniza una factura específica por ID, ideal para pasarlo a un Celery Task individual."""
        factura = self.factura_repo.obtener_por_id(factura_id)
        
        if not factura:
            return {"exito": False, "mensaje": "Factura no encontrada"}
            
        if not factura.sri_clave_acceso:
            return {"exito": False, "mensaje": "Factura no tiene clave de acceso"}

        if factura.estado_sri == "AUTORIZADO": # Retrocompatibilidad si todavía existiese
            factura.estado_sri = "AUTORIZADO_SRI"
            self.factura_repo.guardar(factura)
            return {"exito": True, "mensaje": "Ya autorizada"}

        if factura.estado_sri not in ["PENDIENTE_SRI", "EXCEPTION", "DEVUELTA", "TIMEOUT_FIRMA"]:
             return {"exito": False, "mensaje": f"Estado actual '{factura.estado_sri}' no permite sincronización asíncrona."}

        # Consultar al SRI
        respuesta = self.sri_service.consultar_autorizacion(factura.sri_clave_acceso)

        if respuesta.exito and respuesta.estado == "AUTORIZADO":
            logger.info(f"¡Factura {factura_id} AUTORIZADA asíncronamente!")
            factura.estado_sri = "AUTORIZADO_SRI"
            factura.sri_xml_autorizado = respuesta.comprobante_autorizado or str(respuesta.xml_respuesta)
            
            # Formatear la fecha del SRI a string ISO si es posible
            if respuesta.fecha_autorizacion:
                 factura.sri_fecha_autorizacion = str(respuesta.fecha_autorizacion)
                 
            factura.sri_mensaje_error = None
            self.factura_repo.guardar(factura)
            
            # Enviar Email Asíncrono
            try:
                # TODO: Idealmente esto requiere el objeto socio. Obtener via socio_repo si no está.
                pass 
            except Exception as e:
                logger.error(f"Error enviando correo tras autorización asíncrona: {e}")

            return {"exito": True, "estado": "AUTORIZADO_SRI", "mensaje": "Factura Oficialmente Autorizada en 2do Plano"}
            
        elif respuesta.estado in ["RECHAZADO", "DEVUELTA"]:
            logger.warning(f"Factura {factura_id} DEVUELTA permanentemente.")
            factura.estado_sri = "DEVUELTA_SRI"
            factura.sri_mensaje_error = respuesta.mensaje_error
            self.factura_repo.guardar(factura)
            return {"exito": False, "estado": "DEVUELTA_SRI", "mensaje": respuesta.mensaje_error}

        elif respuesta.estado == "EN PROCESAMIENTO":
            logger.info(f"Factura {factura_id} SIGUE EN PROCESAMIENTO SRI. Queda pendiente.")
            # Se queda como PENDIENTE_SRI para el siguiente Cron/Task
            factura.estado_sri = "PENDIENTE_SRI" 
            factura.sri_mensaje_error = "[SRI] Aún procesando. Consultar luego."
            self.factura_repo.guardar(factura)
            return {"exito": False, "estado": "PENDIENTE_SRI", "mensaje": "Aún en procesamiento"}
            
        else:
            # NO_ENCONTRADO, ERROR_CONSULTA_WSDL
            return {"exito": False, "estado": respuesta.estado, "mensaje": respuesta.mensaje_error}
