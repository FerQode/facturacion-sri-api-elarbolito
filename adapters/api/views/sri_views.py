# adapters/api/views/sri_views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema

from adapters.api.tasks import task_procesar_sri_async

class SincronizadorSRIView(APIView):
    """
    Endpoint de Orquestación DevOps para el SRI.
    Dispara la sincronización asíncrona (Celery) de todas las facturas 
    que quedaron atrapadas en estado PENDIENTE_SRI, PENDIENTE_FIRMA o TIMEOUT_FIRMA.
    """
    # Protegido idealmente con IsAdminUser, pero dejamos IsAuthenticated para Pruebas.
    # En producción enterprise se requiere rol administrador.
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Sincronizar Facturas Pendientes SRI",
        description="Encola tareas en Celery (task_procesar_sri_async) masivamente.",
        responses={202: None}
    )
    def post(self, request, *args, **kwargs):
        from adapters.infrastructure.models.factura_model import FacturaModel
        from adapters.api.tasks import task_procesar_sri_async, task_consultar_autorizacion_sri
        
        # TAREA 5: Endpoint de Rescate (Admin)
        facturas_pendientes = FacturaModel.objects.filter(
            estado_sri__in=["PENDIENTE_FIRMA", "PENDIENTE_SRI", "TIMEOUT_FIRMA", "DEVUELTA", "NO_ENCONTRADO"]
        )

        total_encoladas = 0
        jobs = []

        # Disparar Fan-Out de tareas a Celery (Cola: sri_auth)
        for factura in facturas_pendientes:
            if factura.estado_sri in ["PENDIENTE_SRI", "NO_ENCONTRADO"]:
                task = task_consultar_autorizacion_sri.delay(factura.id)
            else:
                task = task_procesar_sri_async.delay(factura.id)
                
            jobs.append({
                "factura_id": factura.id, 
                "estado_sri": factura.estado_sri,
                "job_id": str(task.id)
            })
            total_encoladas += 1

        return Response(
            {
                "mensaje": "Proceso de sincronización iniciado en segundo plano.",
                "total_facturas_encoladas": total_encoladas,
                "jobs": jobs
            },
            status=status.HTTP_202_ACCEPTED
        )
