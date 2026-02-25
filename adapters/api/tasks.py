# adapters/api/tasks.py
import logging
from celery import shared_task
from django.core.cache import cache

from core.use_cases.sincronizar_facturas_sri_uc import SincronizarFacturasSRIUseCase
from adapters.infrastructure.repositories.django_factura_repository import DjangoFacturaRepository
from adapters.infrastructure.services.django_sri_service import DjangoSRIService
from adapters.infrastructure.services.email_service import DjangoEmailService

logger = logging.getLogger(__name__)

# Definimos una cola especializada para evitar que procesos pesados de SRI 
# bloqueen tareas rápidas del negocio
@shared_task(
    name="sri_auth_consultar", 
    queue="sri_auth", 
    bind=True, 
    max_retries=5, 
    default_retry_delay=60 * 2 # 2 minutos entre reintentos en caso de caídas del SRI
)
def consultar_autorizacion_sri_task(self, factura_id: int):
    """
    Tarea Asíncrona Celery: Consulta el SRI para ver si el ID:70 (EN PROCESAMIENTO)
    ya fue autorizado finalmente.
    """
    lock_id = f"lock_sri_auth_factura_{factura_id}"
    
    # 1. Mutex Distribuido (Redis Lock): Evita colisiones si un Cron y un Admin 
    # intentan consultar la misma factura al mismo milisegundo.
    # El candado dura máximo 5 minutos por si la tarea crashea.
    acquired = cache.add(lock_id, "locked", 300)
    
    if not acquired:
        logger.warning(f"[CELERY SRI] La factura {factura_id} ya se está consultando en otro worker. Omitiendo.")
        return "Locked by another worker"
        
    try:
        # Inyección manual y rápida para el Worker
        factura_repo = DjangoFacturaRepository()
        sri_service = DjangoSRIService()
        email_service = DjangoEmailService()
        
        # Orquestación de Capa de Aplicación
        uc = SincronizarFacturasSRIUseCase(factura_repo, sri_service, email_service)
        
        logger.info(f"[CELERY SRI] Disparando WSDL Autorización para Factura ID {factura_id}")
        resultado = uc.ejecutar_por_id(factura_id)
        
        # Excepciones controladas por el Use Case:
        if not resultado["exito"] and "ERROR_CONSULTA_WSDL" in resultado.get("estado", ""):
            logger.error(f"[CELERY SRI] Error de red SRI. Reintentando tarea ({self.request.retries}/5)")
            raise self.retry()
            
        return resultado
        
    except Exception as e:
        # Si no fue un retry controlado, también relanzar
        logger.error(f"Error crítico no controlado en Celery Task (Factura {factura_id}): {e}")
        # Retries solo si es soft error, si es bug de código no reintents
        if "retry" not in str(type(e)).lower():
            pass # Reportar a Sentry o similar
        raise e
        
    finally:
        # Siempre liberar el lock al terminar (éxito, error, o exception interna)
        cache.delete(lock_id)
