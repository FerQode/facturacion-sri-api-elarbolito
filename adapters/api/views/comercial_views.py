# adapters/api/views/comercial_views.py

from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, extend_schema_view
from django.utils import timezone

# Serializers
from adapters.api.serializers import (
    SocioSerializer,
    FacturaSerializer,
    PagoSerializer,
    CatalogoRubroSerializer,
    ProductoMaterialSerializer
)

# Modelos
from adapters.infrastructure.models import (
    SocioModel,
    FacturaModel,
    PagoModel,
    CatalogoRubroModel,
    ProductoMaterial,
    LecturaModel # ✅ IMPORTADO Y ACTIVO
)

@extend_schema_view(
    list=extend_schema(summary="Listar facturas"),
    retrieve=extend_schema(summary="Ver detalle de factura"),
)
class FacturaViewSet(viewsets.ModelViewSet):
    """
    Maneja la gestión de facturas.
    """
    queryset = FacturaModel.objects.all().order_by('-fecha_emision')
    serializer_class = FacturaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['socio__identificacion', 'numero_secuencial']

    # --- 1. Pre-Emisión (ACTIVO Y FUNCIONAL - REFACTORIZADO CLEAN ARCH) ---
    @action(detail=False, methods=['get'], url_path='pre-emision')
    def pre_emision(self, request):
        """
        Calcula qué se va a facturar basándose en las LECTURAS registradas en el sistema.
        Delegado al Dominio (FacturacionService) para no ensuciar el Adapter.
        """
        # Importamos el servicio de dominio (idealmente inyectado, pero así sirve por ahora)
        from core.services.facturacion_service import FacturacionService
        
        # El Adapter (Vista) solo orquesta: Llama al servicio y retorna HTTP
        service = FacturacionService()
        datos_pendientes = service.calcular_pre_emision_masiva()
        
        return Response(datos_pendientes, status=status.HTTP_200_OK)

    # --- 1.5 Emisión Masiva (POST) ---
    @action(detail=False, methods=['post'], url_path='emision-masiva')
    def emision_masiva(self, request):
        """
        Endpoint que recibe la orden del Frontend para generar las facturas reales en la Base de Datos.
        """
        from core.services.facturacion_service import FacturacionService
        
        # Le delegamos a la capa Core la responsabilidad de guardar (Transacciones DB)
        service = FacturacionService()
        
        try:
            lista_facturas = request.data
            resultado = service.ejecutar_emision_masiva(lista_facturas)
            return Response({
                "mensaje": "Emisión masiva completada con éxito.",
                "facturas_generadas": resultado.get('cantidad', 0)
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            import traceback
            traceback_str = traceback.format_exc()
            print(f"❌ ERROR CRÍTICO EN EMISIÓN MASIVA:\n{traceback_str}")
            return Response({
                "error": "Ocurrió un error al procesar la emisión masiva.",
                "detalle": str(e),
                "traceback": traceback_str # Temporalmente expuesto para el Frontend
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    # --- 2. Pendientes e Historial ---
    @action(detail=False, methods=['get'], url_path='pendientes')
    def pendientes(self, request):
        """
        Retorna las facturas que NO están pagadas, con soporte de filtros.
        Si ver_historial=true, retorna el historial completo (incluyendo PAGADAS).
        """
        from django.db.models import Q
        qs = self.get_queryset()
        
        ver_historial = request.GET.get('ver_historial') == 'true'
        
        # Filtro Central: Si no piden historial, ocultamos las pagadas/anuladas
        if not ver_historial:
            qs = qs.exclude(estado__in=['PAGADA', 'ANULADA'])

        # 🔎 FILTRO POR IDENTIFICACIÓN / NOMBRE / APELLIDO
        identificacion = request.GET.get('identificacion')
        if identificacion:
            qs = qs.filter(
                Q(socio__identificacion__icontains=identificacion) |
                Q(socio__nombres__icontains=identificacion) |
                Q(socio__apellidos__icontains=identificacion)
            )

        # 📅 FILTRO POR FECHA
        dia = request.GET.get('dia')
        mes = request.GET.get('mes')
        anio = request.GET.get('anio')
        
        if dia:
            qs = qs.filter(fecha_emision__day=dia)
        if mes:
            qs = qs.filter(fecha_emision__month=mes)
        if anio:
            qs = qs.filter(fecha_emision__year=anio)

        ver_historial = request.query_params.get('ver_historial') == 'true'
        if not ver_historial and not (dia or mes or anio or identificacion):
            # Por defecto, si no hay filtros explícitos, mostramos los del año actual
            qs = qs.filter(anio=timezone.now().year)

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # --- 3. ESTADO DE CUENTA POR SOCIO (GET) ---
    @action(detail=False, methods=['get'], url_path='estado-cuenta/(?P<identificacion>[^/.]+)')
    def estado_cuenta(self, request, identificacion=None):
        """
        Retorna la deuda completa (Estado de Cuenta) de un socio específico.
        """
        try:
            facturas = FacturaModel.objects.filter(
                socio__identificacion=identificacion
            ).exclude(estado='PAGADA').order_by('fecha_emision')

            if not facturas.exists():
                return Response([], status=status.HTTP_200_OK)

            serializer = self.get_serializer(facturas, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema_view(
    list=extend_schema(summary="Listar todos los socios"),
)
class SocioViewSet(viewsets.ModelViewSet):
    queryset = SocioModel.objects.all().order_by('apellidos')
    serializer_class = SocioSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['identificacion', 'nombres', 'apellidos']

class PagoViewSet(viewsets.ModelViewSet):
    queryset = PagoModel.objects.all().order_by('-fecha_registro')
    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head']

class CatalogoRubroViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CatalogoRubroModel.objects.filter(activo=True).order_by('nombre')
    serializer_class = CatalogoRubroSerializer
    permission_classes = [IsAuthenticated]

class ProductoMaterialViewSet(viewsets.ModelViewSet):
    queryset = ProductoMaterial.objects.filter(activo=True).order_by('nombre')
    serializer_class = ProductoMaterialSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['nombre', 'codigo']