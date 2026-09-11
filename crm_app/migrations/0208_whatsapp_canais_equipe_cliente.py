from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0207_venda_pedido_pap"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappintegracaoconfig",
            name="envios_cliente_ativos",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Só ligar quando o número oficial do plano (Meta Cloud API / WhatsAtende B) "
                    "estiver configurado. O WhatsApp do time comercial nunca envia a clientes."
                ),
                verbose_name="Envios a clientes ativos",
            ),
        ),
        migrations.AddField(
            model_name="whatsappintegracaoconfig",
            name="numero_cliente_label",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                verbose_name="Número oficial Meta / clientes (exibição)",
            ),
        ),
        migrations.AddField(
            model_name="whatsappintegracaoconfig",
            name="numero_equipe_label",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                verbose_name="Número do time comercial (exibição)",
            ),
        ),
    ]
