from decimal import Decimal
from typing import List
from django.db.models import Sum
from core.interfaces.repositories import IPagoRepository
from adapters.infrastructure.models import PagoModel
from core.shared.enums import MetodoPagoEnum

class DjangoPagoRepository(IPagoRepository):

    def obtener_sumatoria_validada(self, factura_id: int) -> float:
        # El vínculo Factura-Pago web ahora vive en la observación para pagos directos a una factura
        suma = PagoModel.objects.filter(
            observacion__icontains=f"Factura #{factura_id}",
            detalles_metodos__metodo=MetodoPagoEnum.TRANSFERENCIA.value,
            validado=True
        ).aggregate(Sum('monto_total'))
        
        resultado = suma['monto_total__sum'] or Decimal("0.00")
        return float(resultado)

    def tiene_pagos_pendientes(self, factura_id: int) -> bool:
        return PagoModel.objects.filter(
            observacion__icontains=f"Factura #{factura_id}",
            detalles_metodos__metodo=MetodoPagoEnum.TRANSFERENCIA.value,
            validado=False
        ).exists()

    def registrar_pagos(self, factura_id: int, pagos: List[dict]) -> None:
        """
        Registra pagos provenientes de caja (Ventanilla).
        Crea una cabecera PagoModel y sus DetallePagoModel.
        """
        from adapters.infrastructure.models import PagoModel, DetallePagoModel, FacturaModel
        
        # 1. Obtenemos la Factura para saber a qué socio pertenece el pago
        factura = FacturaModel.objects.select_related('socio').get(id=factura_id)
        
        # 2. Creamos la CABECERA del Pago
        total_monto = sum(Decimal(str(p['monto'])) for p in pagos)
        
        pago_header = PagoModel.objects.create(
            socio=factura.socio,
            monto_total=total_monto,
            validado=True,
            observacion=f"Pago en Ventanilla (Factura #{factura_id})"
        )
        
        # 3. Creamos los DETALLES (Efectivo, Transferencia, etc)
        detalles_a_crear = []
        for p in pagos:
            metodo = p.get('metodo')
            monto = Decimal(str(p['monto']))
            referencia = p.get('referencia')
            
            detalles_a_crear.append(DetallePagoModel(
                pago=pago_header,
                metodo=metodo,
                monto=monto,
                referencia=referencia
            ))

        if detalles_a_crear:
            DetallePagoModel.objects.bulk_create(detalles_a_crear)

    def obtener_ultimos_pagos(self, socio_id: int, limite: int = 5) -> List[dict]:
        """
        Retorna los últimos pagos realizados por el socio.
        Incluye el link al PDF de la factura pagada si existe.
        """
        # Obtenemos los pagos a través de la relación con Factura -> Socio
        pagos = PagoModel.objects.filter(
            factura__socio_id=socio_id,
            validado=True
        ).select_related('factura').order_by('-fecha_registro')[:limite]

        resultado = []
        for p in pagos:
            # Construimos la URL del PDF si existe en la factura
            pdf_url = None
            if p.factura.archivo_pdf:
                pdf_url = p.factura.archivo_pdf.url
            
            # Formato simple para cumplir contrato
            item = {
                "fecha": p.fecha_registro.date(),
                "monto": p.monto,
                "recibo_nro": f"PAG-{p.id}", # Generamos un ID de recibo virtual
                "archivo_pdf": pdf_url
            }
            resultado.append(item)
            
        return resultado
