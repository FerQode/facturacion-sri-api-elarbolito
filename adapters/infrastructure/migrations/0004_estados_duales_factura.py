# adapters/infrastructure/migrations/0004_estados_duales_factura.py
from django.db import migrations, models
import core.shared.enums

def mapear_estados_sri_historicos(apps, schema_editor):
    FacturaModel = apps.get_model('infrastructure', 'FacturaModel')
    
    # Usar bulk_update en lotes para escalabilidad
    to_update = []
    
    for factura in FacturaModel.objects.all().iterator(chunk_size=1000):
        cambio = False
        msg_error = (factura.mensaje_error_sri or "").upper()
        
        # Mapeo de legacy strings al nuevo Enum tipado
        if "[ID:70]" in msg_error or "EN PROCESAMIENTO" in msg_error:
            nuevo_estado = core.shared.enums.EstadoSRI.PENDIENTE_SRI.value
        elif factura.fecha_autorizacion_sri is not None:
            nuevo_estado = core.shared.enums.EstadoSRI.AUTORIZADA.value
        elif msg_error and "[ID:70]" not in msg_error:
            nuevo_estado = core.shared.enums.EstadoSRI.DEVUELTA.value
        elif factura.estado_sri == "AUTORIZADO":
            nuevo_estado = core.shared.enums.EstadoSRI.AUTORIZADA.value
        elif factura.estado_sri == "DEVUELTA":
            nuevo_estado = core.shared.enums.EstadoSRI.DEVUELTA.value
        elif factura.estado_sri == "ERROR_FIRMA":
            nuevo_estado = core.shared.enums.EstadoSRI.ERROR.value
        else:
            # Fallback a NO_ENVIADA o dejar como está si ya es un valor Enum
            try:
                # Comprobar si ya es un valid choice
                if any(factura.estado_sri == c[0] for c in core.shared.enums.EstadoSRI.choices):
                    nuevo_estado = factura.estado_sri
                else:
                    nuevo_estado = core.shared.enums.EstadoSRI.NO_ENVIADA.value
            except Exception:
                nuevo_estado = core.shared.enums.EstadoSRI.NO_ENVIADA.value
                
        # Idempotencia: solo actualizar si hay cambio real
        if factura.estado_sri != nuevo_estado:
            factura.estado_sri = nuevo_estado
            to_update.append(factura)
            
        if len(to_update) >= 500:
            FacturaModel.objects.bulk_update(to_update, ['estado_sri'])
            to_update = []
            
    if to_update:
        FacturaModel.objects.bulk_update(to_update, ['estado_sri'])

class Migration(migrations.Migration):

    dependencies = [
        ('infrastructure', '0003_alter_cuentaporcobrarmodel_estado_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='facturamodel',
            old_name='estado',
            new_name='estado_financiero',
        ),
        migrations.AlterField(
            model_name='facturamodel',
            name='estado_financiero',
            field=models.CharField(
                choices=core.shared.enums.EstadoFinanciero.choices, 
                default=core.shared.enums.EstadoFinanciero.PENDIENTE, 
                max_length=20
            ),
        ),
        migrations.AlterField(
            model_name='facturamodel',
            name='estado_sri',
            field=models.CharField(
                choices=core.shared.enums.EstadoSRI.choices, 
                default=core.shared.enums.EstadoSRI.NO_ENVIADA, 
                max_length=50
            ),
        ),
        migrations.RunPython(mapear_estados_sri_historicos, reverse_code=migrations.RunPython.noop),
    ]
