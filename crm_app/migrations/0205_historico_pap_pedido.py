# Generated manually for histÃ³rico PAP (venda / interesse / prÃ©-venda)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm_app", "0204_historico_envio_status_entrega"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricoPapPedido",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero_pedido", models.CharField(db_index=True, max_length=40, unique=True)),
                (
                    "tipo_venda",
                    models.CharField(
                        choices=[
                            ("VENDA", "Venda"),
                            ("INTERESSE", "Interesse"),
                            ("PRE_VENDA", "PrÃ©-venda"),
                        ],
                        db_index=True,
                        default="VENDA",
                        max_length=20,
                    ),
                ),
                ("pdv", models.CharField(blank=True, default="", max_length=20)),
                ("status", models.CharField(blank=True, default="", max_length=80)),
                ("data_criacao_pap", models.DateTimeField(blank=True, null=True)),
                ("origem", models.CharField(default="api", max_length=20)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("capturado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Pedido histÃ³rico PAP",
                "verbose_name_plural": "Pedidos histÃ³rico PAP",
                "db_table": "crm_historico_pap_pedido",
                "ordering": ["-capturado_em"],
            },
        ),
        migrations.CreateModel(
            name="HistoricoPapBusca",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pendente", "Pendente"),
                            ("em_andamento", "Em andamento"),
                            ("concluido", "ConcluÃ­do"),
                            ("erro", "Erro"),
                            ("cancelado", "Cancelado"),
                        ],
                        db_index=True,
                        default="pendente",
                        max_length=20,
                    ),
                ),
                ("data_inicio", models.DateField()),
                ("data_fim", models.DateField()),
                ("pdv", models.CharField(blank=True, default="", max_length=20)),
                ("tipos", models.JSONField(blank=True, default=list)),
                ("encontrados", models.PositiveIntegerField(default=0)),
                ("novos", models.PositiveIntegerField(default=0)),
                ("ignorados", models.PositiveIntegerField(default=0)),
                ("por_tipo", models.JSONField(blank=True, default=dict)),
                ("novos_numeros", models.JSONField(blank=True, default=list)),
                ("mensagem", models.TextField(blank=True, default="")),
                ("relatorio_json", models.JSONField(blank=True, default=dict)),
                ("iniciado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("finalizado_em", models.DateTimeField(blank=True, null=True)),
                (
                    "usuario",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="historico_pap_buscas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Busca histÃ³rico PAP",
                "verbose_name_plural": "Buscas histÃ³rico PAP",
                "db_table": "crm_historico_pap_busca",
                "ordering": ["-iniciado_em"],
            },
        ),
    ]

