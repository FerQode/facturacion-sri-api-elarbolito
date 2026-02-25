# adapters/api/tasks.py
import logging
from datetime import datetime
from celery import shared_task
from django.core.cache import cache

from adapters.infrastructure.repositories.django_factura_repository import DjangoFacturaRepository
from adapters.infrastructure.services.django_sri_service import DjangoSRIService
from adapters.infrastructure.services.email_service import DjangoEmailService

logger = logging.getLogger(__name__)

@shared_task(
    name="task_procesar_sri_async", 
    queue="sri_auth", 
    bind=True, 
    max_retries=3, 
    default_retry_delay=10
)
def task_procesar_sri_async(self, factura_id: int):
    """
    Fase 1: Firma XAdES-BES y Envío al WS de Recepción del SRI.
    """
    logger.info(f"[CELERY SRI] Iniciando envío de factura {factura_id} al SRI")
    try:
        factura_repo = DjangoFacturaRepository()
        sri_service = DjangoSRIService()
        
        factura = factura_repo.obtener_por_id(factura_id)
        if not factura:
            logger.error(f"[CELERY SRI] Factura {factura_id} no encontrada en BD. Posible Race Condition.")
            return "Factura no encontrada"

        # Obtenemos socio explícitamente usando django orm nativo aislado para la tarea
        from adapters.infrastructure.models.socio_model import SocioModel
        from core.domain.socio import Socio
        
        try:
            socio_db = SocioModel.objects.get(id=factura.socio_id)
            socio = Socio(
                id=socio_db.id, identificacion=socio_db.identificacion, nombres=socio_db.nombres,
                apellidos=socio_db.apellidos, email=socio_db.email, direccion=socio_db.direccion,
                tipo_identificacion=socio_db.tipo_identificacion, esta_activo=socio_db.esta_activo,
                barrio_id=socio_db.barrio_id, modalidad_cobro=socio_db.modalidad_cobro, rol=socio_db.rol
            )
        except SocioModel.DoesNotExist:
            logger.error(f"[CELERY SRI] Socio {factura.socio_id} no encontrado para Factura {factura_id}")
            return "Socio no encontrado"

        # Generar Clave (si falta o es temporal)
        if not factura.sri_clave_acceso or factura.sri_clave_acceso.startswith('TEMP-'):
            clave = sri_service.generar_clave_acceso(
                fecha_emision=factura.fecha_emision,
                nro_factura=str(factura.id)
            )
            factura.sri_clave_acceso = clave
            factura_repo.guardar(factura)

        # Enviar al SRI (Firma + WS Recepción)
        respuesta = sri_service.enviar_factura(factura, socio)

        if respuesta.exito:
            # Respuesta exitosa o si indica autorización directa
            factura.estado_sri = "PENDIENTE_SRI"
            factura_repo.guardar(factura)
            logger.info(f"[CELERY SRI] Emisión RECIBIDA (o firmada). Encolando consulta de Autorización.")
            # Encolar Paso 2 con delay
            task_consultar_autorizacion_sri.apply_async(args=[factura_id], countdown=10)
        else:
            is_processing = respuesta.mensaje_error and ("ID:70" in respuesta.mensaje_error.upper() or "EN PROCESAMIENTO" in respuesta.mensaje_error.upper())
            if is_processing:
                factura.estado_sri = "PENDIENTE_SRI"
                factura.sri_mensaje_error = respuesta.mensaje_error
                factura_repo.guardar(factura)
                logger.info(f"[CELERY SRI] ID:70 RECIBIDO. Encolando consulta de Autorización con backoff inicial (30s).")
                task_consultar_autorizacion_sri.apply_async(args=[factura_id], countdown=30)
            else:
                # Caso DEVUELTA / RECHAZADA / ERROR_FIRMA
                factura.estado_sri = "DEVUELTA"
                factura.sri_mensaje_error = respuesta.mensaje_error
                factura_repo.guardar(factura)
                logger.error(f"[CELERY SRI] XML Rechazado/Devuelto para Factura {factura_id}: {respuesta.mensaje_error}")

        return "Proceso Recepción Finalizado"
        
    except Exception as e:
        logger.error(f"[CELERY SRI] Excepción al procesar envío Factura {factura_id}: {e}")
        # Mantenemos limpia la Arquitectura fallando suave para no romper el Worker
        factura_repo = DjangoFacturaRepository()
        factura = factura_repo.obtener_por_id(factura_id)
        if factura:
            factura.estado_sri = "ERROR_FIRMA"
            factura.sri_mensaje_error = f"Excepción Celery: {str(e)[:250]}"
            factura_repo.guardar(factura)
        raise self.retry(exc=e)


@shared_task(
    name="task_consultar_autorizacion_sri", 
    queue="sri_auth", 
    bind=True, 
    max_retries=5
)
def task_consultar_autorizacion_sri(self, factura_id: int):
    """
    Fase 2: Llamada al WS de Autorización del SRI + Correo (Exponential Backoff ID:70).
    """
    logger.info(f"[CELERY SRI] Iniciando consulta de Autorización Factura {factura_id}")
    
    lock_id = f"lock_sri_auth_factura_{factura_id}"
    acquired = cache.add(lock_id, "locked", 300)
    
    if not acquired:
        logger.warning(f"[CELERY SRI] La factura {factura_id} ya se está consultando en otro worker.")
        # Retentamos levemente despues si hay bloqueo de carrera
        raise self.retry(countdown=30)

    try:
        factura_repo = DjangoFacturaRepository()
        sri_service = DjangoSRIService()
        email_service = DjangoEmailService()
        
        factura = factura_repo.obtener_por_id(factura_id)
        if not factura or not factura.sri_clave_acceso:
            return "Factura o clave no encontrada"

        # Llama al WS Autorización
        respuesta = sri_service.consultar_autorizacion(factura.sri_clave_acceso)

        if respuesta.exito and respuesta.estado == "AUTORIZADO":
            logger.info(f"[CELERY SRI] Factura {factura_id} Autorizada.")
            # Actualiza DB
            factura.estado_sri = "AUTORIZADO"
            factura.sri_xml_autorizado = respuesta.comprobante_autorizado or str(respuesta.xml_respuesta)
            if respuesta.fecha_autorizacion:
                 factura.sri_fecha_autorizacion = str(respuesta.fecha_autorizacion)
            factura.sri_mensaje_error = None
            factura_repo.guardar(factura)
            
            # Obtener socio y enviar correo
            from adapters.infrastructure.models.socio_model import SocioModel
            try:
                socio_db = SocioModel.objects.get(id=factura.socio_id)
                email_service.enviar_notificacion_factura(
                    email_destinatario=socio_db.email,
                    nombre_socio=f"{socio_db.nombres} {socio_db.apellidos}",
                    numero_factura=factura.id,
                    xml_autorizado=factura.sri_xml_autorizado
                )
            except Exception as email_err:
                logger.error(f"[CELERY SRI] Error enviando correo: {email_err}")

            return "AUTORIZADO"
            
        elif respuesta.estado == "EN PROCESAMIENTO" or (respuesta.mensaje_error and "ID:70" in str(respuesta.mensaje_error)):
            logger.warning(f"[CELERY SRI] Factura {factura_id} en procesamiento (ID:70). Reintentando...")
            raise self.retry(countdown=60, max_retries=5)
            
        else:
            logger.error(f"[CELERY SRI] Autorización Fallida/Rechazada para Factura {factura_id}: {respuesta.estado}")
            factura.estado_sri = "DEVUELTA" if respuesta.estado in ["DEVUELTA", "RECHAZADO"] else respuesta.estado
            factura.sri_mensaje_error = respuesta.mensaje_error
            factura_repo.guardar(factura)
            return respuesta.estado
            
    except Exception as e:
        if isinstance(e, self.retry().exc.__class__): # Si es Retry explícito
            raise e
        logger.error(f"[CELERY SRI] Excepción en Consulta SRI {factura_id}: {e}")
        # Retry solo si es fallo de red o intermitencia
        raise self.retry(exc=e, countdown=60)
        
    finally:
        cache.delete(lock_id)
