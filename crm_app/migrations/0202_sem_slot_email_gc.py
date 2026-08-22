from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0201_relatorio_esteira_horarios_multiplos'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='sem_slot_email_gc_ativo',
            field=models.BooleanField(
                default=True,
                help_text='Quando a auditoria dispara a máscara Sem SLOT, envia também ao e-mail do GC (com o print em anexo).',
                verbose_name='Enviar Sem SLOT por e-mail do GC',
            ),
        ),
        migrations.AlterField(
            model_name='anteciparinstalacaoconfig',
            name='email_gc',
            field=models.EmailField(
                blank=True,
                default='',
                help_text='Destino dos pedidos de ajuda/socorro (abrir chamado TI) e da máscara Sem SLOT.',
                max_length=254,
                verbose_name='E-mail do GC',
            ),
        ),
        migrations.AddField(
            model_name='auditoriasemslotgc',
            name='enviado_email',
            field=models.BooleanField(default=False, verbose_name='Enviado por e-mail ao GC'),
        ),
    ]
