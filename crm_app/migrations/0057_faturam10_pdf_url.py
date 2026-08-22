from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm_app", "0056_faturam10_arquivo_pdf_faturam10_codigo_barras_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="faturam10",
            name="pdf_url",
            field=models.URLField(blank=True, max_length=500, null=True, help_text="Link público do PDF da fatura"),
        ),
    ]
