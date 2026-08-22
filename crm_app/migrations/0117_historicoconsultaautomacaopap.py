from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0024_add_brpronto_campos"),
        ("crm_app", "0116_auditoria_ligacao"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricoConsultaAutomacaoPAP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("telefone_solicitante", models.CharField(blank=True, db_index=True, default="", help_text="Telefone usado na sessão da automação (fallback de auditoria).", max_length=100)),
                ("tipo_automacao", models.CharField(blank=True, choices=[("vender", "Vender"), ("credito", "Crédito"), ("pedido", "Pedido"), ("status", "Status")], db_index=True, default="", max_length=20)),
                ("matricula_pap_utilizada", models.CharField(blank=True, default="", help_text="Snapshot da matrícula PAP no momento da alocação.", max_length=80)),
                ("criado_em", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("login_pap_utilizado", models.ForeignKey(blank=True, help_text="Usuário BackOffice cujo login PAP foi alocado para a automação.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="historico_logins_pap_utilizados", to="usuarios.usuario")),
                ("solicitado_por", models.ForeignKey(blank=True, help_text="Usuário que chamou a automação (quando identificado).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="historico_consultas_automacao_pap", to="usuarios.usuario")),
            ],
            options={
                "verbose_name": "Histórico consulta automação PAP",
                "verbose_name_plural": "Histórico consultas automação PAP",
                "db_table": "crm_hist_consulta_automacao_pap",
                "ordering": ["-criado_em"],
            },
        ),
    ]
