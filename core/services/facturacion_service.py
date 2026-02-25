# core/services/facturacion_service.py
from typing import List, Dict
from decimal import Decimal
from datetime import date

# Imports de tus Entidades de Dominio
from core.domain.factura import Factura
from core.domain.lectura import Lectura
from core.domain.socio import Socio
from adapters.infrastructure.models import LecturaModel

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
        
        # 2. Calcular Consumo de Agua (Usando tu lógica de Tarifa Plana)
        consumo = lectura.valor - lectura.lectura_anterior
        if consumo < 0: consumo = 0 # Protección de datos
        
        # Esto ejecuta la lógica de los $3.00 base + excedentes
        factura_temp.calcular_total_con_medidor(int(consumo))
        
        monto_agua = factura_temp.total # Guardamos el subtotal solo del agua

        # 3. Sumar las Multas Pendientes
        total_multas = Decimal("0.00")
        nombres_multas = []
        
        for multa in multas_pendientes:
            valor = Decimal(str(multa['valor']))
            # Agregamos la multa al objeto factura para que sume al total
            factura_temp.agregar_multa(multa['motivo'], valor)
            
            total_multas += valor
            nombres_multas.append(multa['motivo'])

        # 4. Retornar el JSON exacto que pidió tu compañero
        return {
            "id": lectura.id, # Usamos el ID de la lectura como referencia temporal
            "fecha_lectura": lectura.fecha,
            # Nota: Si lectura tiene el codigo inyectado, úsalo, sino usa el ID
            "medidor_codigo": getattr(lectura, 'medidor_codigo', str(lectura.medidor_id)),
            "socio_nombre": f"{socio.nombres} {socio.apellidos}",
            "cedula": socio.identificacion, # <--- BUG ARREGLADO AQUI
            
            "lectura_anterior": float(lectura.lectura_anterior),
            "lectura_actual": float(lectura.valor),
            "consumo": float(consumo),
            
            "monto_agua": float(monto_agua),
            "multas_mingas": float(total_multas),
            "detalle_multas": nombres_multas, # Array de strings
            
            "total_pagar": float(factura_temp.total)
        }
        
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
            # DEFENSIVO: Si el medidor no tiene terreno asignado (está en bodega o retirado) 
            # o el terreno no tiene socio, saltamos esta lectura para no crashear.
            if not lectura.medidor or not lectura.medidor.terreno or not lectura.medidor.terreno.socio:
                continue

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