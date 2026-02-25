# core/services/facturacion_service.py
from typing import List, Dict
from decimal import Decimal
from datetime import date

# Imports de tus Entidades de Dominio
from core.domain.factura import Factura
from core.domain.lectura import Lectura
from core.domain.socio import Socio

class FacturacionService:
    """
    Servicio de Dominio puro.
    Responsabilidad: Orquestar el cálculo de Agua + Multas = Total a Pagar.
    No guarda en base de datos, solo calcula.
    """

    def previsualizar_factura(self, lectura: Lectura, socio: Socio, multas_pendientes: List[Dict]) -> Dict:
        """
        Genera el DTO (Diccionario) plano que necesita el Frontend.
        """
        # 1. Instanciamos una Factura Temporal (En memoria)
        factura_temp = Factura(
            id=None,
            socio_id=socio.id,
            medidor_id=lectura.medidor_id,
            fecha_emision=date.today(),
            fecha_vencimiento=date.today(),
            lectura=lectura
        )
        
    @staticmethod
    def calcular_pre_emision_masiva():
        """
        Calcula qué se va a facturar basándose en las LECTURAS registradas en el sistema.
        Devuelve una lista de diccionarios con los datos listos para el Frontend.
        """
        datos_pendientes = []

        try:
            lecturas = LecturaModel.objects.select_related('medidor', 'medidor__terreno', 'medidor__terreno__socio').all()
        except Exception:
            return []

        for lectura in lecturas:
            # Los campos reales en LecturaModel son `valor` y `lectura_anterior`
            actual = lectura.valor or 0
            anterior = lectura.lectura_anterior or 0
            
            consumo = actual - anterior
            if consumo < 0: 
                consumo = 0

            # Calculo base de tarifa (Tarifa Fija de ejemplo o escalonada)
            tarifa_m3 = 0.50
            valor_agua = consumo * tarifa_m3

            item = {
                "socio_id": lectura.medidor.terreno.socio.id,
                "nombres": f"{lectura.medidor.terreno.socio.nombres} {lectura.medidor.terreno.socio.apellidos}",
                "lectura_anterior": float(anterior),
                "lectura_actual": float(actual),
                "consumo": float(consumo),
                "valor_agua": round(float(valor_agua), 2),
                "multas": 0.00,       
                "subtotal": round(float(valor_agua), 2)
            }
            datos_pendientes.append(item)

        return datos_pendientes