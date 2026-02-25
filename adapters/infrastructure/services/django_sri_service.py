# adapters/infrastructure/services/django_sri_service.py

import os
import logging
import subprocess
import base64
import random
from datetime import datetime
from tempfile import NamedTemporaryFile
from itertools import cycle
from pathlib import Path
from django.conf import settings

# Django & Third Party
from django.conf import settings
from lxml import etree
import zeep
from zeep.helpers import serialize_object
import json

# Core (Clean Architecture)
from core.interfaces.services import ISRIService, SRIAuthData, SRIResponse
from core.domain.factura import Factura
from core.domain.socio import Socio

logger = logging.getLogger(__name__)

from adapters.infrastructure.repositories.django_sri_repository import DjangoSRISecuencialRepository

class DjangoSRIService(ISRIService):
    """
    Implementación robusta del Servicio SRI.
    - Generación XML: Python (lxml)
    - Firma Digital: Java (sri.jar externo) -> Estabilidad garantizada.
    - Envío SOAP: Python (Zeep)
    - Secuenciales: DB Transactional Shielding
    """

    def __init__(self):
        try:
            # Inicializamos repositorio de secuencias
            self.secuencial_repo = DjangoSRISecuencialRepository()
            
            # Validación: Debe existir O la ruta física O el Base64
            has_path = hasattr(settings, 'SRI_FIRMA_PATH') and settings.SRI_FIRMA_PATH
            has_base64 = hasattr(settings, 'SRI_FIRMA_BASE64') and settings.SRI_FIRMA_BASE64

            if not has_path and not has_base64:
                raise ValueError("ERROR CONFIG: Debe definir SRI_FIRMA_PATH (Local) o SRI_FIRMA_BASE64 (Nube).")

            # Si hay path, lo usamos. Si no, pasamos None y lo manejamos en _firmar_xml
            firma_path_val = str(settings.SRI_FIRMA_PATH) if has_path else None

            self.auth = SRIAuthData(
                firma_path=firma_path_val,
                firma_pass=settings.SRI_FIRMA_PASS,
                sri_url_recepcion=settings.SRI_URL_RECEPCION,
                sri_url_autorizacion=settings.SRI_URL_AUTORIZACION
            )

            # Inicializamos clientes SOAP (Zeep es moderno y maneja bien WSDLs del SRI)
            self.soap_client_recepcion = zeep.Client(self.auth.sri_url_recepcion)
            self.soap_client_autorizacion = zeep.Client(self.auth.sri_url_autorizacion)

            # Ruta absoluta al JAR de firma (Basado en tu estructura de carpetas)
            self.jar_path = os.path.join(
                settings.BASE_DIR,
                'adapters', 'infrastructure', 'files', 'jar', 'sri.jar'
            )

            if not os.path.exists(self.jar_path):
                logger.warning(f"⚠️ ADVERTENCIA: No se encuentra sri.jar en: {self.jar_path}")

        except Exception as e:
            logger.error(f"Error inicializando DjangoSRIService: {e}")
            raise e

    # --- 1. LÓGICA DE CLAVES (Módulo 11) ---

    def _compute_mod11(self, pass_key_48: str) -> str:
        """Algoritmo oficial del SRI para dígito verificador (Portado del Proyecto A)"""
        if len(pass_key_48) > 48:
            return ''
        addition = 0
        factors = cycle((2, 3, 4, 5, 6, 7))
        for digit, factor in zip(reversed(pass_key_48), factors):
            addition += int(digit) * factor
        number = 11 - addition % 11
        if number == 11:
            number = 0
        elif number == 10:
            number = 1
        return str(number)

    def generar_clave_acceso(self, fecha_emision: datetime.date, nro_factura: str) -> str:
        """Genera la clave de acceso de 49 dígitos"""
        fecha = fecha_emision.strftime('%d%m%Y')
        tipo_comprobante = "01"  # Factura
        ruc = settings.SRI_EMISOR_RUC # Configuración Centralizada
        ambiente = str(settings.SRI_AMBIENTE) # 1: Pruebas, 2: Producción

        # Serie: Estab + Punto Emisión
        serie = f"{settings.SRI_SERIE_ESTABLECIMIENTO}{settings.SRI_SERIE_PUNTO_EMISION}"
        secuencial = nro_factura.zfill(9)

        # Código numérico aleatorio (8 dígitos)
        codigo_numerico = ''.join(random.choices("0123456789", k=8))
        tipo_emision = "1" # Normal

        # Primeros 48 dígitos
        clave_48 = f"{fecha}{tipo_comprobante}{ruc}{ambiente}{serie}{secuencial}{codigo_numerico}{tipo_emision}"

        # Dígito verificador
        digito_verificador = self._compute_mod11(clave_48)

        clave_acceso = f"{clave_48}{digito_verificador}"

        if len(clave_acceso) != 49:
            raise ValueError(f"Error generando clave acceso. Longitud obtenida: {len(clave_acceso)}")

        return clave_acceso

    # --- 2. GENERACIÓN XML ---

    def _generar_xml_factura(self, factura: Factura, socio: Socio) -> tuple[str, str]:
        """Construye el XML v1.1.0 usando lxml"""
        try:
            # LÓGICA DE SECUENCIAL (ATÓMICA DB)
            # Usamos el repositorio con bloqueo para garantizar unicidad
            numero_secuencial = self.secuencial_repo.obtener_siguiente_secuencial('01')
            nro_factura_secuencial = str(numero_secuencial)

            if factura.sri_clave_acceso:
                clave_acceso = factura.sri_clave_acceso
            else:
                clave_acceso = self.generar_clave_acceso(
                    fecha_emision=factura.fecha_emision,
                    nro_factura=str(numero_secuencial)
                )

            # Nodo Raíz
            xml_factura = etree.Element("factura", id="comprobante", version="1.1.0")

            # Info Tributaria
            info_tributaria = etree.SubElement(xml_factura, "infoTributaria")
            etree.SubElement(info_tributaria, "ambiente").text = str(settings.SRI_AMBIENTE)
            etree.SubElement(info_tributaria, "tipoEmision").text = "1"
            etree.SubElement(info_tributaria, "razonSocial").text = settings.SRI_EMISOR_RAZON_SOCIAL
            etree.SubElement(info_tributaria, "nombreComercial").text = settings.SRI_NOMBRE_COMERCIAL
            etree.SubElement(info_tributaria, "ruc").text = settings.SRI_EMISOR_RUC
            etree.SubElement(info_tributaria, "claveAcceso").text = clave_acceso
            etree.SubElement(info_tributaria, "codDoc").text = "01"
            etree.SubElement(info_tributaria, "estab").text = settings.SRI_SERIE_ESTABLECIMIENTO
            etree.SubElement(info_tributaria, "ptoEmi").text = settings.SRI_SERIE_PUNTO_EMISION
            etree.SubElement(info_tributaria, "secuencial").text = nro_factura_secuencial.zfill(9)
            etree.SubElement(info_tributaria, "dirMatriz").text = settings.SRI_EMISOR_DIRECCION_MATRIZ

            # Info Factura
            info_factura = etree.SubElement(xml_factura, "infoFactura")
            etree.SubElement(info_factura, "fechaEmision").text = factura.fecha_emision.strftime('%d/%m/%Y')
            etree.SubElement(info_factura, "dirEstablecimiento").text = settings.SRI_EMISOR_DIRECCION_MATRIZ
            etree.SubElement(info_factura, "obligadoContabilidad").text = getattr(settings, 'SRI_OBLIGADO_CONTABILIDAD', 'NO')
            # LÓGICA DINÁMICA DE IDENTIFICACIÓN
            # Tabla 6 del SRI
            codigo_tipo_id = "05" # Default Cédula
            
            # Normalizamos a mayúsculas por si acaso
            tipo = str(socio.tipo_identificacion).upper()
            
            if 'RUC' in tipo or tipo == 'R':
                codigo_tipo_id = "04"
            elif 'PASAPORTE' in tipo or tipo == 'P':
                codigo_tipo_id = "06"

            etree.SubElement(info_factura, "tipoIdentificacionComprador").text = codigo_tipo_id
            
            nombre_completo = f"{socio.nombres} {socio.apellidos}".strip()
            etree.SubElement(info_factura, "razonSocialComprador").text = nombre_completo
            
            # Usamos el nuevo campo 'identificacion'
            etree.SubElement(info_factura, "identificacionComprador").text = socio.identificacion
            etree.SubElement(info_factura, "totalSinImpuestos").text = f"{factura.subtotal:.2f}"
            etree.SubElement(info_factura, "totalDescuento").text = "0.00"

            # Totales con Impuestos
            total_con_impuestos = etree.SubElement(info_factura, "totalConImpuestos")
            total_impuesto = etree.SubElement(total_con_impuestos, "totalImpuesto")
            etree.SubElement(total_impuesto, "codigo").text = "2" # IVA
            etree.SubElement(total_impuesto, "codigoPorcentaje").text = "0" # 0% (Juntas de Agua suelen ser 0%)
            etree.SubElement(total_impuesto, "baseImponible").text = f"{factura.subtotal:.2f}"
            etree.SubElement(total_impuesto, "valor").text = "0.00"

            etree.SubElement(info_factura, "propina").text = "0.00"
            etree.SubElement(info_factura, "importeTotal").text = f"{factura.total:.2f}"
            etree.SubElement(info_factura, "moneda").text = "DOLAR"

            # Pagos
            pagos = etree.SubElement(info_factura, "pagos")
            pago = etree.SubElement(pagos, "pago")
            etree.SubElement(pago, "formaPago").text = "01" # Sin utilización del sistema financiero (Efectivo)
            etree.SubElement(pago, "total").text = f"{factura.total:.2f}"

            # Detalles
            detalles = etree.SubElement(xml_factura, "detalles")
            for i, detalle_entidad in enumerate(factura.detalles, 1):
                detalle_xml = etree.SubElement(detalles, "detalle")
                etree.SubElement(detalle_xml, "codigoPrincipal").text = str(i)
                etree.SubElement(detalle_xml, "descripcion").text = detalle_entidad.concepto[:300]
                etree.SubElement(detalle_xml, "cantidad").text = f"{detalle_entidad.cantidad:.2f}"
                etree.SubElement(detalle_xml, "precioUnitario").text = f"{detalle_entidad.precio_unitario:.4f}"
                etree.SubElement(detalle_xml, "descuento").text = "0.00"
                etree.SubElement(detalle_xml, "precioTotalSinImpuesto").text = f"{detalle_entidad.subtotal:.2f}"

                impuestos_detalle = etree.SubElement(detalle_xml, "impuestos")
                impuesto_detalle = etree.SubElement(impuestos_detalle, "impuesto")
                etree.SubElement(impuesto_detalle, "codigo").text = "2"
                etree.SubElement(impuesto_detalle, "codigoPorcentaje").text = "0"
                etree.SubElement(impuesto_detalle, "tarifa").text = "0"
                etree.SubElement(impuesto_detalle, "baseImponible").text = f"{detalle_entidad.subtotal:.2f}"
                etree.SubElement(impuesto_detalle, "valor").text = "0.00"

            # Convertir a String
            xml_bytes = etree.tostring(xml_factura, encoding="UTF-8", xml_declaration=True, pretty_print=False)
            # Reemplazar comillas simples por dobles (SRI a veces molesta con esto)
            xml_str = xml_bytes.decode("utf-8").replace("'", '"')

            return xml_str, clave_acceso

        except Exception as e:
            logger.error(f"Error generando XML: {e}")
            raise ValueError(f"Error generando estructura XML: {str(e)}")

    # --- 3. FIRMA DIGITAL (Lógica JAVA del Proyecto A Inyectada) ---

    def _firmar_xml_java(self, xml_string: str, clave_acceso: str) -> str:
        """
        Ejecuta el archivo .jar para firmar el XML.
        Soporta firma desde archivo local O desde variable de entorno Base64.
        """
        logger.info("Iniciando proceso de firma con Java...")
        
        temp_input_path = ""
        path_xml_firmado = ""
        temp_p12_path = "" # Path del archivo P12 temporal (si se usa Base64)

        try:
            import tempfile
            import os
            import uuid
            
            # Generar identificador único para concurrencia
            req_id = uuid.uuid4().hex[:8]
            
            # 1. Resolver el archivo P12
            p12_path_to_use = self.auth.firma_path
            
            # Prioridad: Base64 (Nube/Railway)
            base64_firma = getattr(settings, 'SRI_FIRMA_BASE64', None)
            
            if base64_firma:
                logger.info("🔑 Usando Firma Electrónica desde variable de entorno (Base64)")
                # 1. Limpieza agresiva del Base64 (Auditoría DevOps)
                base64_limpia = base64_firma.strip().replace('"', '').replace('\r', '').replace('\n', '').replace(' ', '')
                
                # Reparación de Padding
                missing_padding = len(base64_limpia) % 4
                if missing_padding:
                    base64_limpia += '=' * (4 - missing_padding)
                    
                # Decodificación estricta
                try:
                    p12_bytes = base64.b64decode(base64_limpia, validate=True)
                    if len(p12_bytes) < 1024:
                        raise ValueError("El certificado P12 decodificado es sospechosamente pequeño (< 1KB).")
                except Exception as e:
                    logger.error(f"Error decodificando Base64 del P12: {e}")
                    raise ValueError(f"ERROR_CERTIFICADO: Error en variable SRI_FIRMA_BASE64 (basura o corrupta): {str(e)}")

                # 2. Escritura Binaria y Vaciado a Disco (Crítico)
                p12_path_to_use = os.path.join('/tmp', f"sri_p12_{req_id}.p12")
                with open(p12_path_to_use, "wb") as f:
                    f.write(p12_bytes)
                    f.flush()
                    os.fsync(f.fileno()) # Forzar al OS a escribir en disco físico de Railway

            if not p12_path_to_use or not os.path.exists(p12_path_to_use):
                raise FileNotFoundError(f"No se encontró archivo de firma física ni Base64 valido. Ruta intentada: {p12_path_to_use}")

            # Escribimos también el XML de entrada con fsync garantizado
            temp_input_path = os.path.join('/tmp', f"sri_xml_{req_id}.xml")
            xml_bytes = xml_string.encode('utf-8')
            with open(temp_input_path, "wb") as f_xml:
                f_xml.write(xml_bytes)
                f_xml.flush()
                os.fsync(f_xml.fileno())

            # 3. Auditoría Forense en los Logs
            import hashlib
            import binascii
            sha256_hash = hashlib.sha256(p12_bytes).hexdigest() if base64_firma else "LOCAL_FILE"
            hex_prefix = binascii.hexlify(p12_bytes[:16]).decode('ascii') if base64_firma else "UNKNOWN"
            size_disk = os.path.getsize(p12_path_to_use)
            logger.info("=== AUDITORÍA FORENSE P12 ===")
            logger.info(f"SHA-256: {sha256_hash}")
            logger.info(f"Prefijo Hex (Primeros 16): {hex_prefix} (Debe ser PKCS12 válido, ej. 3082...)")
            logger.info(f"Tamaño real en disco: {size_disk} bytes")
            logger.info("=============================")

            # El JAR guarda el output en la misma carpeta que el input
            nombre_xml_salida = f"{clave_acceso}_signed.xml"
            output_dir = os.path.dirname(temp_input_path)
            path_xml_firmado = os.path.join(output_dir, nombre_xml_salida)

            # 4. Orden de Argumentos Garantizado para el JAR Externo
            commands = [
                'java',
                '-jar', self.jar_path,
                p12_path_to_use,      # Argumento 1: Ruta P12
                self.auth.firma_pass, # Argumento 2: Password
                temp_input_path,      # Argumento 3: Ruta XML Entrada
                output_dir,           # Argumento 4: Carpeta de Salida
                nombre_xml_salida     # Argumento 5: Nombre XML Firmado
            ]
            
            masked_commands = [c if c != self.auth.firma_pass else '***' for c in commands]
            logger.info(f"FORENSIC JAR CMD -> {masked_commands}")

            # Ejecutar Java con Timeout (Auditoría: Proteger workers de Gunicorn)
            try:
                result = subprocess.run(commands, capture_output=True, text=True, timeout=25)
            except subprocess.TimeoutExpired:
                logger.error("TIMEOUT_FIRMA: El JAR de firma SRI tardó más de 25 segundos.")
                raise Exception("TIMEOUT_FIRMA: El servicio local de firma SRI excedió el tiempo límite.")

            if result.returncode != 0:
                logger.error(f"Error Java STDERR: {result.stderr}")
                logger.error(f"Error Java STDOUT: {result.stdout[:500]}") # Truncar para logs
                raise Exception(f"Fallo al firmar con Java: {result.stderr}")

            # Leer el archivo firmado resultante
            if not os.path.exists(path_xml_firmado):
                 raise FileNotFoundError(f"El JAR no generó el archivo firmado en {path_xml_firmado}. Output: {result.stdout}")

            with open(path_xml_firmado, 'r', encoding='utf-8') as f:
                xml_firmado = f.read()

            return xml_firmado

        except Exception as e:
            logger.error(f"Excepción en firma Java: {e}")
            raise e
        finally:
            # Limpieza de archivos temporales
            # 1. XML Input
            if temp_input_path and os.path.exists(temp_input_path):
                try: os.remove(temp_input_path)
                except: pass
            
            # 2. XML Output (Firmado)
            if path_xml_firmado and os.path.exists(path_xml_firmado):
                try: os.remove(path_xml_firmado)
                except: pass
                
            # 3. P12 Temporal (Si se creó)
            if temp_p12_path and os.path.exists(temp_p12_path):
                try: os.remove(temp_p12_path)
                except: pass

    # --- 4. ENVÍO Y PARSEO (SOAP) ---

    def _enviar_comprobante_al_sri(self, xml_firmado: str) -> dict:
        logger.info("Enviando XML firmado al SRI...")
        try:
            # El SRI espera el XML en base64
            xml_b64 = base64.b64encode(xml_firmado.encode('utf-8')).decode('utf-8')
            response = self.soap_client_recepcion.service.validarComprobante(xml_b64)
            return response
        except Exception as e:
            logger.error(f"Error SOAP Recepción: {e}")
            return {"estado": "ERROR_CONEXION", "mensaje": str(e)}

    def _parsear_respuesta(self, response, clave_acceso, xml_enviado):
        # Mapeo de la respuesta Zeep a nuestra Entidad SRIResponse
        logger.info(f"DEBUG SRI - Estructura Respuesta: {response}")
        
        try:
            estado = response.estado # RECIBIDA / DEVUELTA
            mensajes = []

            # Lógica recursiva/robusta para extraer mensajes de error/advertencia
            try:
                # La estructura puede variar, a veces es lista, a veces objeto único
                comprobantes = getattr(response, 'comprobantes', None)
                if comprobantes and hasattr(comprobantes, 'comprobante'):
                    lista_comprobantes = comprobantes.comprobante
                    # Iterar comprobantes (usualmente 1 en envío sincrono)
                    for comp in lista_comprobantes:
                        msgs = getattr(comp, 'mensajes', None)
                        if msgs and hasattr(msgs, 'mensaje'):
                            for m in msgs.mensaje:
                                # Extraer campos clave
                                texto = getattr(m, 'mensaje', 'Sin mensaje')
                                info_ad = getattr(m, 'informacionAdicional', '')
                                tipo = getattr(m, 'tipo', 'INFO')
                                identificador = getattr(m, 'identificador', '')
                                
                                mensaje_formateado = f"[{tipo}] {texto}"
                                if info_ad:
                                    mensaje_formateado += f" ({info_ad})"
                                if identificador:
                                    mensaje_formateado += f" [ID:{identificador}]"
                                
                                mensajes.append(mensaje_formateado)
            except Exception as e_msg:
                mensajes.append(f"Error parseando detalles de mensajes: {str(e_msg)}")
                # Fallback: intentar convertir a string todo el objeto response
                mensajes.append(str(response))


            # Serialización correcta a Dict (para que REST Framework lo renderice como JSON anidado)
            try:
                # serialize_object devuelve un dict estándar de Python (listas, dicts, int, etc.)
                xml_response_dict = serialize_object(response)
            except:
                # Fallback: si falla, devolvemos un dict con el string
                xml_response_dict = {"raw": str(response)}

            if estado == 'RECIBIDA':
                return SRIResponse(
                    exito=True, autorizacion_id=clave_acceso, estado=estado,
                    mensaje_error=None, xml_enviado=xml_enviado, xml_respuesta=xml_response_dict
                )
            else:
                # Estado DEVUELTA
                mensaje_final = " | ".join(mensajes)
                if not mensaje_final:
                    mensaje_final = "Sin detalles de error (Revisar logs)"
                    
                return SRIResponse(
                    exito=False, autorizacion_id=clave_acceso, estado=estado,
                    mensaje_error=mensaje_final, xml_enviado=xml_enviado, xml_respuesta=xml_response_dict
                )

        except Exception as e:
             logger.error(f"Error crítico parseando respuesta SRI: {e}")
             return SRIResponse(
                exito=False, autorizacion_id=clave_acceso, estado="ERROR_PARSE_LOCAL",
                mensaje_error=f"Excepción local: {str(e)}", xml_enviado=xml_enviado, xml_respuesta=str(response)
            )

    # --- MÉTODOS PÚBLICOS DE INTERFACE ---

    def enviar_factura(self, factura: Factura, socio: Socio) -> SRIResponse:
        try:
            # 1. Generar
            xml_sin_firma, clave_acceso = self._generar_xml_factura(factura, socio)

            # 2. Firmar (JAVA)
            xml_firmado = self._firmar_xml_java(xml_sin_firma, clave_acceso)

            # 3. Enviar
            soap_response = self._enviar_comprobante_al_sri(xml_firmado)

            # 4. Parsear
            return self._parsear_respuesta(soap_response, clave_acceso, xml_firmado)

        except Exception as e:
            logger.error(f"Fallo crítico enviando factura: {e}")
            return SRIResponse(
                exito=False, autorizacion_id=None, estado="EXCEPTION",
                mensaje_error=str(e), xml_enviado=None, xml_respuesta=None
            )

    def consultar_autorizacion(self, clave_acceso: str) -> SRIResponse:
        # Implementación simple de consulta
        try:
            response = self.soap_client_autorizacion.service.autorizacionComprobante(clave_acceso)
            # Lógica similar de parseo... (simplificada por brevedad)
            autorizaciones = response.autorizaciones
            if autorizaciones and len(autorizaciones.autorizacion) > 0:
                auth = autorizaciones.autorizacion[0]
                return SRIResponse(
                    exito=(auth.estado == "AUTORIZADO"),
                    autorizacion_id=clave_acceso,
                    estado=auth.estado,
                    mensaje_error=None if auth.estado == "AUTORIZADO" else "No autorizado",
                    xml_enviado=None,
                    xml_respuesta=str(auth)
                )
            return SRIResponse(exito=False, autorizacion_id=clave_acceso, estado="NO_ENCONTRADO", mensaje_error="No existe", xml_enviado=None, xml_respuesta=None)
        except Exception as e:
             return SRIResponse(exito=False, autorizacion_id=clave_acceso, estado="ERROR", mensaje_error=str(e), xml_enviado=None, xml_respuesta=None)