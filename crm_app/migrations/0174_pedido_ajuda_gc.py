# Generated manually for pedido de ajuda GC

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_etapas_erro(apps, schema_editor):
    Etapa = apps.get_model('crm_app', 'EtapaErroAjudaGc')
    auditoria = [
        ('Etapa 1: Identificação PDV', 1),
        ('Etapa 2: Consulta de viabilidade', 2),
        ('Etapa 3: Cadastro do cliente', 3),
        ('Etapa 4: Contato', 4),
        ('Etapa 5: Pagamento/Ofertas', 5),
        ('Etapa 6: Resumo', 6),
        ('Etapa 7: Abrir OS', 7),
    ]
    esteira = [
        ('Agendamento OCO, agenda e não muda o status', 1),
        ('Pedido instalado e não concluído', 2),
    ]
    for nome, ordem in auditoria:
        Etapa.objects.get_or_create(
            contexto='auditoria',
            nome=nome,
            defaults={'ordem': ordem, 'ativo': True},
        )
    for nome, ordem in esteira:
        Etapa.objects.get_or_create(
            contexto='esteira',
            nome=nome,
            defaults={'ordem': ordem, 'ativo': True},
        )


def unseed_etapas_erro(apps, schema_editor):
    Etapa = apps.get_model('crm_app', 'EtapaErroAjudaGc')
    Etapa.objects.filter(contexto__in=['auditoria', 'esteira']).delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('crm_app', '0173_status_agendamento'),
    ]

    operations = [
        migrations.AddField(
            model_name='anteciparinstalacaoconfig',
            name='email_gc',
            field=models.EmailField(
                blank=True,
                default='',
                help_text='Destino dos pedidos de ajuda/socorro (abrir chamado TI, etc.).',
                max_length=254,
                verbose_name='E-mail do GC',
            ),
        ),
        migrations.CreateModel(
            name='EtapaErroAjudaGc',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contexto', models.CharField(choices=[('auditoria', 'Auditoria'), ('esteira', 'Esteira')], db_index=True, max_length=20)),
                ('nome', models.CharField(max_length=255)),
                ('ordem', models.PositiveSmallIntegerField(default=0)),
                ('ativo', models.BooleanField(db_index=True, default=True)),
            ],
            options={
                'verbose_name': 'Etapa de erro (Ajuda GC)',
                'verbose_name_plural': 'Etapas de erro (Ajuda GC)',
                'db_table': 'crm_etapa_erro_ajuda_gc',
                'ordering': ['contexto', 'ordem', 'nome'],
                'unique_together': {('contexto', 'nome')},
            },
        ),
        migrations.CreateModel(
            name='PedidoAjudaGc',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('abrir_chamado_ti', 'Abrir chamado com TI')], default='abrir_chamado_ti', max_length=40)),
                ('origem', models.CharField(choices=[('auditoria', 'Auditoria'), ('esteira', 'Esteira')], db_index=True, max_length=20)),
                ('nome_gc', models.CharField(blank=True, default='', max_length=100)),
                ('email_gc', models.EmailField(blank=True, default='', max_length=254)),
                ('telefone_gc', models.CharField(blank=True, default='', max_length=20)),
                ('pdv', models.CharField(default='1068561', max_length=20)),
                ('login_bo', models.CharField(blank=True, default='', max_length=100)),
                ('login_vendedor', models.CharField(blank=True, default='', max_length=100)),
                ('cpf_cnpj_cliente', models.CharField(blank=True, default='', max_length=20)),
                ('numero_pedido', models.CharField(blank=True, default='', max_length=50)),
                ('contato', models.CharField(blank=True, default='', max_length=120)),
                ('etapa_erro', models.CharField(blank=True, default='', max_length=255)),
                ('detalhe_cenario', models.TextField(blank=True, default='')),
                ('numero_registro', models.CharField(blank=True, default='', max_length=80)),
                ('evidencia', models.FileField(blank=True, null=True, upload_to='pedido_ajuda_gc/%Y/%m/')),
                ('mensagem_enviada', models.TextField(blank=True, default='')),
                ('enviado_email', models.BooleanField(default=False)),
                ('enviado_whatsapp', models.BooleanField(default=False)),
                ('erros', models.JSONField(blank=True, default=list)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('usuario', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pedidos_ajuda_gc', to=settings.AUTH_USER_MODEL)),
                ('venda', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pedidos_ajuda_gc', to='crm_app.venda')),
            ],
            options={
                'verbose_name': 'Pedido de ajuda GC',
                'verbose_name_plural': 'Pedidos de ajuda GC',
                'db_table': 'crm_pedido_ajuda_gc',
                'ordering': ['-criado_em'],
            },
        ),
        migrations.RunPython(seed_etapas_erro, unseed_etapas_erro),
    ]
