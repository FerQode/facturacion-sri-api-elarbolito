# core/domain/shared/enums.py
from enum import Enum
from django.db import models

class EstadoFactura(Enum):
    """
    Representa el estado de una factura.
    """
    PENDIENTE = 'PENDIENTE'
    POR_VALIDAR = 'POR_VALIDAR'
    PAGADA = 'PAGADA'
    ANULADA = 'ANULADA'

class RolUsuario(Enum):
    """
    Roles del sistema.
    """
    ADMINISTRADOR = "ADMINISTRADOR"
    TESORERO = "TESORERO"
    OPERADOR = "OPERADOR"
    SOCIO = "SOCIO"

class MetodoPagoEnum(Enum):
    EFECTIVO = "EFECTIVO"
    TRANSFERENCIA = "TRANSFERENCIA"
    CHEQUE = "CHEQUE"

class CodigoSRIEnum(Enum):
    # Tabla 24 del SRI (Formas de Pago)
    SIN_UTILIZACION_SISTEMA_FINANCIERO = "01" # Efectivo
    OTROS_CON_UTILIZACION_SISTEMA_FINANCIERO = "20" # Transferencias

class EstadoMulta(Enum):
    PENDIENTE = "PENDIENTE"
    PAGADA = "PAGADA"
    ANULADA = "ANULADA"

class ModalidadCobro(Enum):
    MEDIDOR = "MEDIDOR"
    TARIFA_FIJA = "TARIFA_FIJA"

class TipoRubro(Enum):
    AGUA_POTABLE = "AGUA_POTABLE"
    ALCANTARILLADO = "ALCANTARILLADO"
    RECONEXION = "RECONEXION"
    MULTA = "MULTA"
    MATERIALES = "MATERIALES"
    OTROS = "OTROS"

class EstadoCuentaPorCobrar(Enum):
    PENDIENTE = "PENDIENTE"
    EN_PROCESO_JUSTIFICACION = "EN_PROCESO_JUSTIFICACION"
    PAGADA_PARCIALMENTE = "PAGADA_PARCIALMENTE"
    FACTURADO = "FACTURADO" # Ya se emitió factura legal
    PAGADA = "PAGADA"
    ANULADO = "ANULADO"

class TipoEvento(Enum):
    NINGUNO = "NINGUNO"
    MINGA = "MINGA"
    ASAMBLEA = "ASAMBLEA"

class EstadoEvento(Enum):
    PROGRAMADO = "PROGRAMADO"
    REALIZADO = "REALIZADO"
    CANCELADO = "CANCELADO"

class EstadoAsistencia(Enum):
    ASISTIO = "ASISTIO"
    FALTA = "FALTA"
    ATRASO = "ATRASO"
    JUSTIFICADO = "JUSTIFICADO"

class EstadoJustificacion(Enum):
    SIN_SOLICITUD = "SIN_SOLICITUD"
    SOLICITADO = "SOLICITADO"
    APROBADO = "APROBADO"
    RECHAZADA = "RECHAZADA"

class EstadoSolicitud(Enum):
    PENDIENTE = "PENDIENTE"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"

class EstadoFinanciero(models.TextChoices):
    PENDIENTE = 'PENDIENTE', 'Pendiente'
    PAGADA = 'PAGADA', 'Pagada'
    ANULADA = 'ANULADA', 'Anulada'

class EstadoSRI(models.TextChoices):
    NO_ENVIADA = 'NO_ENVIADA', 'No Enviada'
    PENDIENTE_FIRMA = 'PENDIENTE_FIRMA', 'Pendiente de Firma'
    PENDIENTE_SRI = 'PENDIENTE_SRI', 'Pendiente en SRI'
    AUTORIZADA = 'AUTORIZADA', 'Autorizada'
    DEVUELTA = 'DEVUELTA', 'Devuelta'
    RECHAZADA = 'RECHAZADA', 'Rechazada'
    ERROR = 'ERROR', 'Error'