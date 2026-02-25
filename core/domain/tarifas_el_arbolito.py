from decimal import Decimal, ROUND_HALF_UP

# Constantes Reglamentarias de la Junta "EL ARBOLITO"
TARIFA_FIJA = Decimal('3.00')
LIMITE = Decimal('120')
COSTO_M3_EXTRA = Decimal('0.25')

def calcular_total_medidor_el_arbolito(consumo_m3: Decimal) -> Decimal:
    """
    Calcula el total a pagar por consumo de agua para la modalidad MEDIDORES 
    según el Reglamento Interno y Normativa oficial de "EL ARBOLITO".
    
    Reglas de Negocio:
    1. Aporte mensual fijo de $3.00 (cubre hasta 120 m3).
    2. Excedente (mayor a 120 m3) se cobra a $0.25 por m3.
    """
    # Validar que no haya consumos negativos por error
    if consumo_m3 < Decimal('0'):
        consumo_m3 = Decimal('0')
        
    if consumo_m3 <= LIMITE:
        valor = TARIFA_FIJA
    else:
        excedente = consumo_m3 - LIMITE
        valor = TARIFA_FIJA + (excedente * COSTO_M3_EXTRA)
        
    # Cuantización a 2 decimales según reglas contables
    return valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
