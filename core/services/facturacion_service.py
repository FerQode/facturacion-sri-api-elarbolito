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
            # Solo buscamos lecturas que AÚN NO hayan sido facturadas
            lecturas = LecturaModel.objects.filter(esta_facturada=False).select_related('medidor', 'medidor__terreno', 'medidor__terreno__socio').all()
        except Exception:
            return []

        # Importamos la evaluación pura del dominio de tarifas de El Arbolito
        from core.domain.tarifas_el_arbolito import calcular_total_medidor_el_arbolito

        for lectura in lecturas:
            # DEFENSIVO: Si el medidor no tiene terreno asignado (está en bodega o retirado) 
            # o el terreno no tiene socio, saltamos esta lectura para no crashear.
            if not lectura.medidor or not lectura.medidor.terreno or not lectura.medidor.terreno.socio:
                continue

            # Los campos reales en LecturaModel son `valor` y `lectura_anterior`
            actual = lectura.valor or Decimal('0')
            anterior = lectura.lectura_anterior or Decimal('0')
            
            consumo = actual - anterior

            # Regla de Negocio: Modalidad MEDIDORES
            # Delegamos el cálculo a la función pura del reglamento oficial
            valor_agua = calcular_total_medidor_el_arbolito(consumo)

            item = {
                "socio_id": lectura.medidor.terreno.socio.id,
                "nombres": f"{lectura.medidor.terreno.socio.apellidos} {lectura.medidor.terreno.socio.nombres}",
                "identificacion": lectura.medidor.terreno.socio.identificacion,
                "lectura_id": f"{int(anterior)} -> {int(actual)}",
                "lectura_real_id": lectura.id,
                "medidor_id": lectura.medidor.id,
                "medidor_codigo": lectura.medidor.codigo,
                "consumo": "Consumo de Agua Potable", # Rubro visible en frontend
                "lectura_anterior": float(anterior),
                "lectura_actual": float(actual),
                "consumo_m3": float(consumo),
                "valor_agua": round(float(valor_agua), 2),
                "multas": 0.00,       
                "subtotal": round(float(valor_agua), 2)
            }
            datos_pendientes.append(item)

        # B. SOCIOS SIN MEDIDOR (TARIFA FIJA)
        try:
            from adapters.infrastructure.models import ServicioModel
            from core.domain.tarifas_el_arbolito import TARIFA_FIJA
            
            servicios_fijos = ServicioModel.objects.filter(tipo='FIJO', activo=True).select_related('socio')
            for serv in servicios_fijos:
                datos_pendientes.append({
                    "socio_id": serv.socio.id,
                    "nombres": f"{serv.socio.apellidos} {serv.socio.nombres} (FIJO)",
                    "identificacion": serv.socio.identificacion,
                    "lectura_id": "N/A",
                    "lectura_real_id": None,
                    "medidor_id": None,
                    "medidor_codigo": "N/A",
                    "consumo": "Tarifa Fija Mensual",
                    "lectura_anterior": 0.0,
                    "lectura_actual": 0.0,
                    "consumo_m3": 0.0,
                    "valor_agua": float(TARIFA_FIJA),
                    "multas": 0.00,
                    "subtotal": float(TARIFA_FIJA)
                })
        except Exception as e:
            print(f"Error cargando servicios fijos: {e}")

        return datos_pendientes

    def ejecutar_emision_masiva(self, lista_facturas: list) -> Dict:
        """
        Toma los datos confirmados del Frontend y crea las Facturas en MySQL de forma Atómica.
        """
        from django.db import transaction
        from django.utils import timezone
        import uuid
        from adapters.infrastructure.models import FacturaModel, LecturaModel

        if not lista_facturas or not isinstance(lista_facturas, list):
            raise ValueError("No hay datos válidos para la emisión masiva")

        facturas_creadas = 0
        ahora = timezone.now()
        vencimiento = ahora + timezone.timedelta(days=15)

        with transaction.atomic():
            for item in lista_facturas:
                id_lectura_db = item.get('lectura_real_id')

                from django.db import IntegrityError

                # --- NUEVA VALIDACIÓN PARA SERVICIOS FIJOS (Sin medidor) ---
                if not id_lectura_db:
                    ya_facturado = FacturaModel.objects.filter(
                        socio_id=item.get('socio_id'),
                        lectura_id__isnull=True,
                        anio=ahora.year,
                        mes=ahora.month
                    ).exists()
                    
                    if ya_facturado:
                        # Ya se le cobró la Acometida este mes, saltamos al siguiente
                        continue

                try:
                    # Crear la Factura cabecera
                    FacturaModel.objects.create(
                        socio_id=item.get('socio_id'),
                        lectura_id=id_lectura_db, # ID numérico (o None para tarifa fija)
                        medidor_id=item.get('medidor_id'),
                        subtotal=item.get('subtotal', 0),
                        total=item.get('subtotal', 0),
                        impuestos=0.0,
                        estado='PENDIENTE',
                        fecha_emision=ahora.date(),
                        fecha_registro=ahora,
                        fecha_vencimiento=vencimiento.date(),
                        anio=ahora.year,
                        mes=ahora.month,
                        sri_ambiente=1,
                        sri_tipo_emision=1,
                        clave_acceso_sri=f"TEMP-{uuid.uuid4().hex[:10]}", # Temporal, luego se firma
                        estado_sri='PENDIENTE'
                    )

                    # Marcar lectura como facturada para no duplicar cobros
                    if id_lectura_db:
                        LecturaModel.objects.filter(id=id_lectura_db).update(esta_facturada=True)

                    facturas_creadas += 1

                except IntegrityError:
                    # Si la factura ya existe (Duplicado de lectura_id), la ignoramos y pasamos a la siguiente
                    continue

        return {
            "estado": "COMPLETADA",
            "cantidad": facturas_creadas
        }