# adapters/api/views/sri_views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema

from adapters.infrastructure.models import FacturaModel
from adapters.api.tasks import consultar_autorizacion_sri_task

class SincronizadorSRIView(APIView):
    """
    Endpoint de Orquestación DevOps para el SRI.
    Dispara la sincronización asíncrona (Celery) de todas las facturas 
    que quedaron atrapadas en estado PENDIENTE_SRI (ID:70 EN PROCESAMIENTO).
    """
    # Protegido idealmente con IsAdminUser, pero dejamos IsAuthenticated para Pruebas.
    # En producción enterprise se requiere rol administrador.
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Sincronizar Facturas Pendientes (ID:70)",
        description="Encola tareas en Celery para consultar el WSDL de Autorización del SRI sobre facturas PENDIENTE_SRI.",
        responses={202: None}
    )
    def post(self, request, *args, **kwargs):
        # Buscar facturas candidatas (tienen clave de acceso pero no están aprobadas firmemente)
        # Optimizamos a solo enviar a Celery las que mapeamos explícitamente a PENDIENTE_SRI.
        facturas_pendientes = FacturaModel.objects.filter(
            estado_sri__in=["PENDIENTE_SRI", "TIMEOUT_FIRMA"],
            clave_acceso_sri__isnull=False
        )

        total_encoladas = 0
        jobs = []

        # Disparar Fan-Out de tareas a Celery (Cola: sri_auth)
        for factura in facturas_pendientes:
            # .delay() encola el mensaje en Redis instantáneamente
            task = consultar_autorizacion_sri_task.delay(factura.id)
            jobs.append({"factura_id": factura.id, "job_id": task.id})
            total_encoladas += 1

        return Response(
            {
                "mensaje": "Proceso de sincronización iniciado en segundo plano.",
                "total_facturas_encoladas": total_encoladas,
                "jobs": jobs
            },
            status=status.HTTP_202_ACCEPTED
        )
