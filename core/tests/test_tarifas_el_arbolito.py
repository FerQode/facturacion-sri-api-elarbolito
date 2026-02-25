from decimal import Decimal
from django.test import TestCase
from core.domain.tarifas_el_arbolito import calcular_total_medidor_el_arbolito

class TarifasElArbolitoTests(TestCase):
    def test_consumo_debajo_limite(self):
        """1) consumo=Decimal('100') => 3.00"""
        consumo = Decimal('100')
        resultado = calcular_total_medidor_el_arbolito(consumo)
        self.assertEqual(resultado, Decimal('3.00'))

    def test_consumo_al_limite(self):
        """2) consumo=Decimal('120') => 3.00"""
        consumo = Decimal('120')
        resultado = calcular_total_medidor_el_arbolito(consumo)
        self.assertEqual(resultado, Decimal('3.00'))

    def test_consumo_excedente(self):
        """3) consumo=Decimal('130') => 5.50 -> 3.00 + (10 * 0.25)"""
        consumo = Decimal('130')
        resultado = calcular_total_medidor_el_arbolito(consumo)
        self.assertEqual(resultado, Decimal('5.50'))

    def test_consumo_excedente_minimo(self):
        """4) consumo=Decimal('121') => 3.25"""
        consumo = Decimal('121')
        resultado = calcular_total_medidor_el_arbolito(consumo)
        self.assertEqual(resultado, Decimal('3.25'))
        
    def test_consumo_negativo_proteccion(self):
        """Consumo negativo debe tratarse como 0 y cobrar la base $3.00"""
        consumo = Decimal('-10')
        resultado = calcular_total_medidor_el_arbolito(consumo)
        self.assertEqual(resultado, Decimal('3.00'))
