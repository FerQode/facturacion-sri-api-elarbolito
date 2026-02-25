# core/use_cases/registrar_cobro_uc.py
from decimal import Decimal
from typing import List, Dict, Tuple
from datetime import datetime
import hashlib
from django.core.cache import cache

# Interfaces (Puertos)
from core.interfaces.repositories import IFacturaRepository, IPagoRepository
from core.interfaces.services import ISRIService, IEmailService

# Dominio
from core.domain.factura import Factura, DetalleFactura, EstadoFactura
from core.domain.socio import Socio
from core.shared.exceptions import BusinessRuleException, EntityNotFoundException

class RegistrarCobroUseCase:
    """
    Gestiona la Recaudación, la Emisión Electrónica (SRI), Notificación y genera el Comprobante.
    Implementa el 'Candado de Seguridad' para validar transferencias previas.
    """

    def __init__(
        self, 
        factura_repo: IFacturaRepository, 
        pago_repo: IPagoRepository,
        sri_service: ISRIService,
        email_service: IEmailService
    ):
        # Inyección de Dependencias (DIP)
        self.factura_repo = factura_repo
        self.pago_repo = pago_repo
        self.sri_service = sri_service
        self.email_service = email_service

    def ejecutar(self, factura_id: int, lista_pagos: List[Dict]) -> Dict:
        # 1. Obtener Entidad (Agnóstico de la BD)
        factura = self.factura_repo.obtener_por_id(factura_id)
        if not factura:
            raise EntityNotFoundException(f"La factura {factura_id} no existe.")

        # 2. Validaciones de Dominio Puras
        # 2. Validaciones de Dominio Puras
        # Si ya estaba pagada por vía regular (otro monto u otro cajero) pero no hay caché de idempotencia de capa API:
        if factura.estado == EstadoFactura.PAGADA.value:
            if factura.estado_sri == "AUTORIZADO":
                 return self._build_api_contract_response("OK", "Factura previamente autorizada.", factura, total_abonado=factura.total)
            elif factura.estado_sri == "ERROR_FIRMA":
                 return self._build_api_contract_response("SRI_ERROR", "Factura pagada, pero firma SRI falló previamente.", factura, total_abonado=factura.total)
            else:
                 return self._build_api_contract_response("SRI_PENDIENTE", "Factura pagada, SRI pendiente.", factura, total_abonado=factura.total)
        
        # (Asumimos que la validación de ANULADA se maneja igual si existiera el estado)

        # 3. Lógica del "Candado" (Delegada al repositorio)
        if self.pago_repo.tiene_pagos_pendientes(factura.id):
             raise BusinessRuleException("Error: Existen transferencias subidas pero NO verificadas por Tesorería. Vaya al módulo de validación primero.")

        monto_transferencias = Decimal(self.pago_repo.obtener_sumatoria_validada(factura.id))
        
        # 4. Calcular Total Recibido (Efectivo + Transferencias Nuevas)
        # Refactor Clean Architecture: El caso de uso debe agnóstico al método.
        # Sumamos TODO lo que viene en la lista de pagos de la petición.
        total_recibido_caja = sum(
            Decimal(str(p['monto'])) 
            for p in lista_pagos 
        )
        
        # 5. Validación de Totales
        # Total Acumulado = (Transferencias YA validadas previamente) + (Dinero/Valores recibidos ahora)
        total_acumulado = monto_transferencias + total_recibido_caja
        faltante = factura.total - total_acumulado
        
        # Margen de error de 1 centavo
        if faltante > Decimal("0.01"):
            raise BusinessRuleException(
                f"Monto insuficiente. Faltan ${faltante}. "
                f"(Previo Validado: ${monto_transferencias} + Recibido Caja: ${total_recibido_caja})"
            )

        # 6. Persistencia
        # Registramos los nuevos pagos (Efectivo, Transferencia, Cheque, etc.)
        # El repositorio ya sabe cómo guardarlos y marcarlos como válidos si vienen de caja.
        self.pago_repo.registrar_pagos(factura.id, lista_pagos)
        
        # Actualizamos estado de la factura
        factura.estado = EstadoFactura.PAGADA
        factura.estado_sri = "PENDIENTE_FIRMA"
        self.factura_repo.guardar(factura) 

        # 7. Orquestación SRI + Email (ASÍNCRONO)
        from django.db import transaction
        from adapters.api.tasks import task_procesar_sri_async
        transaction.on_commit(lambda: task_procesar_sri_async.delay(factura.id))

        # 8. Construcción de respuesta estricta según contrato de UI (EJE 2)
        final_response = self._build_api_contract_response(
            "SRI_PENDIENTE", 
            "Cobro registrado. El SRI está procesando la factura en segundo plano.", 
            factura, 
            total_acumulado
        )
        
        return final_response

    def _build_api_contract_response(self, status: str, mensaje: str, factura: Factura, total_abonado: Decimal) -> Dict:
        """Construye el contrato estricto de UI asegurando que no haya undefined"""
        return {
            "status": status,
            "pago": {
                "total_abonado": float(total_abonado),
                "mensaje": "Cobro registrado exitosamente." if status in ["OK", "SRI_PENDIENTE"] else "Cobro registrado con advertencias SRI."
            },
            "factura": {
                "id": factura.id,
                "estado": factura.estado.value if hasattr(factura.estado, 'value') else factura.estado, # Debe ser string
                "estado_sri": factura.estado_sri or "PENDIENTE_FIRMA", # Nunca devolver None/undefined
                "mensaje_error_sri": factura.sri_mensaje_error or mensaje
            },
            "ride": {
                "pdf_url": f"/api/v1/facturas-gestion/{factura.id}/ride/" if status == "OK" else None
            }
        }


