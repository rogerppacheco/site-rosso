from django.db import migrations, models
import django.db.models.deletion


def seed_status_agendamento(apps, schema_editor):
    StatusAgendamento = apps.get_model('crm_app', 'StatusAgendamento')
    iniciais = [
        ('Não atribuído', 10, '#6c757d'),
        ('Atribuído', 20, '#0d6efd'),
        ('Em Execução', 30, '#fd7e14'),
        ('Agendamento Cancelado', 40, '#dc3545'),
    ]
    for nome, ordem, cor in iniciais:
        StatusAgendamento.objects.get_or_create(
            nome=nome,
            defaults={'ordem': ordem, 'cor': cor, 'ativo': True},
        )


def unseed_status_agendamento(apps, schema_editor):
    StatusAgendamento = apps.get_model('crm_app', 'StatusAgendamento')
    StatusAgendamento.objects.filter(
        nome__in=[
            'Não atribuído',
            'Atribuído',
            'Em Execução',
            'Agendamento Cancelado',
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('crm_app', '0172_demanda_inclusao_viabilidade'),
    ]

    operations = [
        migrations.CreateModel(
            name='StatusAgendamento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100, unique=True)),
                ('ativo', models.BooleanField(db_index=True, default=True)),
                ('ordem', models.PositiveSmallIntegerField(default=0)),
                ('cor', models.CharField(default='#6c757d', max_length=7)),
            ],
            options={
                'verbose_name': 'Status do Agendamento',
                'verbose_name_plural': 'Status do Agendamento',
                'db_table': 'crm_status_agendamento',
                'ordering': ['ordem', 'nome'],
            },
        ),
        migrations.AddField(
            model_name='venda',
            name='status_agendamento',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                help_text='Substatus do agendamento (ex.: Atribuído, Em Execução). Exibido abaixo da O.S. na Esteira.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='vendas',
                to='crm_app.statusagendamento',
                verbose_name='Status do agendamento',
            ),
        ),
        migrations.RunPython(seed_status_agendamento, unseed_status_agendamento),
    ]
