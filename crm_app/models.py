# crm_app/models.py

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from usuarios.models import Usuario
from django.conf import settings
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import uuid

class Operadora(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    cnpj = models.CharField(max_length=18, unique=True, null=True, blank=True)
    ativo = models.BooleanField(default=True)

    def __str__(self): return self.nome
    class Meta:
        db_table = 'crm_operadora'
        verbose_name = "Operadora"
        verbose_name_plural = "Operadoras"

class Plano(models.Model):
    nome = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    operadora = models.ForeignKey(Operadora, on_delete=models.CASCADE, related_name='planos')
    beneficios = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    comissao_base = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    gdp_velocidade_mbps = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Velocidade GDP (Mbps)',
        help_text='Velocidade usada na tabela GDP (ex.: 500, 600, 800, 1000). Se vazio, infere pelo nome.',
    )
    gdp_indice_oferta = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='Índice oferta GDP',
        help_text='Quando há mais de uma oferta com a mesma velocidade (ex.: dois planos 1GB), use 0 ou 1.',
    )

    def __str__(self): return f"{self.nome} - {self.operadora.nome}"
    class Meta:
        db_table = 'crm_plano'
        verbose_name = "Plano"
        verbose_name_plural = "Planos"


class PlanoValoresComissao(models.Model):
    """Valores de pagamento de comissão vinculados ao plano (propagação para faixas e vendedores)."""
    BANDA_CHOICES = [
        ('500MB', '500 MB'),
        ('600MB', '600 MB'),
        ('700MB', '700 MB'),
        ('800MB', '800 MB'),
        ('1GB', '1 GB'),
        ('PERSONALIZADO', 'Personalizado'),
    ]
    plano = models.OneToOneField(
        Plano, on_delete=models.CASCADE, related_name='valores_comissao',
    )
    banda_comissao = models.CharField(
        max_length=20, choices=BANDA_CHOICES, default='PERSONALIZADO',
        verbose_name='Banda nas regras de faixa',
    )
    valor_pap = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Comissão PAP (CPF)',
    )
    valor_cnpj = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='Comissão CNPJ',
    )
    usa_comissao_cidade_especial = models.BooleanField(
        default=False,
        verbose_name='Comissão especial em cidade de oferta',
        help_text=(
            'Quando ativo, vendas deste plano em municípios da lista de oferta especial '
            'usam valor fixo (não escala por faixa de volume).'
        ),
    )
    valor_pap_cidade_especial = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Comissão PAP em cidade especial',
    )
    valor_cnpj_cidade_especial = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Comissão CNPJ em cidade especial',
    )
    propagar_faixas = models.BooleanField(
        default=False,
        help_text='Atualiza colunas da banda em Regras por Faixa (COMISSÃO).',
    )
    propagar_vendedores = models.BooleanField(
        default=True,
        help_text='Cria/atualiza vínculo por plano em cada config de vendedor.',
    )

    class Meta:
        db_table = 'crm_plano_valores_comissao'
        verbose_name = 'Valores de comissão do plano'
        verbose_name_plural = 'Valores de comissão dos planos'

    def __str__(self) -> str:
        return f'Comissão {self.plano.nome}'


class CidadeOfertaEspecial(models.Model):
    """Municípios com oferta especial (ex.: 600Mb 50% off) e comissão diferenciada."""

    uf = models.CharField(max_length=2, db_index=True)
    municipio = models.CharField(max_length=120)
    municipio_normalizado = models.CharField(max_length=120, db_index=True)
    ativo = models.BooleanField(default=True, db_index=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_cidade_oferta_especial'
        verbose_name = 'Cidade de oferta especial'
        verbose_name_plural = 'Cidades de oferta especial'
        ordering = ['uf', 'municipio']
        constraints = [
            models.UniqueConstraint(
                fields=['uf', 'municipio_normalizado'],
                name='uniq_cidade_oferta_especial_uf_municipio',
            ),
        ]
        indexes = [
            models.Index(fields=['municipio_normalizado', 'uf', 'ativo']),
        ]

    def __str__(self) -> str:
        return f'{self.municipio}/{self.uf}'

    def save(self, *args, **kwargs) -> None:
        from crm_app.services.gdp_preco_service import normalizar_municipio

        self.uf = (self.uf or '').strip().upper()[:2]
        self.municipio = (self.municipio or '').strip()
        self.municipio_normalizado = normalizar_municipio(self.municipio)
        super().save(*args, **kwargs)


class FormaPagamento(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True)
    aplica_desconto = models.BooleanField(default=False, help_text="Aplica desconto de boleto?")
    def __str__(self): return self.nome
    class Meta:
        db_table = 'crm_forma_pagamento'
        verbose_name = "Forma de Pagamento"
        verbose_name_plural = "Formas de Pagamento"

class StatusCRM(models.Model):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(
        max_length=50,
        choices=[
            ('Tratamento', 'Tratamento'),
            ('Esteira', 'Esteira'),
            ('Comissionamento', 'Comissionamento'),
            ('Qualidade', 'Qualidade'),
        ],
    )
    estado = models.CharField(max_length=50, blank=True, null=True)
    cor = models.CharField(max_length=7, default="#FFFFFF")

    def __str__(self): return f"{self.nome} ({self.tipo})"
    class Meta:
        db_table = 'crm_status'
        verbose_name = "Status de CRM"
        verbose_name_plural = "Status de CRM"
        unique_together = ('nome', 'tipo')

class MotivoPendencia(models.Model):
    nome = models.CharField(max_length=255)
    tipo_pendencia = models.CharField(max_length=100)
    def __str__(self): return self.nome
    class Meta:
        db_table = 'crm_motivo_pendencia'
        verbose_name = "Motivo de Pendência"
        verbose_name_plural = "Motivos de Pendência"
        ordering = ['nome']


class StatusAgendamento(models.Model):
    """Catálogo editável do substatus do agendamento (abaixo da O.S. na Esteira).

    Independente de StatusCRM (pipeline: AGENDADO, INSTALADA…): descreve o
    andamento do agendamento no dia (ex.: Atribuído, Em Execução).
    """
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True, db_index=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    cor = models.CharField(max_length=7, default='#6c757d')

    def __str__(self) -> str:
        return self.nome

    class Meta:
        db_table = 'crm_status_agendamento'
        verbose_name = "Status do Agendamento"
        verbose_name_plural = "Status do Agendamento"
        ordering = ['ordem', 'nome']


class RegraComissao(models.Model):
    TIPO_VENDA_CHOICES = [('PAP', 'PAP'), ('TELAG', 'TELAG')]
    TIPO_CLIENTE_CHOICES = [('CPF', 'CPF'), ('CNPJ', 'CNPJ')]
    consultor = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='regras_comissao')
    plano = models.ForeignKey(Plano, on_delete=models.CASCADE, related_name='regras_comissao')
    tipo_venda = models.CharField(max_length=5, choices=TIPO_VENDA_CHOICES)
    tipo_cliente = models.CharField(max_length=4, choices=TIPO_CLIENTE_CHOICES)
    valor_base = models.DecimalField(max_digits=10, decimal_places=2)
    valor_acelerado = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self): return f"Regra {self.consultor} - {self.plano}"
    class Meta:
        db_table = 'crm_regra_comissao'
        verbose_name = "Regra de Comissão"
        verbose_name_plural = "Regras de Comissão"
        unique_together = ('consultor', 'plano', 'tipo_venda', 'tipo_cliente')

class Cliente(models.Model):
    CLASSIFICACAO_MEI_CHOICES = [
        ('MEI', 'MEI'),
        ('NMEI', 'NMEI'),
    ]

    nome_razao_social = models.CharField(max_length=255)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    email = models.EmailField(max_length=255, blank=True, null=True)
    classificacao_mei = models.CharField(
        max_length=20,
        choices=CLASSIFICACAO_MEI_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='Classificação MEI',
        help_text='MEI, NMEI (não MEI), INDETERMINADO ou CPF.',
    )
    classificacao_mei_consultada_em = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='Classificação MEI consultada em',
    )

    def __str__(self): return self.nome_razao_social
    class Meta:
        db_table = 'crm_cliente'
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

class Venda(models.Model):
    reemissao = models.BooleanField(default=False, verbose_name="Reemissão")
    ativo = models.BooleanField(default=True, verbose_name="Venda Ativa")
    vendedor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name='vendas', db_index=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='vendas')
    
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT, null=True, blank=True)
    forma_pagamento = models.ForeignKey(FormaPagamento, on_delete=models.PROTECT, null=True, blank=True)

    status_tratamento = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_tratamento', limit_choices_to={'tipo': 'Tratamento'}, db_index=True)
    status_esteira = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_esteira', limit_choices_to={'tipo': 'Esteira'}, db_index=True)
    
    status_comissionamento = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_comissionamento', limit_choices_to={'tipo': 'Comissionamento'}, db_index=True)

    data_criacao = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # --- NOVOS CAMPOS PARA RASTREIO DE EDIÇÃO ---
    editado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendas_editadas',
        verbose_name="Última alteração por"
    )
    data_ultima_alteracao = models.DateTimeField(auto_now=True, verbose_name="Data da Última Alteração")
    # --------------------------------------------

    forma_entrada = models.CharField(max_length=10, choices=[('APP', 'APP'), ('SEM_APP', 'SEM_APP')], default='APP')
    tem_fixo = models.BooleanField(default=False, verbose_name="Tem Fixo")
    # Débito em conta (DACC)
    banco_dacc = models.CharField(max_length=100, blank=True, null=True, verbose_name="Banco DACC")
    agencia_dacc = models.CharField(max_length=20, blank=True, null=True, verbose_name="Agência DACC")
    conta_dacc = models.CharField(max_length=20, blank=True, null=True, verbose_name="Conta DACC")
    digito_dacc = models.CharField(max_length=5, blank=True, null=True, verbose_name="Dígito DACC")
    
    nome_mae = models.CharField(max_length=255, blank=True, null=True)
    data_nascimento = models.DateField(blank=True, null=True)
    mes_nascimento_pap = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name="Mês nascimento (PAP)",
        help_text="Mês (1–12) quando o portal PAP só revela **/MM/**** na data de nascimento.",
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    cpf_representante_legal = models.CharField(max_length=14, blank=True, null=True)
    nome_representante_legal = models.CharField(max_length=255, blank=True, null=True)
    
    telefone1 = models.CharField(max_length=20, blank=True, null=True)
    telefone2 = models.CharField(max_length=20, blank=True, null=True)
    
    cep = models.CharField(max_length=9, blank=True, null=True)
    logradouro = models.CharField(max_length=255, blank=True, null=True)
    numero_residencia = models.CharField(max_length=20, blank=True, null=True)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=2, blank=True, null=True)
    ponto_referencia = models.CharField(max_length=255, blank=True, null=True)
    
    observacoes = models.TextField(blank=True, null=True)

    ordem_servico = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    data_abertura = models.DateTimeField(null=True, blank=True, verbose_name="Data de Abertura da O.S")
    data_pedido = models.DateTimeField(null=True, blank=True)
    data_agendamento = models.DateField(null=True, blank=True)
    periodo_agendamento = models.CharField(max_length=10, choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')], null=True, blank=True)
    data_instalacao = models.DateField(null=True, blank=True, db_index=True)
    data_instalacao_fisica = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Data instalação (no cliente)",
        help_text="Data em que a instalação ocorreu de fato no cliente. Usada em performance/dashboard para consultores. Editável apenas por BackOffice/Diretoria/Admin.",
    )
    antecipou_instalacao = models.BooleanField(default=False)
    antecipacao_comissao = models.BooleanField(
        default=False,
        verbose_name="Antecipação de comissão",
        help_text="Indica se a comissão desta venda foi antecipada (informação administrativa).",
    )
    motivo_pendencia = models.ForeignKey(MotivoPendencia, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_pendentes', db_index=True)
    status_agendamento = models.ForeignKey(
        StatusAgendamento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendas',
        db_index=True,
        verbose_name="Status do agendamento",
        help_text="Substatus do agendamento (ex.: Atribuído, Em Execução). Exibido abaixo da O.S. na Esteira.",
    )
    pap_status_consultado_em = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Consulta PAP (data/hora)",
        help_text="Última consulta de status no PAP (Esteira). Exibido na coluna Status Atual.",
    )
    pap_status_consultado_matricula = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name="Consulta PAP (matrícula)",
        help_text="Matrícula PAP usada na última consulta de status na Esteira.",
    )
    pap_status_consulta_erro = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name="Consulta PAP (erro)",
        help_text="Último erro da consulta STATUS PAP na Esteira (vazio = sucesso).",
    )
    nio_reagendamento_status = models.CharField(
        max_length=32,
        blank=True,
        default='',
        db_index=True,
        verbose_name="Reagendamento Nio (status)",
        help_text="Último resultado da automação WhatsApp Nio (7029).",
    )
    nio_reagendamento_em = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Reagendamento Nio (data/hora)",
    )
    nio_reagendamento_msg = models.CharField(
        max_length=500,
        blank=True,
        default='',
        verbose_name="Reagendamento Nio (mensagem)",
    )

    inclusao = models.BooleanField(default=False, verbose_name="Inclusão/Viabilidade")
    data_pagamento_comissao = models.DateField(null=True, blank=True, verbose_name="Data Pagamento Comissão")
    
    data_pagamento = models.DateField(null=True, blank=True) 
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    auditor_atual = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='vendas_em_auditoria',
        verbose_name="Em Auditoria Por",
        db_index=True
    )

    gerada_os_automatica = models.BooleanField(
        default=False,
        verbose_name="Gerada O.S. automática",
        help_text="Se a venda foi gerada com O.S. automática (vendedor já abriu o pedido)."
    )
    bloquear_atualizacao_status_osab = models.BooleanField(
        default=False,
        verbose_name="Bloquear atualização de status pela OSAB",
        help_text=(
            "Quando marcado, a importação OSAB não atualiza este pedido "
            "(exceto para INSTALADA, CANCELADA, INSTALADA OUTRO PDV e NÃO CONSTA NA OSAB)."
        ),
    )

    # --- Biometria Br Pronto (consulta na auditoria / WhatsApp) ---
    biometria_aprovada = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        db_index=True,
        verbose_name="Biometria aprovada",
        help_text=(
            "True=Doc. Apto para Venda no Br Pronto; False=consultada sem aprovação; "
            "null=ainda não consultada."
        ),
    )
    biometria_consultada_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora consulta biometria",
    )
    biometria_data_apta = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Data biometria apta",
        help_text="Data do Doc. Apto mais recente retornada pelo Br Pronto.",
    )

    # --- Retorno auditoria: confirmação do cliente (resumo enviado ao celular) ---
    cliente_confirmou_auditoria = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name="Cliente confirmou resumo (auditoria)",
        help_text="True se o cliente respondeu SIM/CONFIRMAR ao resumo enviado; False se BO marcou que não confirmou; null se ainda não definido.",
    )
    protocolo_confirmacao_auditoria = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Protocolo confirmação cliente (auditoria)",
        help_text="Formato AAAAMMDDHHMM + ID da venda (ex.: 2026022621403383). Gerado quando o cliente confirma pelo WhatsApp.",
    )
    data_confirmacao_auditoria = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora confirmação cliente (auditoria)",
    )

    # --- Confirmação/resposta ao lembrete de instalação (esteira, WhatsApp) ---
    cliente_confirmou_lembrete_instalacao = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name="Cliente confirmou instalação (lembrete)",
        help_text="True=respondeu SIM/positivo; False=respondeu Não/Suporte/outro; null=ainda não respondeu ao lembrete.",
    )
    cliente_resposta_lembrete_instalacao = models.TextField(
        blank=True,
        null=True,
        verbose_name="Resposta do cliente ao lembrete",
        help_text="Texto que o cliente enviou ao responder o lembrete de instalação.",
    )
    data_resposta_lembrete_instalacao = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora resposta ao lembrete",
    )

    # --- Posso antecipar? (consulta ao vendedor via WhatsApp, esteira) ---
    vendedor_pode_antecipar = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name="Vendedor pode antecipar?",
        help_text="True=Sim; False=Não; null=ainda não respondeu ou resposta não identificada.",
    )
    vendedor_pode_antecipar_turno = models.CharField(
        max_length=10,
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
        null=True,
        blank=True,
        verbose_name="Turno antecipação (vendedor)",
    )
    vendedor_resposta_posso_antecipar = models.TextField(
        blank=True,
        null=True,
        verbose_name="Resposta vendedor (posso antecipar)",
        help_text="Texto completo recebido do vendedor.",
    )
    vendedor_obs_posso_antecipar = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observação vendedor (posso antecipar)",
        help_text="Texto extra além de Sim/Não e turno.",
    )
    data_solicitacao_posso_antecipar = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora solicitação posso antecipar",
    )
    data_resposta_posso_antecipar = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora resposta posso antecipar",
    )

    # --- Posso reagendar? (consulta ao consultor/vendedor — pendência na esteira) ---
    consultor_pode_reagendar = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        verbose_name="Consultor pode reagendar?",
        help_text="True=Sim reagendar; False=Não; null=sem resposta.",
    )
    consultor_reagendar_data = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data sugerida reagendamento (consultor)",
    )
    consultor_reagendar_turno = models.CharField(
        max_length=10,
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
        null=True,
        blank=True,
        verbose_name="Turno sugerido reagendamento (consultor)",
    )
    consultor_reagendar_resposta = models.TextField(
        blank=True,
        null=True,
        verbose_name="Resposta consultor (posso reagendar)",
        help_text="Resumo da consulta posso reagendar.",
    )
    data_solicitacao_reagendar_consultor = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora solicitação reagendar consultor",
    )
    data_resposta_reagendar_consultor = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora resposta reagendar consultor",
    )

    # --- Lista diária de agendamentos (ciência / pedido de reagendar via WhatsApp) ---
    STATUS_LISTA_AGENDAMENTO_CIENTE = 'CIENTE'
    STATUS_LISTA_AGENDAMENTO_REAGENDAR = 'REAGENDAR'
    STATUS_LISTA_AGENDAMENTO_CHOICES = [
        (STATUS_LISTA_AGENDAMENTO_CIENTE, 'Estou ciente'),
        (STATUS_LISTA_AGENDAMENTO_REAGENDAR, 'Solicitou reagendar'),
    ]
    vendedor_lista_agendamento_status = models.CharField(
        max_length=16,
        choices=STATUS_LISTA_AGENDAMENTO_CHOICES,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Status resposta lista agendamento",
        help_text="Resposta do vendedor à lista diária (não altera o agendamento do CRM).",
    )
    vendedor_lista_reagendar_data = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data sugerida (lista agendamento)",
    )
    vendedor_lista_reagendar_turno = models.CharField(
        max_length=10,
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
        null=True,
        blank=True,
        verbose_name="Turno sugerido (lista agendamento)",
    )
    vendedor_lista_agendamento_resposta = models.TextField(
        blank=True,
        null=True,
        verbose_name="Resumo resposta lista agendamento",
    )
    data_envio_lista_agendamento = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora envio lista agendamento",
    )
    data_resposta_lista_agendamento = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora resposta lista agendamento",
    )

    # --- Boas-vindas (mensagem pós-instalação) ---
    boas_vindas_enviado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Boas-vindas enviado em",
        help_text="Quando a mensagem de boas-vindas foi enviada ao cliente.",
    )
    cliente_resposta_boas_vindas = models.TextField(
        blank=True,
        null=True,
        verbose_name="Resposta do cliente (boas-vindas)",
        help_text="Texto que o cliente enviou ao responder a mensagem de boas-vindas.",
    )
    data_resposta_boas_vindas = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/hora resposta boas-vindas",
    )

    classificacao_mei = models.CharField(
        max_length=20,
        choices=Cliente.CLASSIFICACAO_MEI_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='Classificação MEI na venda',
        help_text='Snapshot MEI/NMEI no momento do cadastro da venda.',
    )

    # --- CAMPOS PARA CONTROLE DE DESCONTOS ---
    flag_adiant_cnpj = models.BooleanField(default=False, verbose_name="Adiant. CNPJ Processado")
    adiantamento_cnpj_realizado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Adiantamento CNPJ realizado em"
    )
    adiantamento_cnpj_realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendas_adiantamento_cnpj_realizado',
        verbose_name="Adiantamento CNPJ realizado por"
    )
    flag_desc_boleto = models.BooleanField(default=False, verbose_name="Desc. Boleto Processado")
    flag_desc_viabilidade = models.BooleanField(default=False, verbose_name="Desc. Viab. Processado")
    flag_desc_antecipacao = models.BooleanField(default=False, verbose_name="Desc. Antecip. Processado")
    # --- Adiantamento sábado (esteira Agendados): valor pela Finalidade Adiantamento em REGRAS_FAIXAS ---
    adiantamento_sabado_marcado = models.BooleanField(
        default=False,
        verbose_name="Adiantamento sábado marcado",
        help_text="Comissão antecipada na aba Agendados (O.S. aberta em sábado, conforme regra).",
    )
    adiantamento_sabado_valor = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Valor adiantamento sábado (snapshot)",
    )
    adiantamento_sabado_valor_pago = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name="Valor pago adiantamento sábado",
        help_text="Valor efetivamente pago no sábado; base para complemento na folha.",
    )
    adiantamento_sabado_marcado_em = models.DateTimeField(null=True, blank=True, verbose_name="Adiant. sábado marcado em")
    adiantamento_sabado_marcado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendas_adiantamento_sabado_marcado",
        verbose_name="Adiant. sábado marcado por",
    )
    adiantamento_sabado_manual = models.BooleanField(
        default=False,
        verbose_name="Adiant. sábado (marcação manual)",
    )
    adiantamento_sabado_obs_manual = models.CharField(
        max_length=500, blank=True, default="",
        verbose_name="Observação (marcação manual)",
    )
    adiantamento_sabado_quitado_em = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Adiant. sábado quitado na instalação em",
        help_text="Preenchido ao instalar para não gerar segundo pagamento de adiantamento.",
    )
    flag_desc_adiantamento_sabado = models.BooleanField(
        default=False,
        verbose_name="Desc. adiant. sábado processado",
        help_text="Desconto na folha (cancelamento ou estorno) já aplicado.",
    )
    # Ano/mês em que o desconto por churn foi aplicado (ex: 202601 = comissão jan/26). Evita descontar duas vezes.
    desconto_churn_aplicado_em = models.PositiveIntegerField(null=True, blank=True, verbose_name="Desconto Churn aplicado em (AAAAMM)")
    # ------------------------------------------

    def __str__(self): return f"Venda #{self.id}"
    class Meta:
        db_table = 'crm_venda'
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"
        permissions = [
            ("pode_reverter_status", "Pode reverter o status"),
            ("can_view_auditoria", "Pode visualizar auditoria"),
            ("can_view_esteira", "Pode visualizar esteira"),
            ("can_view_comissao_dashboard", "Pode visualizar card de comissão"), 
        ]


class PendenciaClienteMsgEnviada(models.Model):
    """Registro de WhatsApp enviado ao cliente ao marcar pendência tipo CLIENTE na esteira."""
    venda = models.ForeignKey(
        Venda, on_delete=models.CASCADE, related_name='msgs_pendencia_cliente_enviadas',
    )
    motivo_pendencia = models.ForeignKey(
        MotivoPendencia, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='msgs_cliente_enviadas',
    )
    telefone = models.CharField(max_length=20)
    mensagem = models.TextField()
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='msgs_pendencia_cliente_registradas',
    )
    sucesso = models.BooleanField(default=False)
    erro = models.CharField(max_length=500, blank=True, default='')
    enviado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'crm_pendencia_cliente_msg_enviada'
        verbose_name = 'Msg pendência cliente (enviada)'
        verbose_name_plural = 'Msgs pendência cliente (enviadas)'
        ordering = ['-enviado_em']
        indexes = [
            models.Index(fields=['venda', 'motivo_pendencia', 'sucesso']),
        ]


class LembreteInstalacaoEnviado(models.Model):
    """Registro de envio do lembrete de instalação (esteira) para respostas automáticas SIM/NÃO/SUPORTE."""
    telefone = models.CharField(max_length=20, db_index=True, help_text="Telefone normalizado (apenas dígitos)")
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='lembretes_instalacao_enviados')
    data_envio = models.DateTimeField(auto_now_add=True)
    data_agendamento = models.DateField()
    periodo_agendamento = models.CharField(max_length=10, choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')])
    respondido_em = models.DateTimeField(null=True, blank=True, help_text="Quando o cliente respondeu (SIM/NÃO/SUPORTE)")

    class Meta:
        db_table = 'crm_lembrete_instalacao_enviado'
        verbose_name = "Lembrete instalação enviado"
        verbose_name_plural = "Lembretes instalação enviados"
        ordering = ['-data_envio']


class PossoAnteciparVendedorEnviado(models.Model):
    """Registro de envio da consulta 'Posso antecipar?' ao vendedor (esteira)."""
    telefone = models.CharField(max_length=20, db_index=True, help_text="WhatsApp do vendedor (dígitos normalizados)")
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='posso_antecipar_enviados')
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posso_antecipar_enviados',
    )
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posso_antecipar_solicitados',
    )
    data_envio = models.DateTimeField(auto_now_add=True)
    respondido_em = models.DateTimeField(null=True, blank=True)
    whatsapp_message_id = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text='messageId Z-API da mensagem com botões (para identificar clique no reenvio).',
    )

    class Meta:
        db_table = 'crm_posso_antecipar_vendedor_enviado'
        verbose_name = "Posso antecipar enviado ao vendedor"
        verbose_name_plural = "Posso antecipar enviados ao vendedor"
        ordering = ['-data_envio']


class PossoReagendarConsultorSessao(models.Model):
    """Fluxo WhatsApp 'Posso agendar novamente?' com o consultor (vendedor) — esteira pendente."""
    ETAPA_SIM_NAO = 'SIM_NAO'
    ETAPA_DATA = 'DATA'
    ETAPA_TURNO = 'TURNO'
    ETAPA_CONCLUIDO = 'CONCLUIDO'
    ETAPA_RECUSADO = 'RECUSADO'
    ETAPA_CHOICES = [
        (ETAPA_SIM_NAO, 'Aguardando Sim/Não'),
        (ETAPA_DATA, 'Aguardando data'),
        (ETAPA_TURNO, 'Aguardando turno'),
        (ETAPA_CONCLUIDO, 'Concluído'),
        (ETAPA_RECUSADO, 'Recusado'),
    ]

    telefone = models.CharField(max_length=20, db_index=True, help_text="WhatsApp do consultor/vendedor")
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='reagendar_consultor_sessoes')
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reagendar_consultor_sessoes',
    )
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reagendar_consultor_solicitados',
    )
    etapa = models.CharField(max_length=16, choices=ETAPA_CHOICES, default=ETAPA_SIM_NAO, db_index=True)
    whatsapp_message_id = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text="messageId Z-API da última mensagem com botões.",
    )
    datas_opcoes_json = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text="JSON com 3 datas ISO oferecidas ao consultor.",
    )
    data_escolhida = models.DateField(null=True, blank=True)
    periodo_escolhido = models.CharField(
        max_length=10,
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
        null=True,
        blank=True,
    )
    pode_reagendar = models.BooleanField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_posso_reagendar_consultor_sessao'
        verbose_name = "Sessão posso reagendar consultor"
        verbose_name_plural = "Sessões posso reagendar consultor"
        ordering = ['-criado_em']


class ListaAgendamentoVendedorEnviado(models.Model):
    """Log de envio da lista diária de agendamentos ao vendedor (imagem + botões)."""
    telefone = models.CharField(max_length=20, db_index=True, help_text="WhatsApp do vendedor (dígitos)")
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lista_agendamento_enviados',
    )
    data_referencia = models.DateField(db_index=True, help_text="Dia dos agendamentos listados")
    periodo = models.CharField(
        max_length=10,
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
        db_index=True,
    )
    venda_ids_json = models.TextField(
        blank=True,
        default='[]',
        help_text="JSON com IDs das vendas incluídas no envio.",
    )
    whatsapp_message_id = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text="messageId Z-API da mensagem com botões iniciais.",
    )
    data_envio = models.DateTimeField(auto_now_add=True)
    respondido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_lista_agendamento_vendedor_enviado'
        verbose_name = "Lista agendamento enviada ao vendedor"
        verbose_name_plural = "Listas agendamento enviadas ao vendedor"
        ordering = ['-data_envio']
        indexes = [
            models.Index(fields=['data_referencia', 'periodo', 'vendedor']),
        ]


class ListaAgendamentoVendedorSessao(models.Model):
    """Fluxo WhatsApp da lista diária: ciência ou reagendar (pedido → data → turno)."""
    ETAPA_INICIAL = 'INICIAL'
    ETAPA_ESCOLHER_PEDIDO = 'PEDIDO'
    ETAPA_DATA = 'DATA'
    ETAPA_TURNO = 'TURNO'
    ETAPA_CIENTE = 'CIENTE'
    ETAPA_CONCLUIDO = 'CONCLUIDO'
    ETAPA_CHOICES = [
        (ETAPA_INICIAL, 'Aguardando ciência/reagendar'),
        (ETAPA_ESCOLHER_PEDIDO, 'Escolhendo pedido'),
        (ETAPA_DATA, 'Aguardando data'),
        (ETAPA_TURNO, 'Aguardando turno'),
        (ETAPA_CIENTE, 'Ciente'),
        (ETAPA_CONCLUIDO, 'Reagendar solicitado'),
    ]

    envio = models.ForeignKey(
        ListaAgendamentoVendedorEnviado,
        on_delete=models.CASCADE,
        related_name='sessoes',
    )
    telefone = models.CharField(max_length=20, db_index=True)
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lista_agendamento_sessoes',
    )
    etapa = models.CharField(max_length=16, choices=ETAPA_CHOICES, default=ETAPA_INICIAL, db_index=True)
    offset_pedidos = models.PositiveIntegerField(default=0, help_text="Página atual na escolha de pedidos.")
    whatsapp_message_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    venda_escolhida = models.ForeignKey(
        Venda,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lista_agendamento_sessoes',
    )
    data_escolhida = models.DateField(null=True, blank=True)
    periodo_escolhido = models.CharField(
        max_length=10,
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')],
        null=True,
        blank=True,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_lista_agendamento_vendedor_sessao'
        verbose_name = "Sessão lista agendamento vendedor"
        verbose_name_plural = "Sessões lista agendamento vendedor"
        ordering = ['-criado_em']


class StatusBoasVindas(models.Model):
    """Status atribuível pelo BO às respostas dos clientes às boas-vindas."""
    codigo = models.CharField(max_length=30, unique=True)
    nome = models.CharField(max_length=100)
    cor = models.CharField(max_length=7, default='#6c757d')
    ordem = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.nome

    class Meta:
        db_table = 'crm_status_boas_vindas'
        verbose_name = "Status Boas-Vindas"
        verbose_name_plural = "Status Boas-Vindas"
        ordering = ['ordem', 'nome']


class BoasVindasEnviado(models.Model):
    """Registro de envio da mensagem de boas-vindas (pós-instalação) para gravar resposta do cliente."""
    telefone = models.CharField(max_length=20, db_index=True, help_text="Telefone normalizado (apenas dígitos)")
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='boas_vindas_enviados')
    data_envio = models.DateTimeField(auto_now_add=True)
    respondido_em = models.DateTimeField(null=True, blank=True, help_text="Quando o cliente respondeu")
    # Campos para gestão (BO)
    status_boas_vindas = models.ForeignKey(
        StatusBoasVindas, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='envios', verbose_name="Status (BO)"
    )
    status_definido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='boas_vindas_status_definidos', verbose_name="Status definido por"
    )
    status_definido_em = models.DateTimeField(null=True, blank=True, verbose_name="Status definido em")
    sugestao_status_ia = models.CharField(
        max_length=30, null=True, blank=True, verbose_name="Sugestão de status pela IA"
    )

    class Meta:
        db_table = 'crm_boas_vindas_enviado'
        verbose_name = "Boas-vindas enviado"
        verbose_name_plural = "Boas-vindas enviados"
        ordering = ['-data_envio']


class MensagemClienteBoasVindas(models.Model):
    """Cada mensagem enviada pelo cliente no chat daquele número que recebeu boas-vindas."""
    DIRECAO_CHOICES = [('ENTRADA', 'Cliente'), ('SAIDA', 'Sistema')]
    boas_vindas_enviado = models.ForeignKey(
        BoasVindasEnviado, on_delete=models.CASCADE, related_name='mensagens'
    )
    texto = models.TextField(help_text="Mensagem original do cliente")
    data_hora = models.DateTimeField(auto_now_add=True)
    direcao = models.CharField(max_length=10, choices=DIRECAO_CHOICES, default='ENTRADA')

    class Meta:
        db_table = 'crm_mensagem_cliente_boas_vindas'
        verbose_name = "Mensagem Cliente (Boas-Vindas)"
        verbose_name_plural = "Mensagens Cliente (Boas-Vindas)"
        ordering = ['data_hora']


class HistoricoAtendimentoIACliente(models.Model):
    """Histórico de interações do atendimento automático (IA/templates) com clientes via WhatsApp."""

    ORIGEM_CHOICES = [
        ('WEBHOOK', 'WhatsApp (contato externo)'),
        ('BOAS_VINDAS', 'Boas-vindas'),
        ('LEMBRETE_INSTALACAO', 'Lembrete instalação'),
        ('PENDENCIA_CLIENTE', 'Pendência cliente (esteira)'),
    ]
    INTENCAO_CHOICES = [
        ('AGENDAMENTO', 'Agendamento'),
        ('INSTALACAO', 'Instalação'),
        ('STATUS', 'Status do pedido'),
        ('OS', 'Ordem de serviço'),
        ('HUMANO', 'Escalonar humano'),
        ('OUTROS', 'Outros'),
    ]
    FONTE_RESPOSTA_CHOICES = [
        ('TEMPLATE', 'Template (dados do pedido)'),
        ('IA', 'IA (Groq/Gemini)'),
        ('FALLBACK', 'Fallback padrão'),
    ]

    venda = models.ForeignKey(
        Venda,
        on_delete=models.CASCADE,
        related_name='historico_atendimento_ia_cliente',
    )
    telefone = models.CharField(
        max_length=20,
        db_index=True,
        help_text="Telefone do cliente normalizado (apenas dígitos)",
    )
    mensagem_cliente = models.TextField(verbose_name="Mensagem do cliente")
    resposta_sistema = models.TextField(verbose_name="Resposta enviada")
    intencao = models.CharField(
        max_length=20,
        choices=INTENCAO_CHOICES,
        default='OUTROS',
        db_index=True,
    )
    fonte_resposta = models.CharField(
        max_length=20,
        choices=FONTE_RESPOSTA_CHOICES,
        default='TEMPLATE',
    )
    origem = models.CharField(
        max_length=30,
        choices=ORIGEM_CHOICES,
        default='WEBHOOK',
        db_index=True,
    )
    avisos_bo_enviados = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Avisos enviados (BO/Diretoria)",
        help_text="Quantidade de destinos WhatsApp notificados nesta interação.",
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'crm_historico_atendimento_ia_cliente'
        verbose_name = "Histórico atendimento IA (cliente)"
        verbose_name_plural = "Históricos atendimento IA (cliente)"
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['venda', '-criado_em']),
            models.Index(fields=['telefone', '-criado_em']),
        ]

    def __str__(self):
        return f"Venda #{self.venda_id} — {self.get_intencao_display()} ({self.criado_em:%d/%m/%Y %H:%M})"


class FilaEnvioBoasVindas(models.Model):
    """Fila de envio automático de boas-vindas. O scheduler processa a cada 5 min."""
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name='fila_boas_vindas')
    data_instalacao = models.DateField(help_text="Data das instalações que originaram esta fila")
    agendado_para = models.DateTimeField(db_index=True, help_text="Horário previsto para envio (8h-16h)")
    enviado_em = models.DateTimeField(null=True, blank=True, help_text="Quando foi enviado")
    erro = models.TextField(null=True, blank=True, help_text="Mensagem de erro se falhou")
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='filas_boas_vindas_criadas'
    )

    class Meta:
        db_table = 'crm_fila_envio_boas_vindas'
        verbose_name = "Fila envio boas-vindas"
        verbose_name_plural = "Filas envio boas-vindas"
        ordering = ['agendado_para']


class WhatsAppTarifaOficial(models.Model):
    """Singleton (pk=1): tarifas BRL por categoria para estimativa de custo Número B."""
    utility_brl = models.DecimalField(max_digits=10, decimal_places=4, default=0.0350)
    marketing_brl = models.DecimalField(max_digits=10, decimal_places=4, default=0.3217)
    authentication_brl = models.DecimalField(max_digits=10, decimal_places=4, default=0.0350)
    service_brl = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    observacao = models.TextField(blank=True, default='')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_whatsapp_tarifa_oficial'
        verbose_name = 'Tarifa WhatsApp oficial'
        verbose_name_plural = 'Tarifas WhatsApp oficial'

    def __str__(self) -> str:
        return f'Tarifas WA oficial (utility={self.utility_brl})'


class HistoricoCustoWhatsAppOficial(models.Model):
    """Log de envios do Número B com custo estimado por mensagem."""
    telefone = models.CharField(max_length=30, db_index=True)
    tipo_envio = models.CharField(max_length=20, db_index=True)
    template_name = models.CharField(max_length=120, blank=True, default='')
    categoria = models.CharField(max_length=30, db_index=True)
    custo_estimado_brl = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    sucesso = models.BooleanField(default=True, db_index=True)
    message_id = models.CharField(max_length=120, blank=True, default='')
    origem = models.CharField(max_length=60, blank=True, default='')
    erro = models.TextField(blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'crm_historico_custo_whatsapp_oficial'
        verbose_name = 'Histórico custo WhatsApp oficial'
        verbose_name_plural = 'Históricos custo WhatsApp oficial'
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['criado_em', 'sucesso']),
            models.Index(fields=['categoria', 'criado_em']),
        ]

    def __str__(self) -> str:
        return (
            f'{self.tipo_envio} {self.categoria} R${self.custo_estimado_brl} '
            f'({self.criado_em:%d/%m/%Y %H:%M})'
        )


class PagamentoComissao(models.Model):
    referencia_ano = models.IntegerField()
    referencia_mes = models.IntegerField()
    data_fechamento = models.DateTimeField(auto_now_add=True)
    total_pago_consultores = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    total_recebido_ciclo = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    observacoes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'crm_pagamento_comissao'
        unique_together = ('referencia_ano', 'referencia_mes')
        ordering = ['-referencia_ano', '-referencia_mes']


class PagamentoComissaoItem(models.Model):
    pagamento = models.ForeignKey(
        PagamentoComissao,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pagamentos_comissao_itens',
    )
    valor_pago = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    valor_recebido_ciclo = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    enviado_whatsapp_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_pagamento_comissao_item'
        unique_together = ('pagamento', 'vendedor')

class ImportacaoOsab(models.Model):
    produto = models.CharField(max_length=255, null=True, blank=True)
    filial = models.CharField(max_length=255, null=True, blank=True)
    uf = models.CharField(max_length=2, null=True, blank=True)
    dt_ref = models.DateField(null=True, blank=True)
    documento = models.CharField(max_length=255, null=True, blank=True, db_index=True) 
    segmento = models.CharField(max_length=255, null=True, blank=True)
    localidade = models.CharField(max_length=255, null=True, blank=True)
    estacao = models.CharField(max_length=255, null=True, blank=True)
    id_bundle = models.CharField(max_length=255, null=True, blank=True)
    telefone = models.CharField(max_length=255, null=True, blank=True)
    cliente = models.CharField(max_length=255, null=True, blank=True)
    velocidade = models.CharField(max_length=255, null=True, blank=True)
    matricula_vendedor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Matrícula do Vendedor")
    classe_produto = models.CharField(max_length=255, null=True, blank=True)
    nome_canal = models.CharField(max_length=255, null=True, blank=True) 
    pdv_sap = models.CharField(max_length=255, null=True, blank=True)
    descricao = models.CharField(max_length=255, null=True, blank=True)
    data_abertura = models.DateTimeField(null=True, blank=True)
    data_fechamento = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=255, null=True, blank=True)
    cluster = models.CharField(max_length=255, null=True, blank=True)
    safra = models.CharField(max_length=255, null=True, blank=True)
    data_agendamento = models.DateField(null=True, blank=True)
    dacc_sol = models.CharField(max_length=255, null=True, blank=True)
    dacc_efe = models.CharField(max_length=255, null=True, blank=True)
    dia_vencimento = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_vl_mesmo_endereco_cpf_diferente = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_vl_mesmo_endereco_cpf_igual = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_planta_mesmo_endereco_cpf_igual = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_planta_mesmo_endereco_cpf_diferente = models.CharField(max_length=255, null=True, blank=True)
    contato1 = models.CharField(max_length=255, null=True, blank=True)
    contato2 = models.CharField(max_length=255, null=True, blank=True)
    contato3 = models.CharField(max_length=255, null=True, blank=True)
    flg_mig_cobre_fixo = models.CharField(max_length=255, null=True, blank=True)
    flg_mig_cobre_velox = models.CharField(max_length=255, null=True, blank=True)
    flg_mig_tv = models.CharField(max_length=255, null=True, blank=True)
    desc_pendencia = models.CharField(max_length=255, null=True, blank=True)
    tipo_pendencia = models.CharField(max_length=255, null=True, blank=True)
    cod_pendencia = models.CharField(max_length=255, null=True, blank=True)
    oferta = models.CharField(max_length=255, null=True, blank=True)
    comunidade = models.CharField(max_length=255, null=True, blank=True)
    gv = models.CharField(max_length=255, null=True, blank=True)
    gc = models.CharField(max_length=255, null=True, blank=True) 
    sap_principal_fim = models.CharField(max_length=255, null=True, blank=True)
    gestao = models.CharField(max_length=255, null=True, blank=True)
    st_regional = models.CharField(max_length=255, null=True, blank=True)
    meio_pagamento = models.CharField(max_length=255, null=True, blank=True)
    flag_vll = models.CharField(max_length=255, null=True, blank=True)
    status_checkout = models.CharField(max_length=255, null=True, blank=True)
    numero_ba = models.CharField(max_length=255, null=True, blank=True)
    venda_no_app = models.CharField(max_length=255, null=True, blank=True)
    celula = models.CharField(max_length=255, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    fg_venda_valida = models.CharField(max_length=255, null=True, blank=True)
    desc_motivo_ordem = models.CharField(max_length=255, null=True, blank=True)
    desc_sub_motivo_ordem = models.CharField(max_length=255, null=True, blank=True)
    campanha = models.CharField(max_length=255, null=True, blank=True)
    flg_mei = models.CharField(max_length=255, null=True, blank=True)
    nm_diretoria = models.CharField(max_length=255, null=True, blank=True)
    nm_regional = models.CharField(max_length=255, null=True, blank=True)
    cd_rede = models.CharField(max_length=255, null=True, blank=True)
    gp_canal = models.CharField(max_length=255, null=True, blank=True)
    gerencia = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Importação OSAB - DOC {self.documento}"
    class Meta:
        db_table = 'crm_importacao_osab'
        verbose_name = "Importação OSAB"
        verbose_name_plural = "Importações OSAB"


class ControleTTDiaTratado(models.Model):
    """Marcação por (TT, dia): positivo = venda registrada, negativo = não foi possível ter vendas."""
    TIPO_TRATADO = 'tratado'
    TIPO_NAO_VENDAS = 'nao_vendas'
    TIPO_CHOICES = [
        (TIPO_TRATADO, 'Venda registrada no dia'),
        (TIPO_NAO_VENDAS, 'Não foi possível ter vendas no dia'),
    ]
    matricula_vendedor = models.CharField(max_length=50, db_index=True)
    data = models.DateField(db_index=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_TRATADO)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='controle_tt_tratados'
    )
    marcado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_controle_tt_dia_tratado'
        verbose_name = "Controle TT dia tratado"
        verbose_name_plural = "Controle TT dias tratados"
        unique_together = [('matricula_vendedor', 'data')]
        ordering = ['-data', 'matricula_vendedor']

    def __str__(self):
        return f"{self.matricula_vendedor} em {self.data} ({self.tipo})"


class ControleTTCreditoUsoDiario(models.Model):
    """
    Contador de consultas de crédito por TT/dia.
    Usado para distribuir o volume entre matrículas e evitar concentração na Nio.
    """
    matricula_vendedor = models.CharField(max_length=50, db_index=True)
    data = models.DateField(db_index=True)
    consultas = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "crm_controle_tt_credito_uso_diario"
        verbose_name = "Controle TT uso crédito (dia)"
        verbose_name_plural = "Controle TT uso crédito (dia)"
        unique_together = [("matricula_vendedor", "data")]
        ordering = ["data", "matricula_vendedor"]

    def __str__(self) -> str:
        return f"{self.matricula_vendedor} em {self.data}: {self.consultas} consulta(s)"


class ControleTTCreditoCursorPap(models.Model):
    """
    Cursor da rotação sequencial de TTs na análise de crédito.

    Guarda a última matrícula entregue para cada PDV (login BO), permitindo que
    a próxima consulta pegue o item seguinte da lista do próprio PAP em vez de
    sortear matrículas da OSAB que podem não existir no portal.
    """
    bo_matricula = models.CharField(
        max_length=50,
        unique=True,
        help_text="Matrícula do login BO/PDV cuja lista de vendedores é percorrida.",
    )
    ultima_matricula = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Última matrícula entregue; a próxima consulta começa depois dela.",
    )
    posicao = models.PositiveIntegerField(
        default=0,
        help_text="Posição da última matrícula na lista ordenada (auditoria).",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "crm_controle_tt_credito_cursor_pap"
        verbose_name = "Controle TT crédito (cursor PAP)"
        verbose_name_plural = "Controle TT crédito (cursor PAP)"
        ordering = ["bo_matricula"]

    def __str__(self) -> str:
        return f"{self.bo_matricula}: {self.ultima_matricula or '(inicio)'} (pos {self.posicao})"


class CicloPagamento(models.Model):
    ano = models.IntegerField(null=True, blank=True)
    mes = models.CharField(max_length=20, null=True, blank=True)
    quinzena = models.CharField(max_length=10, null=True, blank=True)
    ciclo = models.CharField(max_length=50, null=True, blank=True)
    ciclo_complementar = models.CharField(max_length=50, null=True, blank=True)
    evento = models.CharField(max_length=100, null=True, blank=True)
    sub_evento = models.CharField(max_length=100, null=True, blank=True)
    canal_detalhado = models.CharField(max_length=100, null=True, blank=True)
    canal_agrupado = models.CharField(max_length=100, null=True, blank=True)
    sub_canal = models.CharField(max_length=50, null=True, blank=True)
    cod_sap = models.CharField(max_length=50, null=True, blank=True)
    cod_sap_agr = models.CharField(max_length=50, null=True, blank=True)
    parceiro_agr = models.CharField(max_length=255, null=True, blank=True)
    uf_parceiro_agr = models.CharField(max_length=2, null=True, blank=True)
    familia = models.CharField(max_length=100, null=True, blank=True)
    produto = models.CharField(max_length=100, null=True, blank=True)
    oferta = models.CharField(max_length=255, null=True, blank=True)
    plano_detalhado = models.CharField(max_length=255, null=True, blank=True)
    celula = models.CharField(max_length=100, null=True, blank=True)
    metodo_pagamento = models.CharField(max_length=50, null=True, blank=True)
    contrato = models.CharField(max_length=50, unique=True, primary_key=True)
    num_os_pedido_siebel = models.CharField(max_length=50, null=True, blank=True)
    id_bundle = models.CharField(max_length=50, null=True, blank=True)
    data_atv = models.DateField(null=True, blank=True)
    data_retirada = models.DateField(null=True, blank=True)
    qtd = models.IntegerField(null=True, blank=True)
    comissao_bruta = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fator = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    iq = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_comissao_final = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'crm_ciclo_pagamento'
        verbose_name = "Ciclo de Pagamento"
        verbose_name_plural = "Ciclos de Pagamento"

    def __str__(self):
        return f"{self.contrato} - {self.ciclo}"

class HistoricoAlteracaoVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.SET_NULL, null=True, related_name='historico_alteracoes')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='alteracoes_vendas')
    data_alteracao = models.DateTimeField(auto_now_add=True)
    alteracoes = models.JSONField(default=dict, help_text="Registra alterações ou a exclusão da venda")

    class Meta:
        db_table = 'crm_historico_alteracao_venda'
        verbose_name = "Histórico de Alteração de Venda"
        verbose_name_plural = "Históricos de Alteração de Venda"
        ordering = ['-data_alteracao']

    def __str__(self):
        usuario_str = self.usuario.username if self.usuario else 'N/A'
        return f"Alteração na Venda #{self.venda.id} por {usuario_str} em {self.data_alteracao.strftime('%d/%m/%Y %H:%M')}"

class Campanha(models.Model):
    TIPO_META_CHOICES = [
        ('BRUTA', 'Vendas Brutas (OS Aberta)'),
        ('LIQUIDA', 'Vendas Líquidas (Instaladas)'),
    ]
    
    CANAL_CHOICES = [
        ('TODOS', 'Todos os Canais'),
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
    ]

    nome = models.CharField(max_length=100, unique=True)
    
    data_inicio = models.DateField(null=True, blank=True, verbose_name="Início")
    data_fim = models.DateField(null=True, blank=True, verbose_name="Fim")
    
    meta_vendas = models.IntegerField(default=0, help_text="Quantidade alvo de vendas")
    valor_premio = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Prêmio em Dinheiro (R$)", help_text="Valor a ser pago se atingir a meta")
    
    tipo_meta = models.CharField(max_length=20, choices=TIPO_META_CHOICES, default='LIQUIDA', verbose_name="Tipo de Meta")
    canal_alvo = models.CharField(max_length=20, choices=CANAL_CHOICES, default='TODOS', verbose_name="Canal Alvo")
    
    # Novos Relacionamentos ManyToMany
    planos_elegiveis = models.ManyToManyField('Plano', blank=True, verbose_name="Planos Válidos", help_text="Se deixar vazio, vale para todos.")
    formas_pagamento_elegiveis = models.ManyToManyField('FormaPagamento', blank=True, verbose_name="Pagamentos Válidos", help_text="Se deixar vazio, vale para todas.")
    
    descricao_premio = models.TextField(blank=True, null=True, verbose_name="Prêmio", help_text="Descrição da premiação")
    regras = models.TextField(blank=True, null=True, verbose_name="Regras") 
    
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        inicio = self.data_inicio.strftime('%d/%m') if self.data_inicio else '?'
        fim = self.data_fim.strftime('%d/%m') if self.data_fim else '?'
        return f"{self.nome} ({inicio} - {fim})"

    class Meta:
        verbose_name = "Campanha"
        verbose_name_plural = "Campanhas"

class RegraCampanha(models.Model):
    campanha = models.ForeignKey(Campanha, on_delete=models.CASCADE, related_name='regras_meta')
    meta = models.IntegerField(verbose_name="Meta (Qtd Vendas)")
    valor_premio = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Prêmio (R$)")

    def __str__(self):
        return f"> {self.meta} vendas = R$ {self.valor_premio}"

    class Meta:
        verbose_name = "Faixa de Premiação"
        verbose_name_plural = "Faixas de Premiação"
        ordering = ['-meta']

class ComissaoOperadora(models.Model):
    plano = models.OneToOneField(Plano, on_delete=models.CASCADE, related_name='comissao_operadora', verbose_name="Plano")
    valor_base = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Base")
    bonus_transicao = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Bônus Transição")
    
    data_inicio_bonus = models.DateField(null=True, blank=True, verbose_name="Início Bônus")
    data_fim_bonus = models.DateField(null=True, blank=True, verbose_name="Fim Bônus")

    def __str__(self):
        return f"Recebimento {self.plano.nome}"


class RegraComissaoFaixa(models.Model):
    """
    Regras por faixa de vendas (aba REGRAS_FAIXAS do Excel).
    PERFIL = Supervisor/Vendedor (regra geral) ou vendedor específico quando vendedor preenchido.
    FINALIDADE: COMISSAO = usada no pagamento da folha (considera MIN/MAX); ADIANTAMENTO = só na tela de adiantamento (Comissão est.).
    """
    PERFIL_CHOICES = [
        ('Vendedor', 'Vendedor'),
        ('Supervisor', 'Supervisor'),
    ]
    FINALIDADE_CHOICES = [
        ('COMISSAO', 'Pagamento de comissão'),
        ('ADIANTAMENTO', 'Adiantamento'),
    ]
    perfil = models.CharField(
        max_length=50, choices=PERFIL_CHOICES, blank=True, null=True,
        help_text="Vazio se for regra individual (vendedor preenchido)"
    )
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='regras_comissao_faixa', null=True, blank=True,
        help_text="Preenchido quando a regra é só para este vendedor (ex.: ALEX)"
    )
    finalidade = models.CharField(
        max_length=20,
        choices=FINALIDADE_CHOICES,
        default='COMISSAO',
        help_text="Comissão = folha de pagamento (usa MIN/MAX). Adiantamento = só tela de adiantamento."
    )
    faixa_nome = models.CharField(max_length=100)
    min_vendas = models.PositiveIntegerField(default=0)
    max_vendas = models.PositiveIntegerField(
        default=99999,
        help_text="Use 99999 para sem teto"
    )
    valor_500mb_pap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_700mb_pap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_1gb_pap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_500mb_cnpj = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_700mb_cnpj = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_1gb_cnpj = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'crm_regra_comissao_faixa'
        verbose_name = "Regra de Comissão por Faixa"
        verbose_name_plural = "Regras de Comissão por Faixa"
        ordering = ['perfil', 'vendedor', 'min_vendas']

    def __str__(self):
        who = self.vendedor.username if self.vendedor_id else (self.perfil or "?")
        return f"{who} | {self.faixa_nome} ({self.min_vendas}-{self.max_vendas})"


class RegraComissaoFaixaPlano(models.Model):
    """Valor de comissão por faixa × plano (coluna dinâmica na matriz de comissionamento)."""
    faixa = models.ForeignKey(
        RegraComissaoFaixa, on_delete=models.CASCADE, related_name='valores_por_plano',
    )
    plano = models.ForeignKey(
        Plano, on_delete=models.CASCADE, related_name='valores_faixa_comissao',
    )
    valor_pap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_cnpj = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'crm_regra_comissao_faixa_plano'
        verbose_name = 'Comissão faixa × plano'
        verbose_name_plural = 'Comissões faixa × plano'
        constraints = [
            models.UniqueConstraint(
                fields=['faixa', 'plano'],
                name='crm_regra_comissao_faixa_plano_uniq',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.faixa.faixa_nome} — {self.plano.nome}'


class ConfigComissaoVendedor(models.Model):
    """
    Configuração de comissão por vendedor (aba REGRAS_VENDEDORES do Excel).
    Uma linha por usuário (e por mês quando ano/mes preenchidos); valores manuais sobrescrevem faixa quando usar_valor_manual=True.
    ano/mes nulos = modelo padrão do vendedor; preenchidos = regras daquele mês.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='configs_comissao'
    )
    ano = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Ano de referência (nulo = modelo padrão)')
    mes = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Mês de referência (1-12, nulo = modelo padrão)')
    perfil_comissao = models.CharField(
        max_length=20, choices=RegraComissaoFaixa.PERFIL_CHOICES, default='Vendedor'
    )
    usar_valor_manual = models.BooleanField(
        default=False,
        verbose_name="Usar valor manual?"
    )
    valor_500mb_pap_manual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_700mb_pap_manual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_1gb_pap_manual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_500mb_cnpj_manual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_700mb_cnpj_manual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_1gb_cnpj_manual = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    desconta_dacc_pap = models.BooleanField(default=False, verbose_name="Desconta DACC PAP?")
    desconta_boleto_pap = models.BooleanField(default=True, verbose_name="Desconta Boleto PAP?")
    desconto_boleto = models.DecimalField(max_digits=10, decimal_places=2, default=0, null=True, blank=True)
    desconto_inclusao = models.DecimalField(max_digits=10, decimal_places=2, default=0, null=True, blank=True)
    desconto_instalacao = models.DecimalField(max_digits=10, decimal_places=2, default=0, null=True, blank=True)
    adiantar_cnpj = models.DecimalField(max_digits=10, decimal_places=2, default=0, null=True, blank=True)
    inss_valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    adiantamento = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    premiação = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bonus_cartao_credito = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cartao_trafego = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    gestor_trafego = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'crm_config_comissao_vendedor'
        verbose_name = "Config. Comissão Vendedor"
        verbose_name_plural = "Config. Comissão Vendedores"
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'ano', 'mes'],
                condition=models.Q(ano__isnull=False) & models.Q(mes__isnull=False),
                name='crm_config_comissao_vendedor_ano_mes_uniq',
            ),
        ]

    def __str__(self):
        ref = f" {self.ano}/{self.mes}" if self.ano and self.mes else ""
        return f"Config comissão: {self.usuario.username}{ref}"


class PlanoValoresComissaoVendedor(models.Model):
    """Override de comissão por plano na config do vendedor (além das colunas fixas por banda)."""
    config = models.ForeignKey(
        ConfigComissaoVendedor, on_delete=models.CASCADE,
        related_name='valores_por_plano',
    )
    plano = models.ForeignKey(
        Plano, on_delete=models.CASCADE, related_name='valores_vendedor',
    )
    valor_pap = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_cnpj = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'crm_plano_valores_comissao_vendedor'
        verbose_name = 'Comissão plano × vendedor'
        verbose_name_plural = 'Comissões plano × vendedor'
        constraints = [
            models.UniqueConstraint(
                fields=['config', 'plano'],
                name='crm_plano_valores_comissao_vendedor_uniq',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.plano.nome} — {self.config}'


class Comunicado(models.Model):
    PERFIL_CHOICES = [
        ('TODOS', 'Todos'),
        ('VENDEDOR', 'Vendedores'),
        ('SUPERVISOR', 'Supervisores'),
        ('BACKOFFICE', 'Backoffice'),
        ('DIRETORIA', 'Diretoria'),
    ]
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('ENVIADO', 'Enviado'),
        ('CANCELADO', 'Cancelado'),
        ('ERRO', 'Erro'),
    ]
    CANAL_OPCOES = [
        ('TODOS', 'Todos'),
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
    ]
    STATUS_DESTINATARIOS_CHOICES = [
        ('somente_ativos', 'Somente ativos'),
        ('somente_inativos', 'Somente inativos'),
        ('todos', 'Todos'),
    ]

    titulo = models.CharField(max_length=200, verbose_name="Título Interno")
    mensagem = models.TextField(verbose_name="Mensagem WhatsApp")
    
    data_programada = models.DateField()
    hora_programada = models.TimeField()
    
    perfil_destino = models.CharField(max_length=20, choices=PERFIL_CHOICES, default='TODOS')
    canal_alvo = models.CharField(
        max_length=20, choices=CANAL_OPCOES, default='TODOS', verbose_name="Canal Alvo"
    )
    cluster_alvo = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Filtro por cluster (vazio ou TODOS = todos). Ex: CLUSTER_1, CLUSTER_2, CLUSTER_3",
    )
    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comunicados_direcionados',
        verbose_name="Vendedor específico",
    )
    status_destinatarios = models.CharField(
        max_length=20,
        choices=STATUS_DESTINATARIOS_CHOICES,
        default='somente_ativos',
        help_text="Define se o envio individual considera usuários ativos, inativos ou todos.",
    )
    representatividade_minima = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Representatividade mínima (%)",
        help_text="0 = todos. Filtra vendedores com participação mínima no volume do mês (O.S. cadastradas).",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.titulo} - {self.get_status_display()}"
    
    class Meta:
        verbose_name = "Comunicado (Record Informa)"
        verbose_name_plural = "Comunicados"
        ordering = ['-data_programada', '-hora_programada']

class AreaVenda(models.Model):
    nome_kml = models.CharField(max_length=255, help_text="Nome que estava no Placemark")
    celula = models.CharField(max_length=255, null=True, blank=True)
    uf = models.CharField(max_length=2, null=True, blank=True)
    municipio = models.CharField(max_length=100, null=True, blank=True)
    bairro = models.CharField(max_length=100, null=True, blank=True)
    prioridade = models.IntegerField(default=0, null=True, blank=True)
    estacao = models.CharField(max_length=50, null=True, blank=True)
    aging = models.IntegerField(default=0, null=True, blank=True)
    cluster = models.CharField(max_length=50, null=True, blank=True)
    status_venda = models.CharField(max_length=100, null=True, blank=True)
    hc = models.IntegerField(default=0, verbose_name="HC")
    hp = models.IntegerField(default=0, verbose_name="HP")
    hp_viavel = models.IntegerField(default=0, verbose_name="HP Viável")
    hp_viavel_total = models.IntegerField(default=0, verbose_name="HP Viável Total")
    ocupacao = models.CharField(max_length=20, null=True, blank=True, help_text="Percentual texto")
    hc_esperado = models.FloatField(default=0.0)
    atingimento_meta = models.CharField(max_length=20, null=True, blank=True)
    coordenadas = models.TextField(null=True, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.municipio} - {self.celula} ({self.nome_kml})"

    class Meta:
        verbose_name = "Área de Venda (KML)"
        verbose_name_plural = "Áreas de Venda (KML)"

class SessaoWhatsapp(models.Model):
    # O PROBLEMA ESTÁ AQUI: max_length=20 é muito curto
    telefone = models.CharField(max_length=100, unique=True) 
    etapa = models.CharField(max_length=50) 
    dados_temp = models.JSONField(default=dict) 
    updated_at = models.DateTimeField(auto_now=True)
    data_ultimo_aviso_nao_autorizado = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data do último aviso de usuário não autorizado",
        help_text="Quando o usuário não está autorizado a chamar no bot, usamos esta data para enviar o aviso apenas uma vez por dia."
    )

    def __str__(self):
        return f"{self.telefone} - {self.etapa}"


class BrProntoBoEmUso(models.Model):
    """
    Controla qual login Br Pronto (ged360) está em uso pela automação de biometria.
    Evita conflito de sessão (GED bloqueia login simultâneo no mesmo usuário).
    """
    bo_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="brpronto_sessoes_em_uso",
        help_text="Usuário cujo login Br Pronto está em uso",
    )
    solicitante_telefone = models.CharField(max_length=100, blank=True, default="", db_index=True)
    locked_at = models.DateTimeField(auto_now_add=True)
    sessao_whatsapp_id = models.IntegerField(null=True, blank=True)
    origem = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="origem da reserva: bio | auditoria | etc.",
    )

    class Meta:
        db_table = "crm_brpronto_bo_em_uso"
        verbose_name = "Br Pronto BO em Uso"
        verbose_name_plural = "Br Pronto BOs em Uso"

    def __str__(self) -> str:
        return f"BrPronto {self.bo_usuario_id} em uso por {self.solicitante_telefone or 'sistema'}"


class PapBoEmUso(models.Model):
    """
    Controla qual usuário BackOffice está em uso pela automação PAP.
    Vendedores com autorizar_venda_sem_auditoria usam logins de BO (pool),
    pois não conseguem vender pelo site pap.niointernet.com.br.
    """
    TIPO_VENDER = 'vender'
    TIPO_CREDITO = 'credito'
    TIPO_PEDIDO = 'pedido'
    TIPO_STATUS = 'status'
    TIPOS_AUTOMACAO = (
        (TIPO_VENDER, 'Vender'),
        (TIPO_CREDITO, 'Crédito'),
        (TIPO_PEDIDO, 'Pedido'),
        (TIPO_STATUS, 'Status'),
    )
    bo_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='pap_sessoes_em_uso',
        help_text="Usuário BackOffice cujo login está em uso"
    )
    vendedor_telefone = models.CharField(max_length=100, db_index=True)
    locked_at = models.DateTimeField(auto_now_add=True)
    sessao_whatsapp_id = models.IntegerField(null=True, blank=True)
    tipo_automacao = models.CharField(
        max_length=20,
        choices=TIPOS_AUTOMACAO,
        blank=True,
        default='',
        verbose_name='Tipo automação',
        help_text='Tipo de automação que está usando este login (para auditoria).'
    )

    class Meta:
        db_table = 'crm_pap_bo_em_uso'
        verbose_name = "PAP BO em Uso"
        verbose_name_plural = "PAP BOs em Uso"

    def __str__(self):
        return f"BO {self.bo_usuario.username} em uso por {self.vendedor_telefone}"


class HistoricoConsultaAutomacaoPAP(models.Model):
    """
    Auditoria de consultas das automações ao pool de login PAP.
    Registra quem chamou a automação e qual login PAP foi utilizado.
    """
    TIPO_VENDER = 'vender'
    TIPO_CREDITO = 'credito'
    TIPO_PEDIDO = 'pedido'
    TIPO_STATUS = 'status'
    TIPOS_AUTOMACAO = (
        (TIPO_VENDER, 'Vender'),
        (TIPO_CREDITO, 'Crédito'),
        (TIPO_PEDIDO, 'Pedido'),
        (TIPO_STATUS, 'Status'),
    )
    STATUS_PENDENTE = 'pendente'
    STATUS_SUCESSO = 'sucesso'
    STATUS_ERRO = 'erro'
    STATUS_EXECUCAO = (
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_SUCESSO, 'Sucesso'),
        (STATUS_ERRO, 'Erro'),
    )

    solicitado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='historico_consultas_automacao_pap',
        help_text='Usuário que chamou a automação (quando identificado).',
    )
    telefone_solicitante = models.CharField(
        max_length=100,
        blank=True,
        default='',
        db_index=True,
        help_text='Telefone usado na sessão da automação (fallback de auditoria).',
    )
    tipo_automacao = models.CharField(
        max_length=20,
        choices=TIPOS_AUTOMACAO,
        blank=True,
        default='',
        db_index=True,
    )
    login_pap_utilizado = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='historico_logins_pap_utilizados',
        help_text='Usuário BackOffice cujo login PAP foi alocado para a automação.',
    )
    matricula_pap_utilizada = models.CharField(
        max_length=80,
        blank=True,
        default='',
        help_text='Snapshot da matrícula PAP no momento da alocação.',
    )
    status_execucao = models.CharField(
        max_length=20,
        choices=STATUS_EXECUCAO,
        default=STATUS_PENDENTE,
        db_index=True,
        help_text='Resultado final da consulta após execução da automação.',
    )
    mensagem_resultado = models.TextField(
        blank=True,
        default='',
        help_text='Resumo do resultado/erro retornado ao usuário.',
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_hist_consulta_automacao_pap'
        verbose_name = 'Histórico consulta automação PAP'
        verbose_name_plural = 'Histórico consultas automação PAP'
        ordering = ['-criado_em']

    def __str__(self):
        automacao = self.get_tipo_automacao_display() if self.tipo_automacao else 'Não informado'
        login = self.login_pap_utilizado.username if self.login_pap_utilizado else '-'
        return f'{automacao} | login PAP: {login} | {self.criado_em:%d/%m/%Y %H:%M}'


class FilaEsperaPAP(models.Model):
    """
    Fila de espera quando todos os logins PAP estão em uso.
    Ao liberar um login, o primeiro da fila é avisado por WhatsApp.
    """
    TIPO_VENDER = 'vender'
    TIPO_PEDIDO = 'pedido'
    TIPO_STATUS = 'status'
    TIPO_CREDITO = 'credito'
    TIPOS = (
        (TIPO_VENDER, 'Vender'),
        (TIPO_PEDIDO, 'Pedido'),
        (TIPO_STATUS, 'Status'),
        (TIPO_CREDITO, 'Crédito'),
    )

    telefone = models.CharField(max_length=100, db_index=True)
    tipo_acao = models.CharField(max_length=20, choices=TIPOS, default=TIPO_VENDER)
    created_at = models.DateTimeField(auto_now_add=True)
    sessao_whatsapp_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'crm_fila_espera_pap'
        verbose_name = "Fila espera PAP"
        verbose_name_plural = "Fila espera PAP"
        ordering = ['created_at']

    def __str__(self):
        return f"{self.telefone} ({self.get_tipo_acao_display()}) desde {self.created_at}"


class PapConfirmacaoCliente(models.Model):
    """
    Pendência de confirmação "Sim" do cliente no fluxo PAP ou resumo enviado da auditoria.
    Usado para compartilhar estado entre terminal (testar_pap_terminal) e webhook:
    terminal registra ao enviar resumo; webhook marca confirmado ao receber "Sim".
    sessao_id vincula a confirmação à sessão atual (PAP). venda_id vincula à auditoria.
    """
    celular_cliente = models.CharField(max_length=20, db_index=True)
    protocolo_pedido = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="Protocolo PAP do pedido ao enviar o resumo (evita SIM de outra venda no mesmo celular).",
    )
    protocolo_confirmacao_envio = models.CharField(
        max_length=24,
        blank=True,
        null=True,
        db_index=True,
        help_text="Protocolo enviado ao cliente ao confirmar (YYYYMMDDHHMM + seq 4 dígitos).",
    )
    confirmado = models.BooleanField(default=False)
    sessao = models.ForeignKey(
        'SessaoWhatsapp',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='sessao_id',
        db_index=True,
        related_name='pap_confirmacoes',
    )
    venda = models.ForeignKey(
        'Venda',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        related_name='pap_confirmacoes_auditoria',
        help_text='Preenchido quando o resumo foi enviado da auditoria; ao confirmar, gera protocolo nesta venda.',
    )
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resumos_plano_enviados',
        verbose_name='Enviado por (BO)',
        help_text='Usuário que enviou o resumo do plano pela auditoria.',
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'crm_pap_confirmacao_cliente'
        verbose_name = "PAP Confirmação Cliente"
        ordering = ['-criado_em']

    def __str__(self):
        return f"{self.celular_cliente} - {'OK' if self.confirmado else 'pendente'}"


class PapProtocoloConfirmacaoSequencia(models.Model):
    """Contador por minuto (YYYYMMDDHHMM) para protocolo de confirmação no WhatsApp."""

    janela = models.CharField(max_length=12, unique=True, db_index=True)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "crm_pap_protocolo_confirmacao_sequencia"
        verbose_name = "PAP protocolo confirmação (sequência/min)"
        verbose_name_plural = "PAP protocolos confirmação (sequência/min)"

    def __str__(self):
        return f"{self.janela} → {self.ultimo}"


class AnaliseCreditoHistorico(models.Model):
    """
    Histórico de consultas de análise de crédito via WhatsApp.
    Usado para rate limit (1 min entre análises, 15 por dia) e auditoria.
    """
    STATUS_PENDENTE = "pendente"
    STATUS_SUCESSO = "sucesso"
    STATUS_ERRO = "erro"
    STATUS_CHOICES = (
        (STATUS_PENDENTE, "Pendente"),
        (STATUS_SUCESSO, "Sucesso"),
        (STATUS_ERRO, "Erro"),
    )
    ORIGEM_DADOS_ASSERTIVA = "assertiva"
    ORIGEM_DADOS_ALEATORIO = "aleatorio"
    ORIGEM_DADOS_MISTO = "misto"
    ORIGEM_DADOS_CHOICES = (
        (ORIGEM_DADOS_ASSERTIVA, "Assertiva"),
        (ORIGEM_DADOS_ALEATORIO, "Aleatório"),
        (ORIGEM_DADOS_MISTO, "Misto"),
    )
    FORMAS_TODAS = "todas"
    FORMAS_CARTAO = "cartao"
    FORMAS_PAGAMENTO_CHOICES = (
        (FORMAS_TODAS, "Todas as formas de pagamento"),
        (FORMAS_CARTAO, "Apenas cartão de crédito"),
    )

    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='analises_credito_historico',
        help_text="Usuário que fez a consulta",
    )
    cpf_consultado = models.CharField(
        max_length=14,
        db_index=True,
        help_text="CPF consultado (apenas dígitos)",
    )
    aprovado = models.BooleanField(
        null=True,
        blank=True,
        help_text="True se crédito aprovado, False se negado",
    )
    status_execucao = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDENTE,
        db_index=True,
        help_text="Estado atual/final da execução da consulta.",
    )
    telefone_solicitante = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        help_text="Telefone do usuário que solicitou a análise pelo WhatsApp.",
    )
    assertiva_consultada = models.BooleanField(
        default=False,
        help_text="Indica se a API Assertiva respondeu à consulta cadastral.",
    )
    assertiva_dados = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot normalizado dos contatos e endereço retornados pela Assertiva.",
    )
    assertiva_erro = models.TextField(
        blank=True,
        default="",
        help_text="Erro ocorrido ao consultar ou validar os dados da Assertiva.",
    )
    endereco_utilizado = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Endereço usado na viabilidade (origem assertiva/padrao) e "
            "bloqueios encontrados nas tentativas anteriores."
        ),
    )
    origem_contato = models.CharField(
        max_length=20,
        choices=ORIGEM_DADOS_CHOICES,
        default=ORIGEM_DADOS_ASSERTIVA,
        help_text=(
            "Origem do telefone/e-mail aceitos pelo PAP: dados da Assertiva, "
            "gerados aleatoriamente ou uma combinação dos dois."
        ),
    )
    contato_utilizado = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Telefone(s) e e-mail aceitos pelo PAP, com a origem de cada um "
            "(assertiva ou aleatorio)."
        ),
    )
    resultado_detalhe = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Ex: Elegível para todas as formas, Elegível apenas para Cartão",
    )
    formas_pagamento = models.CharField(
        max_length=20,
        choices=FORMAS_PAGAMENTO_CHOICES,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Quando aprovado: se o PAP liberou todas as formas de pagamento ou "
            "apenas cartão de crédito."
        ),
    )
    motivo_negativa = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text="Quando negado: motivo exibido no modal de resultado do PAP.",
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "crm_analise_credito_historico"
        verbose_name = "Análise de Crédito (Histórico)"
        verbose_name_plural = "Análises de Crédito (Histórico)"
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["usuario", "criado_em"]),
        ]

    def __str__(self):
        if self.aprovado is None:
            status = self.get_status_execucao_display()
        else:
            status = "Aprovado" if self.aprovado else "Negado"
        return f"{self.cpf_consultado} - {self.usuario.username} - {status} - {self.criado_em}"


class EmailRecusadoPapCredito(models.Model):
    """
    E-mails que o PAP recusou na etapa de contato da análise de crédito.

    O Nio valida a entregabilidade do e-mail; os contatos históricos da Assertiva
    costumam apontar para caixas desativadas. Guardar a recusa evita repetir o
    modal "E-mail inválido" (e os ~7s de retrabalho) na próxima consulta do
    mesmo cliente.
    """
    MOTIVO_INVALIDO = "EMAIL_INVALIDO"
    MOTIVO_REJEITADO = "EMAIL_REJEITADO"
    MOTIVO_CHOICES = (
        (MOTIVO_INVALIDO, "E-mail inválido para o Nio"),
        (MOTIVO_REJEITADO, "E-mail já usado em pedido anterior"),
    )

    email = models.EmailField(
        max_length=254,
        unique=True,
        help_text="E-mail recusado pelo PAP (sempre em minúsculas).",
    )
    motivo = models.CharField(
        max_length=20,
        choices=MOTIVO_CHOICES,
        default=MOTIVO_INVALIDO,
        db_index=True,
        help_text="Classificação do modal Atenção! que recusou o e-mail.",
    )
    ocorrencias = models.PositiveIntegerField(
        default=1,
        help_text="Quantidade de vezes que o PAP recusou este e-mail.",
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "crm_email_recusado_pap_credito"
        verbose_name = "E-mail recusado no PAP (crédito)"
        verbose_name_plural = "E-mails recusados no PAP (crédito)"
        ordering = ["-atualizado_em"]

    def __str__(self) -> str:
        return f"{self.email} - {self.motivo} ({self.ocorrencias}x)"


class EstatisticaBotWhatsApp(models.Model):
    """
    Armazena estatísticas de mensagens enviadas pelo bot WhatsApp
    """
    COMANDO_CHOICES = [
        ('FACHADA', 'Fachada'),
        ('DFV', 'DFV (Power BI)'),
        ('CDOE', 'CDOE (Power BI)'),
        ('VIABILIDADE', 'Viabilidade'),
        ('FATURA', 'Fatura'),
        ('STATUS', 'Status'),
        ('CREDITO', 'Crédito'),
        ('BIO', 'Bio (Br Pronto)'),
        ('PEDIDO', 'Pedido'),
        ('VENDER', 'Vender'),
        ('ANDAMENTO', 'Andamento'),
    ]
    
    telefone = models.CharField(max_length=100, db_index=True, help_text="Telefone do usuário que recebeu a mensagem")
    vendedor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='estatisticas_bot', db_index=True)
    comando = models.CharField(max_length=20, choices=COMANDO_CHOICES, db_index=True)
    data_envio = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = "Estatística Bot WhatsApp"
        verbose_name_plural = "Estatísticas Bot WhatsApp"
        indexes = [
            models.Index(fields=['comando', 'data_envio']),
            models.Index(fields=['vendedor', 'data_envio']),
            models.Index(fields=['data_envio']),
        ]
    
    def __str__(self):
        vendedor_nome = self.vendedor.username if self.vendedor else "N/A"
        return f"{self.comando} - {vendedor_nome} - {self.data_envio.strftime('%d/%m/%Y %H:%M')}"

class DFV(models.Model):
    uf = models.CharField(max_length=2, null=True, blank=True)
    municipio = models.CharField(max_length=100, null=True, blank=True)
    logradouro = models.CharField(max_length=255, null=True, blank=True)
    num_fachada = models.CharField(max_length=50, null=True, blank=True, help_text="Número da fachada")
    complemento = models.CharField(max_length=255, null=True, blank=True)
    cep = models.CharField(max_length=10, null=True, blank=True)
    bairro = models.CharField(max_length=100, null=True, blank=True)
    tipo_viabilidade = models.CharField(max_length=100, null=True, blank=True)
    tipo_rede = models.CharField(max_length=50, null=True, blank=True) 
    celula = models.CharField(max_length=50, null=True, blank=True)
    nome_cdo = models.CharField(max_length=100, null=True, blank=True, help_text="Nome do CDO")
    data_importacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.logradouro}, {self.num_fachada} - {self.municipio}"
        
    class Meta:
        verbose_name = "Base DFV"
        verbose_name_plural = "Base DFV"
        indexes = [
            models.Index(fields=['cep']),
            models.Index(fields=['cep', 'num_fachada']),
        ]

class GrupoDisparo(models.Model):
    nome = models.CharField(max_length=100, help_text="Ex: Grupo Gestão Comercial")
    chat_id = models.CharField(max_length=100, help_text="ID do grupo (Ex: 12036304...g.us)")
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


class EsteiraVendasConfig(models.Model):
    """Configuração única da esteira de vendas (ex.: WhatsApp BackOffice nas msgs ao cliente)."""
    whatsapp_backoffice = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='WhatsApp BackOffice (pendência cliente)',
        help_text='Número usado no botão/mensagem de dúvidas ao marcar pendência tipo CLIENTE.',
    )
    relatorio_pendencia_cliente_ativo = models.BooleanField(
        default=False,
        verbose_name='Relatório pendências CLIENTE (WPP)',
        help_text='Envia imagem com volume de pendências tipo CLIENTE por vendedor (seg–sex).',
    )
    relatorio_pendencia_cliente_horario_1 = models.TimeField(
        default='12:00',
        verbose_name='Horário 1º envio (pend. cliente)',
    )
    relatorio_pendencia_cliente_horario_2 = models.TimeField(
        default='18:00',
        verbose_name='Horário 2º envio (pend. cliente)',
    )
    relatorio_pendencia_cliente_controle_disparos = models.JSONField(
        default=dict,
        blank=True,
        help_text='Controle interno para evitar reenvio no mesmo slot diário.',
    )
    relatorio_pendencia_cliente_grupos = models.ManyToManyField(
        'GrupoDisparo',
        blank=True,
        related_name='+',
        verbose_name='Grupos WhatsApp (pend. cliente)',
        help_text='Grupos que recebem a imagem de pendências CLIENTE por vendedor.',
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )

    class Meta:
        verbose_name = 'Config. Esteira de Vendas'
        verbose_name_plural = 'Config. Esteira de Vendas'

    def __str__(self):
        return f'BackOffice: {self.whatsapp_backoffice or "não definido"}'


class AnteciparInstalacaoConfig(models.Model):
    """Configuração única operacional (GC + destinos de Antecipação e Sem SLOT)."""
    nome_gc = models.CharField(max_length=100, blank=True, default='', verbose_name="Nome do GC")
    telefone_gc = models.CharField(max_length=20, blank=True, default='21979630377', verbose_name="Telefone do GC")
    email_gc = models.EmailField(
        max_length=254,
        blank=True,
        default='',
        verbose_name="E-mail do GC",
        help_text="Destino dos pedidos de ajuda/socorro (abrir chamado TI) e da máscara Sem SLOT.",
    )
    grupo = models.ForeignKey(
        GrupoDisparo, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name="Grupo WhatsApp (legado)",
        help_text="Campo legado. Preferir grupos_destino.",
    )
    grupos_destino = models.ManyToManyField(
        GrupoDisparo,
        blank=True,
        related_name='+',
        verbose_name='Grupos WhatsApp de destino',
        help_text='Grupos que recebem Antecipação e Sem SLOT (um ou mais).',
    )
    telefones_destino = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Telefones WhatsApp individuais',
        help_text='Números WhatsApp individuais que recebem Antecipação e Sem SLOT.',
    )
    relatorio_esteira_gc_ativo = models.BooleanField(
        default=False,
        verbose_name="Relatório diário esteira (GC)",
        help_text="Envia ao GC o volume de ativados e esteira de auditoria (seg-sex).",
    )
    relatorio_esteira_horario_1 = models.TimeField(
        default='17:20',
        verbose_name="Horário 1º envio (esteira GC)",
        help_text="Campo legado. Preferir relatorio_esteira_horarios.",
    )
    relatorio_esteira_horario_2 = models.TimeField(
        default='18:00',
        verbose_name="Horário 2º envio (esteira GC)",
        help_text="Campo legado. Preferir relatorio_esteira_horarios.",
    )
    relatorio_esteira_horarios = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Horários do relatório esteira (GC)",
        help_text="Lista de horários HH:MM para disparo do relatório (seg–sex). Quantos forem necessários.",
    )
    relatorio_esteira_controle_disparos = models.JSONField(
        default=dict,
        blank=True,
        help_text="Controle interno para evitar reenvio no mesmo slot diário.",
    )
    sem_slot_email_gc_ativo = models.BooleanField(
        default=True,
        verbose_name="Enviar Sem SLOT por e-mail do GC",
        help_text="Quando a auditoria dispara a máscara Sem SLOT, envia também ao e-mail do GC (com o print em anexo).",
    )
    teams_notificacao_ativo = models.BooleanField(
        default=False,
        verbose_name="Notificação Teams ativa",
        help_text="Envia cópia das mensagens operacionais (Sem SLOT, Antecipar, etc.) ao canal Teams via n8n.",
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        verbose_name = "Config. Antecipar Instalação"
        verbose_name_plural = "Config. Antecipar Instalação"

    def __str__(self):
        nome_gc = self.nome_gc or 'não definido'
        n_grupos = self.grupos_destino.count() if self.pk else 0
        n_tels = len(self.telefones_destino or [])
        return (
            f"GC: {nome_gc} ({self.telefone_gc or 'não definido'}) | "
            f"Destinos: {n_grupos} grupo(s), {n_tels} telefone(s)"
        )


class EtapaErroAjudaGc(models.Model):
    """Opções de 'qual etapa do erro' para pedidos de ajuda ao GC (auditoria ou esteira)."""

    CONTEXTO_AUDITORIA = 'auditoria'
    CONTEXTO_ESTEIRA = 'esteira'
    CONTEXTO_CHOICES = [
        (CONTEXTO_AUDITORIA, 'Auditoria'),
        (CONTEXTO_ESTEIRA, 'Esteira'),
    ]

    contexto = models.CharField(max_length=20, choices=CONTEXTO_CHOICES, db_index=True)
    nome = models.CharField(max_length=255)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativo = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'crm_etapa_erro_ajuda_gc'
        verbose_name = 'Etapa de erro (Ajuda GC)'
        verbose_name_plural = 'Etapas de erro (Ajuda GC)'
        ordering = ['contexto', 'ordem', 'nome']
        unique_together = ('contexto', 'nome')

    def __str__(self) -> str:
        return f'{self.get_contexto_display()}: {self.nome}'


class PedidoAjudaGc(models.Model):
    """Histórico de pedidos de ajuda/socorro enviados ao GC da Nio."""

    TIPO_ABRIR_CHAMADO_TI = 'abrir_chamado_ti'
    TIPO_CHOICES = [
        (TIPO_ABRIR_CHAMADO_TI, 'Abrir chamado com TI'),
    ]
    ORIGEM_AUDITORIA = 'auditoria'
    ORIGEM_ESTEIRA = 'esteira'
    ORIGEM_CHOICES = [
        (ORIGEM_AUDITORIA, 'Auditoria'),
        (ORIGEM_ESTEIRA, 'Esteira'),
    ]

    tipo = models.CharField(max_length=40, choices=TIPO_CHOICES, default=TIPO_ABRIR_CHAMADO_TI)
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='pedidos_ajuda_gc',
    )
    venda = models.ForeignKey(
        Venda,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pedidos_ajuda_gc',
    )
    nome_gc = models.CharField(max_length=100, blank=True, default='')
    email_gc = models.EmailField(max_length=254, blank=True, default='')
    telefone_gc = models.CharField(max_length=20, blank=True, default='')
    pdv = models.CharField(max_length=20, default='1068561')
    login_bo = models.CharField(max_length=100, blank=True, default='')
    login_vendedor = models.CharField(max_length=100, blank=True, default='')
    cpf_cnpj_cliente = models.CharField(max_length=20, blank=True, default='')
    numero_pedido = models.CharField(max_length=50, blank=True, default='')
    contato = models.CharField(max_length=120, blank=True, default='')
    etapa_erro = models.CharField(max_length=255, blank=True, default='')
    detalhe_cenario = models.TextField(blank=True, default='')
    numero_registro = models.CharField(max_length=80, blank=True, default='')
    evidencia = models.FileField(upload_to='pedido_ajuda_gc/%Y/%m/', blank=True, null=True)
    mensagem_enviada = models.TextField(blank=True, default='')
    enviado_email = models.BooleanField(default=False)
    enviado_whatsapp = models.BooleanField(default=False)
    erros = models.JSONField(default=list, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'crm_pedido_ajuda_gc'
        verbose_name = 'Pedido de ajuda GC'
        verbose_name_plural = 'Pedidos de ajuda GC'
        ordering = ['-criado_em']

    def __str__(self) -> str:
        return f'#{self.pk} {self.get_tipo_display()} ({self.origem})'


class AnteciparInstalacaoSolicitacao(models.Model):
    TIPO_SOLICITACAO_CHOICES = [
        ('antecipacao', 'Antecipação'),
        ('reparo', 'Reparo'),
        ('instalacao_fisica', 'Instalação física / pendência'),
    ]
    """Histórico de solicitações de antecipação de instalação e de reparo (internet pós-instalação)."""
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='solicitacoes_antecipar'
    )
    venda = models.ForeignKey(Venda, on_delete=models.SET_NULL, null=True, related_name='solicitacoes_antecipar')
    ordem_servico = models.CharField(max_length=50, blank=True)
    tipo_solicitacao = models.CharField(
        max_length=24, choices=TIPO_SOLICITACAO_CHOICES, default='antecipacao',
        verbose_name="Tipo (Antecipação, Reparo ou Instalação física)"
    )
    descricao_solicitacao = models.TextField()
    observacao_reparo = models.TextField(
        blank=True,
        verbose_name="Observação no reparo (ex.: internet não funciona total ou com lentidão)"
    )
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    enviado_gc = models.BooleanField(default=False)
    enviado_grupo = models.BooleanField(default=False)
    enviado_teams = models.BooleanField(default=False, verbose_name="Enviado ao Teams")
    erros = models.JSONField(default=list, blank=True)
    mensagem_enviada = models.TextField(blank=True)
    # Resposta do GC ao solicitante (registro + disparo de msg padronizada ao vendedor)
    RESPOSTA_GC_CHOICES = [
        ('solicitado', 'Solicitado (encaminhada para Vtal)'),
        ('antecipada', 'Antecipada'),
        ('nao_antecipada', 'Não antecipada'),
    ]
    resposta_gc = models.CharField(
        max_length=20, choices=RESPOSTA_GC_CHOICES, blank=True, null=True,
        verbose_name="Resposta do GC"
    )
    resposta_gc_em = models.DateTimeField(blank=True, null=True, verbose_name="Data da resposta GC")
    resposta_gc_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='respostas_gc_antecipar'
    )
    resposta_gc_complemento_vendedor = models.TextField(
        blank=True,
        default='',
        verbose_name="Complemento ao vendedor (texto após a resposta padrão do GC)",
    )
    imagem_anexo = models.ImageField(
        upload_to='antecipar_instalacao/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Imagem anexo (opcional)",
    )

    class Meta:
        verbose_name = "Solicitação Antecipar Instalação"
        verbose_name_plural = "Solicitações Antecipar Instalação"
        ordering = ['-data_solicitacao']

    def __str__(self):
        return f"OS {self.ordem_servico} em {self.data_solicitacao.strftime('%d/%m/%Y %H:%M')}"


class VendaEsteiraEvento(models.Model):
    """Timeline de alterações na esteira (status, pendência, agendamento, instalação)."""

    TIPO_EVENTO_CHOICES = [
        ('STATUS_ESTEIRA', 'Status esteira'),
        ('MOTIVO_PENDENCIA', 'Motivo pendência'),
        ('AGENDAMENTO', 'Agendamento'),
        ('INSTALACAO', 'Instalação (OSAB)'),
        ('INSTALACAO_FISICA', 'Instalação física'),
        ('MSG_CLIENTE_PENDENCIA', 'WhatsApp cliente (pendência)'),
    ]
    ORIGEM_CHOICES = [
        ('MANUAL', 'Manual (esteira)'),
        ('OSAB', 'Importação OSAB'),
        ('SISTEMA', 'Sistema'),
    ]

    venda = models.ForeignKey(
        Venda, on_delete=models.CASCADE, related_name='eventos_esteira', db_index=True,
    )
    tipo_evento = models.CharField(max_length=32, choices=TIPO_EVENTO_CHOICES, db_index=True)
    valor_anterior = models.CharField(max_length=500, blank=True, default='')
    valor_novo = models.CharField(max_length=500, blank=True, default='')
    origem = models.CharField(max_length=16, choices=ORIGEM_CHOICES, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_esteira_registrados',
    )
    motivo_pendencia = models.ForeignKey(
        MotivoPendencia, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_esteira',
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'crm_venda_esteira_evento'
        verbose_name = 'Evento esteira'
        verbose_name_plural = 'Eventos esteira'
        ordering = ['criado_em']
        indexes = [
            models.Index(fields=['venda', 'tipo_evento', 'criado_em']),
            models.Index(fields=['tipo_evento', 'criado_em']),
        ]

    def __str__(self):
        return f'Venda #{self.venda_id} {self.tipo_evento} ({self.origem})'


class PendenciaIndevidaRegistro(models.Model):
    """Marcação de pendência indevida na esteira (metadado; venda segue PENDENTE normalmente)."""
    venda = models.ForeignKey(
        Venda, on_delete=models.SET_NULL, null=True, related_name='pendencias_indevidas',
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='pendencias_indevidas_registradas',
    )
    motivo_pendencia = models.ForeignKey(
        'MotivoPendencia', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pendencias_indevidas',
    )
    observacao = models.TextField(blank=True)
    tem_evidencia = models.BooleanField(default=False)
    mensagem_enviada = models.TextField(blank=True)
    enviado_gc = models.BooleanField(default=False)
    erros = models.JSONField(default=list, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pendência indevida'
        verbose_name_plural = 'Pendências indevidas'
        ordering = ['-criado_em']

    def __str__(self):
        return f'Pend. indevida venda #{self.venda_id or "—"} ({self.criado_em:%d/%m/%Y})'


class PendenciaIndevidaAnexo(models.Model):
    TIPO_CHOICES = [
        ('imagem', 'Imagem'),
        ('video', 'Vídeo'),
        ('audio', 'Áudio'),
    ]
    registro = models.ForeignKey(
        PendenciaIndevidaRegistro, on_delete=models.CASCADE, related_name='anexos',
    )
    arquivo = models.FileField(upload_to='pendencia_indevida/%Y/%m/')
    nome_original = models.CharField(max_length=255, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='imagem')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Anexo pendência indevida'
        verbose_name_plural = 'Anexos pendência indevida'
        ordering = ['id']

    def __str__(self):
        return self.nome_original or str(self.arquivo)


class AuditoriaSemSlotGC(models.Model):
    """Registro de venda cadastrada sem slot — comunicação aos destinos configurados."""
    TURNO_CHOICES = [
        ('MANHA', 'Manhã'),
        ('TARDE', 'Tarde'),
    ]
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='auditorias_sem_slot',
    )
    venda = models.ForeignKey(
        Venda, on_delete=models.SET_NULL, null=True, related_name='auditorias_sem_slot',
    )
    ordem_servico = models.CharField(max_length=50, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    endereco_completo = models.TextField(blank=True)
    data_agendamento_cadastrada = models.DateField(null=True, blank=True)
    turno_agendamento_cadastrado = models.CharField(max_length=10, choices=TURNO_CHOICES, blank=True)
    data_desejada_cliente = models.DateField()
    turno_desejado_cliente = models.CharField(max_length=10, choices=TURNO_CHOICES)
    telefone_contato = models.CharField(max_length=120, blank=True)
    imagem_anexo = models.ImageField(upload_to='auditoria_sem_slot/%Y/%m/', blank=True, null=True)
    mensagem_enviada = models.TextField(blank=True)
    enviado_gc = models.BooleanField(default=False)
    enviados_diretoria = models.JSONField(
        default=list,
        blank=True,
        help_text='Telefones individuais que receberam o envio (legado: Diretoria).',
    )
    enviados_grupos = models.JSONField(
        default=list,
        blank=True,
        help_text='Chat IDs / nomes dos grupos WhatsApp que receberam o envio.',
    )
    enviado_teams = models.BooleanField(default=False, verbose_name="Enviado ao Teams")
    enviado_email = models.BooleanField(default=False, verbose_name="Enviado por e-mail ao GC")
    erros = models.JSONField(default=list, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Auditoria Sem Slot (GC)"
        verbose_name_plural = "Auditorias Sem Slot (GC)"
        ordering = ['-criado_em']

    def __str__(self):
        return f"Sem SLOT {self.ordem_servico or '—'} ({self.criado_em.strftime('%d/%m/%Y')})"


class DemandaInclusaoViabilidade(models.Model):
    """
    Solicitação de Inclusão/Viabilidade coletada no WhatsApp.
    O Google Forms é preenchido localmente pelo auditor (extensão Chrome).
    """

    STATUS_PENDENTE = "PENDENTE"
    STATUS_EM_ANDAMENTO = "EM_ANDAMENTO"
    STATUS_ENVIADA = "ENVIADA"
    STATUS_ERRO = "ERRO"
    STATUS_CANCELADA = "CANCELADA"
    STATUS_CHOICES = [
        (STATUS_PENDENTE, "Pendente"),
        (STATUS_EM_ANDAMENTO, "Em andamento"),
        (STATUS_ENVIADA, "Enviada ao Forms"),
        (STATUS_ERRO, "Erro"),
        (STATUS_CANCELADA, "Cancelada"),
    ]

    protocolo = models.CharField(max_length=32, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDENTE,
        db_index=True,
    )
    telefone_solicitante = models.CharField(max_length=30, blank=True, default="", db_index=True)
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demandas_inclusao_solicitadas",
    )
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="demandas_inclusao_auditadas",
    )
    # Snapshot dos dados coletados + payload pronto para a extensão Chrome
    dados = models.JSONField(default=dict, blank=True)
    form_payload = models.JSONField(default=dict, blank=True)
    arquivos_urls = models.JSONField(default=list, blank=True)
    r2_folder = models.CharField(max_length=255, blank=True, default="")
    observacoes = models.TextField(blank=True, default="")
    erro_mensagem = models.TextField(blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    enviado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Demanda Inclusão/Viabilidade"
        verbose_name_plural = "Demandas Inclusão/Viabilidade"
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["status", "-criado_em"]),
        ]

    def __str__(self) -> str:
        return f"Inclusão {self.protocolo} ({self.status})"


class LancamentoFinanceiro(models.Model):
    TIPOS_CHOICES = [
        ('ADIANTAMENTO_CNPJ', 'Adiantamento CNPJ'),
        ('ADIANTAMENTO_COMISSAO', 'Adiantamento de Comissão'),
        ('BONUS_PREMIACAO', 'Bônus/Premiação'),
        ('DESCONTO', 'Desconto Avulso'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lancamentos_financeiros')
    tipo = models.CharField(max_length=30, choices=TIPOS_CHOICES)
    
    data = models.DateField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    
    quantidade_vendas = models.IntegerField(default=0, blank=True, null=True)
    descricao = models.CharField(max_length=255, verbose_name="Descrição / Observação")
    
    # --- NOVO CAMPO: Para guardar IDs das vendas e permitir reversão ---
    metadados = models.JSONField(default=dict, blank=True, null=True, verbose_name="Dados de Controle") 
    
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='lancamentos_criados')
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.usuario} - R$ {self.valor}"

    class Meta:
        verbose_name = "Lançamento Financeiro"
        verbose_name_plural = "Lançamentos Financeiros"
        ordering = ['-data']
        
class AgendamentoDisparo(models.Model):
    STATUS_DESTINATARIOS_CHOICES = [
        ('somente_ativos', 'Somente ativos'),
        ('somente_inativos', 'Somente inativos'),
        ('todos', 'Todos'),
    ]
    MODO_ENVIO_CHOICES = [
        ('INTERVALO', 'Intervalo'),
        ('ESPECIFICO', 'Horários específicos'),
    ]
    TIPOS = [
        ('HORARIO', 'Diário (Hora em Hora 9h-19h)'),
        ('SEMANAL', 'Semanal (Ter/Qui/Sáb 17h)'),
    ]
    CANAL_OPCOES = [
        ('TODOS', 'Todos'),
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
    ]

    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    canal_alvo = models.CharField(max_length=20, choices=CANAL_OPCOES, default='TODOS')
    cluster_alvo = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Filtro por cluster (vazio ou TODOS = todos). Ex: CLUSTER_1, CLUSTER_2, CLUSTER_3"
    )
    destinatarios = models.TextField(help_text="IDs de grupos ou números separados por vírgula")
    ativo = models.BooleanField(default=True)
    ultimo_disparo = models.DateTimeField(null=True, blank=True)
    modo_envio = models.CharField(
        max_length=20,
        choices=MODO_ENVIO_CHOICES,
        default='INTERVALO',
        help_text="INTERVALO usa intervalo/hora_fim. ESPECIFICO usa horários exatos."
    )
    intervalo_minutos = models.PositiveIntegerField(
        default=60,
        null=True,
        blank=True,
        help_text="Intervalo mínimo em minutos entre envios (ex: 60 = 1x por hora, 30 = a cada 30 min)"
    )
    hora_fim = models.PositiveSmallIntegerField(
        default=19,
        null=True,
        blank=True,
        help_text="Horário máximo (0-23) para envio na frequência diária. Ex: 19 = até 19h59."
    )
    horarios_especificos = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista de horários HH:MM para envio (08:00-22:00)."
    )
    dias_semana = models.JSONField(
        default=list,
        blank=True,
        help_text="Dias da semana permitidos (0=Seg ... 6=Dom), usado no modo específico semanal."
    )
    controle_disparos = models.JSONField(
        default=dict,
        blank=True,
        help_text="Controle interno para evitar reenvio no mesmo slot diário."
    )
    TIPO_RELATORIO_CHOICES = [
        ('HOJE', 'Hoje'),
        ('SEMANAL', 'Semanal'),
        ('MENSAL', 'Mensal'),
    ]
    tipo_relatorio = models.CharField(
        max_length=10,
        choices=TIPO_RELATORIO_CHOICES,
        default='HOJE',
        help_text="Qual relatório enviar: Hoje, Semanal ou Mensal."
    )
    status_destinatarios = models.CharField(
        max_length=20,
        choices=STATUS_DESTINATARIOS_CHOICES,
        default='somente_ativos',
        help_text="Define se a regra envia para usuários ativos, inativos ou todos."
    )
    prioridade = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Ordem de envio: menor número envia primeiro."
    )

    def __str__(self):
        return f"{self.nome} - {self.get_canal_alvo_display()}"


class LogEnvioPerformance(models.Model):
    """Histórico de envios do Painel de Performance (regras automáticas)."""
    regra = models.ForeignKey(
        AgendamentoDisparo,
        on_delete=models.SET_NULL,
        null=True,
        related_name='logs_envio'
    )
    regra_nome = models.CharField(max_length=100)  # cópia para quando regra for apagada
    data_hora = models.DateTimeField(auto_now_add=True)
    sucesso = models.BooleanField(default=False)
    total_destinos = models.PositiveSmallIntegerField(default=0)
    sucessos = models.PositiveSmallIntegerField(default=0)
    falhas = models.PositiveSmallIntegerField(default=0)
    detalhe = models.CharField(max_length=500, blank=True)  # erro ou "OK"

    class Meta:
        ordering = ['-data_hora']
        verbose_name = "Log de envio Performance"
        verbose_name_plural = "Logs de envio Performance"

    def __str__(self):
        return f"{self.regra_nome} @ {self.data_hora} - {'OK' if self.sucesso else 'Falha'}"


class SyncStatusEsteiraExecucao(models.Model):
    """Execução do job de sincronização noturna/manual da esteira via PAP (comando STATUS)."""

    MODO_AUTOMATICO = 'automatico'
    MODO_MANUAL = 'manual'
    MODO_CONSULTA_ABA = 'consulta_aba'
    MODOS = (
        (MODO_AUTOMATICO, 'Automático'),
        (MODO_MANUAL, 'Manual'),
        (MODO_CONSULTA_ABA, 'Consulta da aba'),
    )

    STATUS_PENDENTE = 'pendente'
    STATUS_EM_ANDAMENTO = 'em_andamento'
    STATUS_CONCLUIDO = 'concluido'
    STATUS_INTERROMPIDO = 'interrompido'
    STATUS_ERRO = 'erro'
    STATUS_CHOICES = (
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_EM_ANDAMENTO, 'Em andamento'),
        (STATUS_CONCLUIDO, 'Concluído'),
        (STATUS_INTERROMPIDO, 'Interrompido'),
        (STATUS_ERRO, 'Erro'),
    )

    modo = models.CharField(max_length=16, choices=MODOS, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDENTE, db_index=True)
    iniciado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sync_status_esteira_iniciados',
    )
    iniciado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    total_pedidos = models.PositiveIntegerField(default=0)
    processados = models.PositiveIntegerField(default=0)
    atualizados = models.PositiveIntegerField(default=0)
    sem_alteracao = models.PositiveIntegerField(default=0)
    erros = models.PositiveIntegerField(default=0)
    ignorados_sem_cpf = models.PositiveIntegerField(default=0)
    relatorio_json = models.JSONField(default=dict, blank=True)
    mensagem_erro = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'crm_sync_status_esteira_execucao'
        verbose_name = 'Sync status esteira (PAP)'
        verbose_name_plural = 'Sync status esteira (PAP)'
        ordering = ['-iniciado_em']

    def __str__(self):
        return f"Sync esteira #{self.id} ({self.modo}) — {self.status}"


class NioReagendamentoExecucao(models.Model):
    """Job de reagendamento via bot WhatsApp oficial Nio (7029)."""

    MODO_UNITARIO = 'unitario'
    MODO_MASSA = 'massa'
    MODOS = (
        (MODO_UNITARIO, 'Unitário'),
        (MODO_MASSA, 'Em massa'),
    )

    STATUS_PENDENTE = 'pendente'
    STATUS_EM_ANDAMENTO = 'em_andamento'
    STATUS_CONCLUIDO = 'concluido'
    STATUS_INTERROMPIDO = 'interrompido'
    STATUS_ERRO = 'erro'
    STATUS_CHOICES = (
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_EM_ANDAMENTO, 'Em andamento'),
        (STATUS_CONCLUIDO, 'Concluído'),
        (STATUS_INTERROMPIDO, 'Interrompido'),
        (STATUS_ERRO, 'Erro'),
    )

    modo = models.CharField(max_length=16, choices=MODOS, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDENTE, db_index=True)
    iniciado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='nio_reagendamento_iniciados',
    )
    iniciado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    total_pedidos = models.PositiveIntegerField(default=0)
    processados = models.PositiveIntegerField(default=0)
    sucessos = models.PositiveIntegerField(default=0)
    falhas = models.PositiveIntegerField(default=0)
    cancelar_solicitado = models.BooleanField(default=False)
    relatorio_json = models.JSONField(default=dict, blank=True)
    mensagem_erro = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'crm_nio_reagendamento_execucao'
        verbose_name = 'Reagendamento Nio (execução)'
        verbose_name_plural = 'Reagendamento Nio (execuções)'
        ordering = ['-iniciado_em']

    def __str__(self) -> str:
        return f"Nio reagendamento #{self.id} ({self.modo}) — {self.status}"


class NioReagendamentoItem(models.Model):
    """Resultado por venda dentro de uma execução Nio."""

    STATUS_PENDENTE = 'pendente'
    STATUS_EM_ANDAMENTO = 'em_andamento'
    STATUS_SUCESSO = 'sucesso'
    STATUS_SEM_SLOT = 'sem_slot'
    STATUS_ERRO_CPF = 'erro_cpf'
    STATUS_ERRO_CONSULTA = 'erro_consulta'
    STATUS_ERRO = 'erro'
    STATUS_CANCELADO = 'cancelado'
    STATUS_CHOICES = (
        (STATUS_PENDENTE, 'Pendente'),
        (STATUS_EM_ANDAMENTO, 'Em andamento'),
        (STATUS_SUCESSO, 'Sucesso'),
        (STATUS_SEM_SLOT, 'Sem slot'),
        (STATUS_ERRO_CPF, 'Erro CPF'),
        (STATUS_ERRO_CONSULTA, 'Consulta indisponível'),
        (STATUS_ERRO, 'Erro'),
        (STATUS_CANCELADO, 'Cancelado'),
    )

    execucao = models.ForeignKey(
        NioReagendamentoExecucao,
        on_delete=models.CASCADE,
        related_name='itens',
    )
    venda = models.ForeignKey(
        'Venda',
        on_delete=models.CASCADE,
        related_name='nio_reagendamento_itens',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDENTE, db_index=True)
    mensagem = models.CharField(max_length=500, blank=True, default='')
    dados_json = models.JSONField(default=dict, blank=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'crm_nio_reagendamento_item'
        verbose_name = 'Reagendamento Nio (item)'
        verbose_name_plural = 'Reagendamento Nio (itens)'
        ordering = ['id']
        indexes = [
            models.Index(fields=['execucao', 'status']),
            models.Index(fields=['venda', '-finalizado_em']),
        ]

    def __str__(self) -> str:
        return f"Nio item #{self.id} venda={self.venda_id} — {self.status}"


# No arquivo site-record/crm_app/models.py

class CdoiSolicitacao(models.Model):
    STATUS_CHOICES = [
        ('SEM_TRATAMENTO', 'Sem tratamento'),
        ('EM_CADASTRO', 'Em cadastro'),
        ('EM_PROJETO', 'Em Projeto'),
        ('EM_EXECUCAO', 'Em Execução'),
        ('CONCLUIDA', 'Concluída'),
    ]

    # ... (mantenha os campos existentes: nome_condominio, nome_sindico, etc.)
    nome_condominio = models.CharField(max_length=255)
    nome_sindico = models.CharField(max_length=255)
    contato_sindico = models.CharField(max_length=20)
    cep = models.CharField(max_length=9)
    logradouro = models.CharField(max_length=255)
    numero = models.CharField(max_length=20)
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    uf = models.CharField(max_length=2)
    latitude = models.CharField(max_length=50, blank=True, null=True)
    longitude = models.CharField(max_length=50, blank=True, null=True)
    infraestrutura_tipo = models.CharField(max_length=50)
    possui_shaft_dg = models.BooleanField(default=False)
    total_hps = models.IntegerField(default=0)
    pre_venda_minima = models.IntegerField(default=0)
    
    link_carta_sindico = models.URLField(max_length=500, blank=True, null=True)
    link_fotos_fachada = models.URLField(max_length=500, blank=True, null=True)
    destinatarios_resumo = models.TextField(blank=True, null=True, help_text="Telefones extras para resumo")

    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data_criacao = models.DateTimeField(auto_now_add=True)
    
    # NOVOS CAMPOS / ATUALIZADOS
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='SEM_TRATAMENTO')
    observacao = models.TextField(blank=True, null=True, verbose_name="Observação do Backoffice")

    def __str__(self):
        return f"{self.nome_condominio} ({self.status})"

class CdoiBloco(models.Model):
    solicitacao = models.ForeignKey(CdoiSolicitacao, on_delete=models.CASCADE, related_name='blocos')
    nome_bloco = models.CharField(max_length=100)
    andares = models.IntegerField()
    unidades_por_andar = models.IntegerField()
    total_hps_bloco = models.IntegerField()
    # Vínculo 1:1 com obra SmartRiser — evita recriar obra com o mesmo complemento
    vtop_obra_id = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="ID obra V.top",
    )
    vtop_etapa = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name="Etapa V.top após última sync",
    )
    vtop_sincronizado_em = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Última sync V.top",
    )


class LinkPublicoPreVenda(models.Model):
    """Link público único gerado para cada acionamento CDOI"""
    codigo_unico = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="Código Único")
    acionamento = models.ForeignKey('CdoiSolicitacao', on_delete=models.CASCADE, related_name='links_prevenda', verbose_name="Acionamento CDOI")
    imagem_banner = models.URLField(max_length=2000, blank=True, null=True, verbose_name="URL da Imagem/Banner")
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Criado por")
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Criação")
    ativo = models.BooleanField(default=True, verbose_name="Link Ativo")
    
    class Meta:
        verbose_name = "Link Público Pré-venda"
        verbose_name_plural = "Links Públicos Pré-vendas"
        ordering = ['-data_criacao']
    
    def save(self, *args, **kwargs):
        if not self.codigo_unico:
            self.codigo_unico = str(uuid.uuid4()).replace('-', '')[:20]
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Link {self.codigo_unico} - {self.acionamento.nome_condominio}"
    
    def get_url_publica(self, request=None):
        """Retorna a URL completa do link público"""
        if request:
            base_url = request.build_absolute_uri('/')[:-1]
        else:
            from django.conf import settings
            base_url = getattr(settings, 'SITE_URL', 'https://www.recordpap.com.br')
        return f"{base_url}/prevenda-publica/{self.codigo_unico}/"


class PreVenda(models.Model):
    """Pré-vendas coletadas através dos links públicos"""
    link_publico = models.ForeignKey(LinkPublicoPreVenda, on_delete=models.CASCADE, related_name='prevendas', verbose_name="Link Público")
    nome_cliente = models.CharField(max_length=255, verbose_name="Nome do Cliente")
    telefone_whatsapp = models.CharField(max_length=20, verbose_name="Telefone/WhatsApp")
    email = models.EmailField(blank=True, null=True, verbose_name="E-mail")
    bloco = models.CharField(max_length=100, blank=True, null=True, verbose_name="Bloco")
    apartamento = models.CharField(max_length=50, blank=True, null=True, verbose_name="Apartamento")
    data_cadastro = models.DateTimeField(auto_now_add=True, verbose_name="Data de Cadastro")
    ip_origem = models.GenericIPAddressField(blank=True, null=True, verbose_name="IP de Origem")
    
    class Meta:
        verbose_name = "Pré-venda"
        verbose_name_plural = "Pré-vendas"
        ordering = ['-data_cadastro']
    
    def __str__(self):
        return f"{self.nome_cliente} - {self.telefone_whatsapp} ({self.link_publico.acionamento.nome_condominio})"
    
    @property
    def acionamento_cdoi(self):
        """Retorna o acionamento CDOI vinculado"""
        return self.link_publico.acionamento


# =============================================================================
# BÔNUS M-10 & FPD
# =============================================================================

class SafraM10(models.Model):
    """Agrupa contratos por safra (mês de instalação)"""
    mes_referencia = models.DateField(help_text="Mês/Ano da safra (ex: 2025-07-01)")
    total_instalados = models.IntegerField(default=0, help_text="Total de contratos instalados na safra")
    total_ativos = models.IntegerField(default=0, help_text="Total ainda ativo")
    total_elegivel_bonus = models.IntegerField(default=0, help_text="Elegíveis para bônus M-10")
    valor_bonus_total = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total a pagar (elegíveis × R$ 150)")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Safra M-10"
        verbose_name_plural = "Safras M-10"
        ordering = ['-mes_referencia']

    def __str__(self):
        return f"Safra {self.mes_referencia.strftime('%m/%Y')} - {self.total_instalados} contratos"


class ContratoM10(models.Model):
    """Cada contrato individual da safra"""
    STATUS_CHOICES = [
        ('ATIVO', 'Ativo'),
        ('CANCELADO', 'Cancelado'),
        ('DOWNGRADE', 'Downgrade'),
    ]

    venda = models.ForeignKey('Venda', on_delete=models.SET_NULL, null=True, blank=True, related_name='bonus_m10')
    numero_contrato = models.CharField(max_length=100, unique=True)
    numero_contrato_definitivo = models.CharField(max_length=100, null=True, blank=True, help_text="Preenchido automaticamente do FPD")
    ordem_servico = models.CharField(max_length=100, null=True, blank=True, unique=True, help_text="O.S para crossover com FPD/Churn")
    
    # Dados preenchidos automaticamente do FPD
    data_vencimento_fpd = models.DateField(null=True, blank=True, help_text="Data de vencimento da última fatura FPD")
    data_pagamento_fpd = models.DateField(null=True, blank=True, help_text="Data de pagamento da última fatura FPD")
    status_fatura_fpd = models.CharField(max_length=50, null=True, blank=True, help_text="Status da última fatura FPD (PAGO, ABERTO, etc)")
    valor_fatura_fpd = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Valor da última fatura FPD")
    nr_dias_atraso_fpd = models.IntegerField(null=True, blank=True, help_text="Dias em atraso da última fatura FPD")
    
    cliente_nome = models.CharField(max_length=255)
    cpf_cliente = models.CharField(max_length=18, null=True, blank=True, help_text="CPF do cliente")
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    data_instalacao = models.DateField()
    safra = models.CharField(max_length=7, null=True, blank=True, help_text="Mês/Ano da instalação (YYYY-MM)")
    plano_original = models.CharField(max_length=100)
    plano_atual = models.CharField(max_length=100)
    valor_plano = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status_contrato = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ATIVO')
    teve_downgrade = models.BooleanField(default=False, help_text="Marca manual se houve downgrade")
    data_cancelamento = models.DateField(null=True, blank=True)
    motivo_cancelamento = models.CharField(max_length=255, blank=True, null=True)
    elegivel_bonus = models.BooleanField(default=False, help_text="10 faturas pagas + sem downgrade + ativo")
    data_ultima_sincronizacao_fpd = models.DateTimeField(null=True, blank=True, help_text="Última sincronização com FPD")
    # Órfão: veio do FPD sem vínculo com pedido/venda; cobrança bloqueada até ter CPF
    orfao = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Contrato criado só pelo FPD, sem venda/CPF — aguarda vínculo para tratar",
    )
    status_tratamento = models.ForeignKey(
        'StatusCRM',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contratos_m10_tratamento',
        limit_choices_to={'tipo': 'Qualidade'},
        db_index=True,
        help_text="Status de tratamento do BO no módulo Qualidade (Cadastros Gerais → Status tipo Qualidade)",
    )
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato M-10"
        verbose_name_plural = "Contratos M-10"
        ordering = ['-data_instalacao']

    def __str__(self):
        return f"{self.numero_contrato} - {self.cliente_nome}"

    def save(self, *args, **kwargs):
        """Calcula safra automaticamente"""
        if self.data_instalacao:
            self.safra = self.data_instalacao.strftime('%Y-%m')
        
        super().save(*args, **kwargs)
    
    def calcular_vencimento_fatura_1(self):
        """Calcula o vencimento da primeira fatura segundo a regra:
        - Dias 1-28: data_instalacao + 25 dias
        - Dias 29-31: dia 26 do mês seguinte
        """
        dia_instalacao = self.data_instalacao.day
        
        if dia_instalacao <= 28:
            return self.data_instalacao + timedelta(days=25)
        else:
            # Dias 29, 30, 31: vencimento no dia 26 do mês seguinte
            mes_seguinte = self.data_instalacao + relativedelta(months=1)
            return mes_seguinte.replace(day=26)
    
    def calcular_data_disponibilidade(self, numero_fatura):
        """Calcula quando a fatura estará disponível no Nio (3-5 dias após instalação)
        Para simplificar, usamos 3 dias como mínimo
        """
        if numero_fatura == 1:
            return self.data_instalacao + timedelta(days=3)
        else:
            # Faturas subsequentes ficam disponíveis 3 dias antes do vencimento
            vencimento = self.calcular_vencimento_fatura_n(numero_fatura)
            return vencimento - timedelta(days=3)
    
    def calcular_vencimento_fatura_n(self, numero_fatura):
        """Calcula o vencimento da fatura N (1 a 10)
        Fatura 1: conforme regra especial
        Faturas 2-10: mesmo dia da fatura 1, mas nos meses subsequentes
        """
        if numero_fatura == 1:
            return self.calcular_vencimento_fatura_1()
        else:
            vencimento_fatura_1 = self.calcular_vencimento_fatura_1()
            return vencimento_fatura_1 + relativedelta(months=numero_fatura - 1)
    
    def criar_ou_atualizar_faturas(self):
        """Cria ou atualiza as 10 faturas com as datas de vencimento calculadas.

        Importante: se a fatura já foi sincronizada pela planilha FPD/SPD/TPD
        (``data_importacao_fpd`` preenchido), o vencimento da operadora prevalece
        e não é sobrescrito pelo cálculo instalação+25.
        """
        for i in range(1, 11):
            data_vencimento = self.calcular_vencimento_fatura_n(i)
            data_disponibilidade = self.calcular_data_disponibilidade(i)

            fatura, created = FaturaM10.objects.get_or_create(
                contrato=self,
                numero_fatura=i,
                defaults={
                    'data_vencimento': data_vencimento,
                    'data_disponibilidade': data_disponibilidade,
                    'valor': self.valor_plano,
                }
            )

            if created:
                continue

            # Planilha FPD/SPD/TPD é a fonte da verdade do vencimento real
            if fatura.data_importacao_fpd:
                if not fatura.data_disponibilidade:
                    fatura.data_disponibilidade = data_disponibilidade
                    fatura.save(update_fields=['data_disponibilidade', 'atualizado_em'])
                continue

            fatura.data_vencimento = data_vencimento
            fatura.data_disponibilidade = data_disponibilidade
            fatura.save(update_fields=['data_vencimento', 'data_disponibilidade', 'atualizado_em'])

    def calcular_elegibilidade(self):
        """Verifica se o contrato é elegível para bônus M-10.

        Nova regra: basta que todas as faturas cadastradas estejam pagas
        (qualquer quantidade) e o contrato esteja ativo. Mantemos o bloqueio
        para contratos com downgrade.

        Usa ``QuerySet.update`` para não disparar post_save (que recria faturas
        e apagaria o vencimento importado do FPD).
        """
        from django.utils import timezone

        total_faturas = self.faturas.count()
        faturas_pagas = self.faturas.filter(status='PAGO').count()

        # Se não existem faturas cadastradas, mas o status FPD está pago,
        # consideramos como 1/1 para fins de elegibilidade.
        if total_faturas == 0 and self.status_fatura_fpd and str(self.status_fatura_fpd).lower().startswith('paga'):
            total_faturas = 1
            faturas_pagas = 1

        self.elegivel_bonus = (
            total_faturas > 0 and
            faturas_pagas == total_faturas and
            not self.teve_downgrade and
            self.status_contrato == 'ATIVO'
        )
        ContratoM10.objects.filter(pk=self.pk).update(
            elegivel_bonus=self.elegivel_bonus,
            atualizado_em=timezone.now(),
        )
        return self.elegivel_bonus


class FaturaM10(models.Model):
    """10 faturas de cada contrato"""
    STATUS_CHOICES = [
        ('PAGO', 'Pago'),
        ('NAO_PAGO', 'Não Pago'),
        ('AGUARDANDO', 'Aguardando Arrecadação'),
        ('ATRASADO', 'Atrasado'),
        ('OUTROS', 'Outros'),
    ]
    
    ORIGEM_BUSCA_CHOICES = [
        ('MANUAL', 'Busca Manual'),
        ('AUTOMATICA', 'Busca Automática (Agendada)'),
        ('SAFRA', 'Busca por Safra'),
        ('INDIVIDUAL', 'Busca Individual'),
    ]
    
    STATUS_BUSCA_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]

    contrato = models.ForeignKey(ContratoM10, on_delete=models.CASCADE, related_name='faturas')
    numero_fatura = models.IntegerField(help_text="1 a 10")
    numero_fatura_operadora = models.CharField(max_length=100, blank=True, null=True, help_text="NR_FATURA da planilha")
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    data_vencimento = models.DateField()
    data_disponibilidade = models.DateField(null=True, blank=True, help_text="Data em que a fatura estará disponível no Nio")
    data_pagamento = models.DateField(null=True, blank=True)
    data_promessa_pagamento = models.DateField(
        null=True,
        blank=True,
        help_text="Data em que o cliente prometeu pagar (tratamento Qualidade)",
    )
    dias_atraso = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NAO_PAGO')
    # Origem/conferência do status (tratamento manual x planilha FPD)
    STATUS_ORIGEM_CHOICES = [
        ('FPD', 'Planilha FPD'),
        ('TRATAMENTO', 'Tratamento (manual)'),
        ('SISTEMA', 'Sistema'),
    ]
    CONFERENCIA_FPD_CHOICES = [
        ('', '—'),
        ('AGUARDANDO', 'Aguardando confirmação FPD'),
        ('CONFIRMADO', 'Confirmado na planilha FPD'),
        ('DIVERGENTE', 'Divergente da planilha FPD'),
    ]
    status_origem = models.CharField(
        max_length=20,
        choices=STATUS_ORIGEM_CHOICES,
        default='SISTEMA',
        db_index=True,
        help_text="Se o status atual veio do FPD ou foi informado no tratamento",
    )
    conferencia_fpd = models.CharField(
        max_length=20,
        choices=CONFERENCIA_FPD_CHOICES,
        blank=True,
        default='',
        db_index=True,
        help_text="Conferência do status de tratamento com a próxima importação FPD",
    )
    status_informado_tratamento = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Status que o BO informou no tratamento (para conferir no FPD)",
    )
    data_status_tratamento = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Quando o status foi alterado no tratamento",
    )
    # Campos mapeados diretamente do arquivo FPD
    id_contrato_fpd = models.CharField(max_length=100, blank=True, null=True, help_text="ID_CONTRATO do arquivo FPD")
    dt_pagamento_fpd = models.DateField(blank=True, null=True, help_text="DT_PAGAMENTO do arquivo FPD")
    ds_status_fatura_fpd = models.CharField(max_length=50, blank=True, null=True, help_text="DS_STATUS_FATURA do arquivo FPD")
    data_importacao_fpd = models.DateTimeField(blank=True, null=True, help_text="Data da última importação FPD")
    codigo_pix = models.TextField(blank=True, null=True, help_text="Código PIX Copia e Cola")
    codigo_barras = models.CharField(max_length=100, blank=True, null=True, help_text="Código de barras da fatura")
    pdf_url = models.URLField(max_length=500, blank=True, null=True, help_text="Link público do PDF da fatura")
    arquivo_pdf = models.FileField(upload_to='faturas_m10/%Y/%m/', blank=True, null=True, help_text="PDF da fatura")
    observacao = models.TextField(blank=True, null=True)
    
    # Campos de rastreamento de busca
    origem_busca = models.CharField(max_length=20, choices=ORIGEM_BUSCA_CHOICES, blank=True, null=True, help_text="Origem da última busca")
    status_busca = models.CharField(max_length=20, choices=STATUS_BUSCA_CHOICES, default='PENDENTE', help_text="Status da última busca")
    ultima_busca_em = models.DateTimeField(blank=True, null=True, help_text="Data/hora da última tentativa de busca")
    tempo_busca_segundos = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True, help_text="Tempo de execução da busca em segundos")
    tentativas_busca = models.IntegerField(default=0, help_text="Número de tentativas de busca")
    erro_busca = models.TextField(blank=True, null=True, help_text="Mensagem de erro da última busca")
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fatura M-10"
        verbose_name_plural = "Faturas M-10"
        ordering = ['contrato', 'numero_fatura']
        unique_together = ['contrato', 'numero_fatura']

    def __str__(self):
        return f"Fatura {self.numero_fatura} - {self.contrato.numero_contrato} - {self.status}"


class HistoricoEnvioQualidade(models.Model):
    """Log de envios/contatos do módulo Qualidade (WhatsApp, e-mail, ligação)."""
    CANAL_CHOICES = [
        ('WHATSAPP', 'WhatsApp'),
        ('EMAIL', 'E-mail'),
        ('LIGACAO', 'Ligação'),
        ('RESPOSTA', 'Resposta do cliente'),
    ]
    ORIGEM_CHOICES = [
        ('AUTO', 'Automático'),
        ('MANUAL', 'Manual'),
        ('SISTEMA', 'Sistema'),
    ]
    STATUS_ENTREGA_ACEITO = 'ACEITO'
    STATUS_ENTREGA_ENVIADO = 'ENVIADO'
    STATUS_ENTREGA_ENTREGUE = 'ENTREGUE'
    STATUS_ENTREGA_LIDO = 'LIDO'
    STATUS_ENTREGA_FALHOU = 'FALHOU'
    STATUS_ENTREGA_CHOICES = [
        (STATUS_ENTREGA_ACEITO, 'Aceito pela API'),
        (STATUS_ENTREGA_ENVIADO, 'Enviado'),
        (STATUS_ENTREGA_ENTREGUE, 'Entregue'),
        (STATUS_ENTREGA_LIDO, 'Lido'),
        (STATUS_ENTREGA_FALHOU, 'Falha de entrega'),
    ]

    contrato = models.ForeignKey(
        ContratoM10,
        on_delete=models.CASCADE,
        related_name='historico_envios_qualidade',
    )
    fatura = models.ForeignKey(
        FaturaM10,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='historico_envios_qualidade',
    )
    canal = models.CharField(max_length=20, choices=CANAL_CHOICES)
    origem = models.CharField(
        max_length=20,
        choices=ORIGEM_CHOICES,
        default='MANUAL',
        blank=True,
        help_text='AUTO = job 10:00; MANUAL = tela Qualidade; SISTEMA = webhook/botões',
    )
    template_nome = models.CharField(
        max_length=120,
        blank=True,
        default='',
        help_text='Nome do template Meta quando canal WhatsApp usa template',
    )
    destinatario = models.CharField(max_length=255)
    mensagem = models.TextField(blank=True, default='')
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='envios_qualidade',
    )
    sucesso = models.BooleanField(default=True)
    erro = models.TextField(null=True, blank=True)
    message_id = models.CharField(
        max_length=191,
        blank=True,
        default='',
        help_text='wamid / messageId retornado no aceite do envio (correlação com webhook da Meta)',
    )
    status_entrega = models.CharField(
        max_length=20,
        choices=STATUS_ENTREGA_CHOICES,
        blank=True,
        default='',
        help_text='ACEITO = HTTP 200 da API; ENVIADO/ENTREGUE/LIDO/FALHOU = webhook posterior',
    )
    erro_codigo = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text='Código Meta (ex.: 131048 spam, 131047 janela 24h)',
    )
    status_atualizado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Histórico de Envio Qualidade"
        verbose_name_plural = "Históricos de Envio Qualidade"
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['contrato', 'canal', '-criado_em']),
            models.Index(fields=['-criado_em', 'canal', 'origem']),
            models.Index(fields=['message_id'], name='crm_app_his_msgid_idx'),
        ]

    def __str__(self) -> str:
        return f"{self.canal} → {self.destinatario} ({self.criado_em:%d/%m/%Y %H:%M})"


class HistoricoBuscaFatura(models.Model):
    """Histórico detalhado de execuções de busca de faturas"""
    TIPO_BUSCA_CHOICES = [
        ('AUTOMATICA', 'Busca Automática (Agendada)'),
        ('SAFRA', 'Busca por Safra'),
        ('INDIVIDUAL', 'Busca Individual'),
        ('RETRY', 'Retry de Erro'),
        ('MATCH_NOTURNO', 'Match noturno Nio (22h–7h)'),
    ]
    
    STATUS_CHOICES = [
        ('EM_ANDAMENTO', 'Em Andamento'),
        ('CONCLUIDA', 'Concluída'),
        ('ERRO', 'Erro'),
        ('CANCELADA', 'Cancelada'),
    ]
    
    tipo_busca = models.CharField(max_length=20, choices=TIPO_BUSCA_CHOICES, help_text="Tipo de execução")
    safra = models.CharField(max_length=7, blank=True, null=True, help_text="Safra processada (formato YYYY-MM)")
    usuario = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True, help_text="Usuário que iniciou")
    
    # Métricas de execução
    inicio_em = models.DateTimeField(auto_now_add=True)
    termino_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # Estatísticas
    total_contratos = models.IntegerField(default=0)
    total_faturas = models.IntegerField(default=0)
    faturas_sucesso = models.IntegerField(default=0)
    faturas_erro = models.IntegerField(default=0)
    faturas_nao_disponiveis = models.IntegerField(default=0)
    faturas_retry = models.IntegerField(default=0)
    
    # Performance
    tempo_medio_fatura = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True, help_text="Tempo médio por fatura (segundos)")
    tempo_min_fatura = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    tempo_max_fatura = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    
    # Status e logs
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EM_ANDAMENTO')
    mensagem = models.TextField(blank=True, null=True, help_text="Mensagem final ou erro")
    logs = models.JSONField(blank=True, null=True, help_text="Logs detalhados da execução")
    
    class Meta:
        verbose_name = "Histórico de Busca de Fatura"
        verbose_name_plural = "Histórico de Buscas de Faturas"
        ordering = ['-inicio_em']
    
    def __str__(self):
        return f"{self.get_tipo_busca_display()} - {self.inicio_em.strftime('%d/%m/%Y %H:%M')}"


class ImportacaoAgendamento(models.Model):
    """Modelo para armazenar importaÃ§Ãµes de Agendamentos Futuros e Tarefas Fechadas"""
    sg_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="UF")
    nm_municipio = models.CharField(max_length=255, null=True, blank=True, verbose_name="MunicÃ­pio")
    indicador = models.CharField(max_length=255, null=True, blank=True, verbose_name="Indicador")
    cd_nrba = models.CharField(max_length=255, null=True, blank=True, verbose_name="CÃ³digo NRBA")
    st_ba = models.CharField(max_length=255, null=True, blank=True, verbose_name="Status BA")
    cd_encerramento = models.CharField(max_length=255, null=True, blank=True, verbose_name="CÃ³digo Encerramento")
    desc_observacao = models.TextField(null=True, blank=True, verbose_name="ObservaÃ§Ã£o")
    desc_macro_atividade = models.CharField(max_length=255, null=True, blank=True, verbose_name="Macro Atividade")
    ds_atividade = models.CharField(max_length=255, null=True, blank=True, verbose_name="Atividade")
    dt_abertura_ba = models.DateField(null=True, blank=True, verbose_name="Data Abertura BA")
    dt_inicio_agendamento = models.DateTimeField(null=True, blank=True, verbose_name="InÃ­cio Agendamento")
    dt_fim_agendamento = models.DateTimeField(null=True, blank=True, verbose_name="Fim Agendamento")
    dt_inicio_execucao_real = models.DateTimeField(null=True, blank=True, verbose_name="InÃ­cio ExecuÃ§Ã£o Real")
    dt_fim_execucao_real = models.DateTimeField(null=True, blank=True, verbose_name="Fim ExecuÃ§Ã£o Real")
    nr_ordem = models.CharField(max_length=255, null=True, blank=True, verbose_name="NÃºmero Ordem")
    nr_ordem_venda = models.CharField(max_length=255, null=True, blank=True, verbose_name="Ordem Venda")
    dt_execucao_particao = models.DateField(null=True, blank=True, verbose_name="Data ExecuÃ§Ã£o PartiÃ§Ã£o")
    anomes = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/MÃªs")
    cd_sap_original = models.CharField(max_length=255, null=True, blank=True, verbose_name="SAP Original")
    cd_rede = models.CharField(max_length=255, null=True, blank=True, verbose_name="CÃ³digo Rede")
    nm_pdv_rel = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome PDV")
    rede = models.CharField(max_length=255, null=True, blank=True, verbose_name="Rede")
    gp_canal = models.CharField(max_length=255, null=True, blank=True, verbose_name="Grupo Canal")
    sg_gerencia = models.CharField(max_length=255, null=True, blank=True, verbose_name="Sigla GerÃªncia")
    nm_gc = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome GC")
    dt_agendamento = models.DateField(null=True, blank=True, verbose_name="Data Agendamento")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "ImportaÃ§Ã£o Agendamento"
        verbose_name_plural = "ImportaÃ§Ãµes Agendamentos"
        ordering = ["-dt_agendamento", "-criado_em"]
        indexes = [
            models.Index(fields=["cd_nrba"]),
            models.Index(fields=["nr_ordem"]),
            models.Index(fields=["dt_agendamento"]),
            models.Index(fields=["anomes"]),
        ]

    def __str__(self):
        return f"BA {self.cd_nrba} - {self.dt_agendamento or 'Sem data'}"

class ImportacaoRecompra(models.Model):
    """Modelo para importação de dados de Recompra"""
    
    # Identificadores
    ds_anomes = models.CharField(max_length=50, null=True, blank=True, verbose_name="Ano/Mês")
    nr_ordem = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="Número Ordem")
    
    # Datas
    dt_venda_particao = models.DateField(null=True, blank=True, verbose_name="Data Venda Partição")
    dt_encerramento = models.DateField(null=True, blank=True, verbose_name="Data Encerramento")
    dt_inicio_ativo = models.DateField(null=True, blank=True, verbose_name="Data Início Ativo")
    
    # Status e Segmento
    st_ordem = models.CharField(max_length=255, null=True, blank=True, verbose_name="Status Ordem")
    nm_seg = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome Segmento")
    resultado = models.CharField(max_length=255, null=True, blank=True, verbose_name="Resultado")
    
    # Localização
    sg_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="UF")
    nm_municipio = models.CharField(max_length=255, null=True, blank=True, verbose_name="Município")
    nm_bairro = models.CharField(max_length=255, null=True, blank=True, verbose_name="Bairro")
    nr_cep = models.CharField(max_length=20, null=True, blank=True, verbose_name="CEP")
    nr_cep_base = models.CharField(max_length=20, null=True, blank=True, verbose_name="CEP Base")
    
    # Complementos de Endereço
    nr_complemento1_base = models.CharField(max_length=255, null=True, blank=True, verbose_name="Complemento 1")
    nr_complemento2_base = models.CharField(max_length=255, null=True, blank=True, verbose_name="Complemento 2")
    nr_complemento3_base = models.CharField(max_length=255, null=True, blank=True, verbose_name="Complemento 3")
    
    # SAP e Transações
    cd_sap_pdv = models.CharField(max_length=255, null=True, blank=True, verbose_name="SAP PDV")
    cd_tr_vdd = models.CharField(max_length=255, null=True, blank=True, verbose_name="Transação Vendedor")
    
    # Organização
    nm_diretoria = models.CharField(max_length=255, null=True, blank=True, verbose_name="Diretoria")
    nm_regional = models.CharField(max_length=255, null=True, blank=True, verbose_name="Regional")
    cd_rede = models.CharField(max_length=255, null=True, blank=True, verbose_name="Código Rede")
    gp_canal = models.CharField(max_length=255, null=True, blank=True, verbose_name="Grupo Canal")
    nm_pdv_rel = models.CharField(max_length=255, null=True, blank=True, verbose_name="PDV Relacionado")
    nm_gc = models.CharField(max_length=255, null=True, blank=True, verbose_name="Gerente de Conta")
    
    # Extras
    GERENCIA = models.CharField(max_length=255, null=True, blank=True, verbose_name="Gerência")
    REDE = models.CharField(max_length=255, null=True, blank=True, verbose_name="Rede")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")
    
    class Meta:
        verbose_name = "Importação Recompra"
        verbose_name_plural = "Importações Recompra"
        ordering = ["-dt_venda_particao", "-created_at"]
        indexes = [
            models.Index(fields=["nr_ordem"]),
            models.Index(fields=["ds_anomes"]),
            models.Index(fields=["dt_venda_particao"]),
            models.Index(fields=["sg_uf"]),
        ]
    
    def __str__(self):
        return f"Recompra {self.nr_ordem} - {self.nm_municipio or 'Sem município'}"


class ImportacaoFPD(models.Model):
    """Modelo para importação de dados FPD / SPD / TPD (planilha operadora)."""

    MATCH_STATUS_CHOICES = [
        ('MATCHED', 'Vinculado ao CRM'),
        ('FALTA_CRM', 'Falta no CRM'),
        ('ORFAO', 'Órfão (sem CPF/venda)'),
    ]
    INDICADOR_CHOICES = [
        ('FPD', '1ª fatura (FPD)'),
        ('SPD', '2ª fatura (SPD)'),
        ('TPD', '3ª fatura (TPD)'),
    ]

    # Chaves de matching
    nr_ordem = models.CharField(max_length=100, db_index=True, help_text="Número de Ordem (O.S)")
    numero_os = models.CharField(max_length=100, null=True, blank=True, db_index=True, help_text="Alternativa NR_OS")
    id_contrato = models.CharField(max_length=100, help_text="ID_CONTRATO do arquivo FPD")

    # FPD / SPD / TPD
    indicador = models.CharField(
        max_length=3,
        choices=INDICADOR_CHOICES,
        default='FPD',
        db_index=True,
        help_text="FPD=1ª, SPD=2ª, TPD=3ª fatura",
    )
    numero_fatura_m10 = models.PositiveSmallIntegerField(
        default=1,
        db_index=True,
        help_text="Número da fatura no M-10 (1/2/3)",
    )

    # Dados da fatura
    nr_fatura = models.CharField(max_length=100, help_text="NR_FATURA do arquivo FPD")
    dt_venc_orig = models.DateField(help_text="Data de vencimento original")
    dt_pagamento = models.DateField(null=True, blank=True, help_text="Data de pagamento")
    nr_dias_atraso = models.IntegerField(default=0, help_text="Número de dias em atraso")
    ds_status_fatura = models.CharField(max_length=50, help_text="Status da fatura (PAGO, ABERTO, VENCIDO, etc)")
    ds_sit_fatura = models.CharField(
        max_length=20,
        blank=True,
        default='',
        db_index=True,
        help_text="ABERTA / FECHADA (planilha)",
    )
    faixa = models.CharField(max_length=40, blank=True, default='', help_text="Faixa de atraso da planilha")
    vl_fatura = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Valor da fatura")

    # Dados auxiliares para investigar "faltam no CRM"
    municipio = models.CharField(max_length=120, blank=True, default='')
    uf = models.CharField(max_length=2, blank=True, default='')
    cd_vendedor_original = models.CharField(max_length=50, blank=True, default='')
    nm_pdv = models.CharField(max_length=120, blank=True, default='')
    nm_gc = models.CharField(max_length=120, blank=True, default='')
    # Segmento da planilha (Varejo / Empresarial) — coluna nm_seg
    nm_seg = models.CharField(
        max_length=40,
        blank=True,
        default='',
        db_index=True,
        help_text='Segmento do cliente na planilha (Varejo / Empresarial)',
    )
    match_status = models.CharField(
        max_length=20,
        choices=MATCH_STATUS_CHOICES,
        default='MATCHED',
        db_index=True,
        help_text="Resultado do vínculo com ContratoM10/Venda",
    )

    # Vínculo com ContratoM10
    contrato_m10 = models.ForeignKey(
        ContratoM10,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='importacoes_fpd',
    )

    # Timestamps
    importada_em = models.DateTimeField(auto_now_add=True, help_text="Data da importação")
    atualizada_em = models.DateTimeField(auto_now=True, help_text="Data da última atualização")

    class Meta:
        verbose_name = "Importação FPD"
        verbose_name_plural = "Importações FPD"
        ordering = ["-importada_em"]
        indexes = [
            models.Index(fields=["nr_ordem"]),
            models.Index(fields=["id_contrato"]),
            models.Index(fields=["ds_status_fatura"]),
            models.Index(fields=["indicador", "ds_sit_fatura"]),
            models.Index(fields=["match_status", "indicador"]),
            models.Index(fields=["nr_ordem", "indicador"]),
        ]

    def __str__(self):
        return f"{self.indicador} {self.nr_ordem} - Fatura {self.nr_fatura}"


class LogImportacaoFPD(models.Model):
    """Log de importações FPD"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    sucesso = models.IntegerField(default=0)
    erros = models.IntegerField(default=0)
    total_contratos_nao_encontrados = models.IntegerField(default=0)
    total_valor_importado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    exemplos_nao_encontrados = models.TextField(blank=True, null=True)
    data_importacao = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Log Importação FPD"
        verbose_name_plural = "Logs Importação FPD"
        ordering = ["-data_importacao"]
    
    def __str__(self):
        return f"Log FPD {self.nome_arquivo} - {self.status}"
    
    def calcular_duracao(self):
        """Calcula duração em segundos entre início e fim (usa iniciado_em/data_importacao e finalizado_em)."""
        inicio = getattr(self, 'iniciado_em', None) or getattr(self, 'data_importacao', None)
        fim = getattr(self, 'finalizado_em', None)
        if not fim:
            try:
                from django.utils import timezone
                fim = timezone.now()
            except Exception:
                pass
        if inicio and fim and hasattr(fim, '__sub__'):
            self.duracao_segundos = int((fim - inicio).total_seconds())


class LogImportacaoOSAB(models.Model):
    """Log de importações OSAB"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
        ('REVERTIDO', 'Revertido'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas OSAB
    total_registros = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    criados = models.IntegerField(default=0)
    atualizados = models.IntegerField(default=0)
    vendas_encontradas = models.IntegerField(default=0)
    ja_corretos = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    # Flags de controle
    enviar_whatsapp = models.BooleanField(default=True)
    revertido_em = models.DateTimeField(blank=True, null=True)
    revertido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='importacoes_osab_revertidas',
    )
    
    class Meta:
        verbose_name = "Log Importação OSAB"
        verbose_name_plural = "Logs Importação OSAB"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class LogImportacaoOSABSnapshotVenda(models.Model):
    """Estado da venda antes das alterações de uma importação OSAB (para reversão)."""

    ORIGEM_PLANILHA = 'PLANILHA'
    ORIGEM_AUSENTE_OSAB = 'AUSENTE_OSAB'
    ORIGEM_CHOICES = [
        (ORIGEM_PLANILHA, 'Planilha OSAB'),
        (ORIGEM_AUSENTE_OSAB, 'CRM ausente na base OSAB'),
    ]

    log = models.ForeignKey(
        LogImportacaoOSAB,
        on_delete=models.CASCADE,
        related_name='snapshots_vendas',
    )
    venda = models.ForeignKey('Venda', on_delete=models.CASCADE, related_name='snapshots_importacao_osab')
    ordem_servico = models.CharField(max_length=50, blank=True, default='')
    origem = models.CharField(max_length=20, choices=ORIGEM_CHOICES)
    valores_antes = models.JSONField(default=dict)

    class Meta:
        verbose_name = "Snapshot reversão OSAB"
        verbose_name_plural = "Snapshots reversão OSAB"
        constraints = [
            models.UniqueConstraint(
                fields=['log', 'venda'],
                name='uniq_osab_snapshot_log_venda',
            ),
        ]

    def __str__(self):
        return f"Log OSAB #{self.log_id} — venda #{self.venda_id}"


class LogImportacaoLegado(models.Model):
    """Log de importações de Vendas Legado (Históricas)"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas Legado
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    vendas_criadas = models.IntegerField(default=0)
    vendas_atualizadas = models.IntegerField(default=0)
    clientes_criados = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação Legado"
        verbose_name_plural = "Logs Importação Legado"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class LogImportacaoAgendamento(models.Model):
    """Log de importações de Agendamentos"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas Agendamento
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    agendamentos_criados = models.IntegerField(default=0)
    agendamentos_atualizados = models.IntegerField(default=0)
    nao_encontrados = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação Agendamento"
        verbose_name_plural = "Logs Importação Agendamento"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class ImportacaoChurn(models.Model):
    """Modelo para importação de dados de CHURN da operadora"""
    
    # Localização
    uf = models.CharField(max_length=2, null=True, blank=True)
    produto = models.CharField(max_length=255, null=True, blank=True)
    
    # Vendedor
    matricula_vendedor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Matrícula do Vendedor")
    cd_tr_vdd_original = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="CD TR VDD original (planilha churn)",
    )
    
    # Gestão
    gv = models.CharField(max_length=255, null=True, blank=True)
    sap_principal_fim = models.CharField(max_length=255, null=True, blank=True)
    gestao = models.CharField(max_length=255, null=True, blank=True)
    st_regional = models.CharField(max_length=255, null=True, blank=True)
    gc = models.CharField(max_length=255, null=True, blank=True)
    
    # Identificação
    numero_pedido = models.CharField(max_length=50, null=True, blank=True, unique=True, verbose_name="Número do Pedido")
    nr_ordem = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Número de Ordem")
    
    # Datas
    dt_gross = models.DateField(null=True, blank=True, verbose_name="Data Gross")
    anomes_gross = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/Mês Gross")
    dt_retirada = models.DateField(null=True, blank=True, verbose_name="Data Retirada")
    anomes_retirada = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/Mês Retirada")
    
    # Outros
    grupo_unidade = models.CharField(max_length=255, null=True, blank=True)
    codigo_sap = models.CharField(max_length=50, null=True, blank=True)
    municipio = models.CharField(max_length=255, null=True, blank=True)
    tipo_retirada = models.CharField(max_length=255, null=True, blank=True)
    motivo_retirada = models.CharField(max_length=255, null=True, blank=True)
    submotivo_retirada = models.CharField(max_length=255, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    desc_apelido = models.CharField(max_length=255, null=True, blank=True)
    nr_velocidade = models.CharField(max_length=50, null=True, blank=True, verbose_name="Velocidade/Plano (ex: 500MB, 700MB, 1GB)")

    class Meta:
        verbose_name = "Importação Churn"
        verbose_name_plural = "Importações Churn"
        db_table = "crm_importacao_churn"
    
    def __str__(self):
        return f"Churn {self.numero_pedido} - {self.dt_retirada or 'Sem data'}"


class LogImportacaoChurn(models.Model):
    """Log de importações CHURN"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Sucesso Parcial'),
    ]
    
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='logs_importacao_churn'
    )
    nome_arquivo = models.CharField(max_length=255, help_text="Nome do arquivo importado")
    tamanho_arquivo = models.IntegerField(help_text="Tamanho do arquivo em bytes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PROCESSANDO')
    
    # Timestamps
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    duracao_segundos = models.IntegerField(null=True, blank=True, help_text="Duração em segundos")
    
    # Estatísticas
    total_linhas = models.IntegerField(default=0, help_text="Total de linhas no arquivo")
    total_processadas = models.IntegerField(default=0, help_text="Linhas processadas com sucesso")
    total_erros = models.IntegerField(default=0, help_text="Linhas com erro")
    total_contratos_cancelados = models.IntegerField(default=0, help_text="Contratos M10 cancelados")
    total_contratos_reativados = models.IntegerField(default=0, help_text="Contratos M10 reativados")
    total_nao_encontrados = models.IntegerField(default=0, help_text="O.S não encontradas no M10")
    
    # Detalhes
    mensagem_erro = models.TextField(null=True, blank=True, help_text="Mensagem de erro se houver")
    detalhes_json = models.JSONField(default=dict, blank=True, help_text="Detalhes adicionais em JSON")
    
    class Meta:
        verbose_name = "Log Importação CHURN"
        verbose_name_plural = "Logs Importações CHURN"
        ordering = ["-iniciado_em"]
        indexes = [
            models.Index(fields=["-iniciado_em"]),
            models.Index(fields=["status"]),
        ]
    
    def __str__(self):
        return f"Log CHURN {self.nome_arquivo} - {self.get_status_display()}"


class LogImportacaoDFV(models.Model):
    """Log de importações DFV (Dados do Faturamento de Vendas)"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas DFV
    total_registros = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    sucesso = models.IntegerField(default=0)
    erros = models.IntegerField(default=0)
    total_valor_importado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    contratos_nao_encontrados = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação DFV"
        verbose_name_plural = "Logs Importação DFV"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class LogImportacaoGdpPreco(models.Model):
    """Log de importações da planilha GDP (preços Nio por município)."""

    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    vigente = models.BooleanField(
        default=False,
        help_text='Importação ativa usada para consulta de preços.',
    )
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)

    total_municipios = models.IntegerField(default=0)
    total_precos = models.IntegerField(default=0)
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        db_table = 'crm_log_importacao_gdp_preco'
        verbose_name = 'Log Importação GDP Preços'
        verbose_name_plural = 'Logs Importação GDP Preços'
        ordering = ['-iniciado_em']

    def calcular_duracao(self) -> None:
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])

    def __str__(self) -> str:
        return f'{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime("%d/%m/%Y %H:%M")})'


class GdpPrecoMunicipio(models.Model):
    """Preço de plano Nio por município, meio de pagamento e velocidade (fonte: GDP)."""

    MEIO_PAGAMENTO_CHOICES = [
        ('CARTAO', 'Cartão de crédito'),
        ('DACC', 'Débito automático'),
        ('BOLETO', 'Boleto'),
    ]

    log_importacao = models.ForeignKey(
        LogImportacaoGdpPreco,
        on_delete=models.CASCADE,
        related_name='precos',
    )
    uf = models.CharField(max_length=2, db_index=True)
    municipio = models.CharField(max_length=120, db_index=True)
    municipio_normalizado = models.CharField(max_length=120, db_index=True)
    cod_ibge = models.CharField(max_length=10, blank=True, null=True, db_index=True)
    meio_pagamento = models.CharField(max_length=10, choices=MEIO_PAGAMENTO_CHOICES, db_index=True)
    velocidade_mbps = models.PositiveIntegerField(db_index=True)
    indice_oferta = models.PositiveSmallIntegerField(default=0)
    valor = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'crm_gdp_preco_municipio'
        verbose_name = 'Preço GDP por município'
        verbose_name_plural = 'Preços GDP por município'
        indexes = [
            models.Index(fields=['municipio_normalizado', 'uf', 'meio_pagamento']),
            models.Index(fields=['cod_ibge', 'meio_pagamento']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'log_importacao',
                    'uf',
                    'municipio_normalizado',
                    'meio_pagamento',
                    'velocidade_mbps',
                    'indice_oferta',
                ],
                name='uniq_gdp_preco_municipio_oferta',
            ),
        ]

    def __str__(self) -> str:
        return (
            f'{self.municipio}/{self.uf} {self.velocidade_mbps}Mbps '
            f'{self.meio_pagamento} R${self.valor}'
        )


class LogImportacaoRecompra(models.Model):
    """Log de importações Recompra"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas Recompra
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    registros_criados = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação Recompra"
        verbose_name_plural = "Logs Importação Recompra"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class RecordApoia(models.Model):
    """Repositório de arquivos Record Apoia - Acesso público para todos os usuários"""
    
    TIPO_ARQUIVO_CHOICES = [
        ('PDF', 'PDF'),
        ('WORD', 'Word (DOC/DOCX)'),
        ('EXCEL', 'Excel (XLS/XLSX)'),
        ('IMAGEM', 'Imagem (JPG/PNG/GIF)'),
        ('VIDEO', 'Vídeo (MP4/AVI/MOV)'),
        ('OUTRO', 'Outro'),
    ]
    
    # Dados do arquivo
    arquivo = models.FileField(
        upload_to='record_apoia/%Y/%m/%d/',
        help_text='Arquivo a ser armazenado'
    )
    nome_original = models.CharField(
        max_length=255,
        help_text='Nome original do arquivo no upload'
    )
    tipo_arquivo = models.CharField(
        max_length=20,
        choices=TIPO_ARQUIVO_CHOICES,
        help_text='Tipo/categoria do arquivo'
    )
    tamanho_bytes = models.BigIntegerField(
        default=0,
        help_text='Tamanho do arquivo em bytes'
    )
    
    # Metadados e organização
    titulo = models.CharField(
        max_length=255,
        help_text='Título/descrição do arquivo'
    )
    descricao = models.TextField(
        blank=True,
        null=True,
        help_text='Descrição detalhada (opcional)'
    )
    categoria = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Categoria/tag para organização (ex: Manual, Treinamento, Documentação)'
    )
    tags = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text='Tags separadas por vírgula (ex: urgente, importante, tutorial)'
    )
    
    # Controle
    usuario_upload = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='arquivos_uploadados',
        help_text='Usuário que fez o upload'
    )
    data_upload = models.DateTimeField(
        auto_now_add=True,
        help_text='Data e hora do upload'
    )
    downloads_count = models.IntegerField(
        default=0,
        help_text='Contador de downloads'
    )
    ativo = models.BooleanField(
        default=True,
        help_text='Se False, arquivo está oculto (soft delete)'
    )
    url_externa = models.TextField(
        blank=True,
        null=True,
        help_text='URL de backup (R2) para sobreviver a redeploys sem volume persistente',
    )
    
    class Meta:
        verbose_name = "Arquivo Record Apoia"
        verbose_name_plural = "Arquivos Record Apoia"
        ordering = ['-data_upload']
        indexes = [
            models.Index(fields=['tipo_arquivo']),
            models.Index(fields=['categoria']),
            models.Index(fields=['data_upload']),
            models.Index(fields=['ativo']),
        ]
    
    def __str__(self):
        return f"{self.titulo} ({self.get_tipo_arquivo_display()})"
    
    def save(self, *args, **kwargs):
        """Determina automaticamente o tipo_arquivo baseado na extensão do arquivo"""
        if not self.tipo_arquivo or self.tipo_arquivo == '':
            if self.arquivo and self.arquivo.name:
                ext = self.arquivo.name.split('.')[-1].lower()
                if ext in ['pdf']:
                    self.tipo_arquivo = 'PDF'
                elif ext in ['doc', 'docx']:
                    self.tipo_arquivo = 'WORD'
                elif ext in ['xls', 'xlsx']:
                    self.tipo_arquivo = 'EXCEL'
                elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                    self.tipo_arquivo = 'IMAGEM'
                elif ext in ['mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm']:
                    self.tipo_arquivo = 'VIDEO'
                else:
                    self.tipo_arquivo = 'OUTRO'
            elif self.nome_original:
                ext = self.nome_original.split('.')[-1].lower()
                if ext in ['pdf']:
                    self.tipo_arquivo = 'PDF'
                elif ext in ['doc', 'docx']:
                    self.tipo_arquivo = 'WORD'
                elif ext in ['xls', 'xlsx']:
                    self.tipo_arquivo = 'EXCEL'
                elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                    self.tipo_arquivo = 'IMAGEM'
                elif ext in ['mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm']:
                    self.tipo_arquivo = 'VIDEO'
                else:
                    self.tipo_arquivo = 'OUTRO'
            else:
                self.tipo_arquivo = 'OUTRO'
        
        # Atualizar tamanho_bytes se necessário
        if self.arquivo:
            try:
                self.tamanho_bytes = self.arquivo.size
            except (FileNotFoundError, IOError, OSError, AttributeError):
                pass  # Manter valor atual se não conseguir ler
        
        super().save(*args, **kwargs)
    
    def formatar_tamanho(self):
        """Retorna o tamanho formatado (KB, MB, GB)"""
        tamanho = self.tamanho_bytes
        for unidade in ['B', 'KB', 'MB', 'GB']:
            if tamanho < 1024.0:
                return f"{tamanho:.2f} {unidade}"
            tamanho /= 1024.0
        return f"{tamanho:.2f} TB"


class DocumentoConhecimentoIA(models.Model):
    """
    Documentos (PDF, Excel, PPT) enviados pela área interna para alimentar
    a base de conhecimento da IA do bot WhatsApp. O texto extraído é incluído no contexto.
    """
    titulo = models.CharField(max_length=255, help_text="Título do documento")
    arquivo = models.FileField(
        upload_to='conhecimento_ia/%Y/%m/',
        help_text="Arquivo (PDF, XLS/XLSX, PPT/PPTX)"
    )
    nome_original = models.CharField(max_length=255, blank=True)
    tipo = models.CharField(
        max_length=20,
        choices=[('PDF', 'PDF'), ('EXCEL', 'Excel'), ('PPT', 'PowerPoint'), ('OUTRO', 'Outro')],
        default='OUTRO'
    )
    conteudo_extraido = models.TextField(
        blank=True,
        help_text="Texto extraído do arquivo para a IA (preenchido no processamento)"
    )
    ativo = models.BooleanField(default=True, help_text="Se inativo, não entra no contexto da IA")
    data_upload = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documentos_conhecimento_ia'
    )

    class Meta:
        db_table = 'crm_documento_conhecimento_ia'
        verbose_name = "Documento Conhecimento IA"
        verbose_name_plural = "Documentos Conhecimento IA"
        ordering = ['-data_upload']


class UrlConhecimentoIA(models.Model):
    """
    URLs de sites cujo conteúdo foi extraído para alimentar a base de conhecimento da IA.
    """
    url = models.URLField(max_length=2000, help_text="URL da página")
    titulo = models.CharField(max_length=255, help_text="Título ou descrição")
    conteudo_extraido = models.TextField(
        blank=True,
        help_text="Texto extraído da página (e de links do mesmo domínio, se crawlou)"
    )
    ativo = models.BooleanField(default=True, help_text="Se inativo, não entra no contexto da IA")
    data_upload = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='urls_conhecimento_ia'
    )

    class Meta:
        db_table = 'crm_url_conhecimento_ia'
        verbose_name = "URL Conhecimento IA"
        verbose_name_plural = "URLs Conhecimento IA"
        ordering = ['-data_upload']


class ImportacaoEstabelecimentoCNPJ(models.Model):
    """
    Modelo para importação de dados ESTABELE da Receita Federal (CNPJ).
    Layout oficial: 30 colunas, separador ;, sem cabeçalho.
    """
    # Identificação CNPJ
    cnpj_raiz = models.CharField(max_length=8, db_index=True, help_text="8 primeiros dígitos do CNPJ")
    cnpj_ordem = models.CharField(max_length=4, help_text="Dígitos 9-12 do CNPJ")
    cnpj_dv = models.CharField(max_length=2, help_text="Dígitos verificadores")
    cnpj_completo = models.CharField(max_length=14, db_index=True, blank=True, help_text="CNPJ completo (raiz+ordem+dv)")

    identificador_matriz_filial = models.CharField(max_length=1, blank=True)  # 1=Matriz, 2=Filial
    nome_fantasia = models.CharField(max_length=255, blank=True)
    situacao_cadastral = models.CharField(max_length=2, db_index=True, blank=True)  # 02=Ativa
    data_situacao_cadastral = models.CharField(max_length=8, blank=True)  # AAAAMMDD
    motivo_situacao_cadastral = models.CharField(max_length=2, blank=True)
    nome_cidade_exterior = models.CharField(max_length=255, blank=True)
    codigo_pais = models.CharField(max_length=3, blank=True)
    data_inicio_atividade = models.CharField(max_length=8, blank=True)  # AAAAMMDD
    cnae_fiscal = models.CharField(max_length=7, db_index=True, blank=True)  # CNAE principal
    cnae_secundarios = models.TextField(blank=True)  # Lista separada por vírgula

    # Endereço
    tipo_logradouro = models.CharField(max_length=50, blank=True)
    logradouro = models.CharField(max_length=255, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=255, blank=True)
    bairro = models.CharField(max_length=255, blank=True)
    cep = models.CharField(max_length=8, blank=True)
    uf = models.CharField(max_length=2, db_index=True, blank=True)
    codigo_municipio = models.CharField(max_length=7, db_index=True, blank=True)

    # Município (nome): preenchido por cruzamento CEP -> CepLocalidade ou codigo_municipio -> IBGE
    nome_municipio = models.CharField(max_length=255, null=True, blank=True, verbose_name='Nome do município')

    # Contato
    ddd_telefone_1 = models.CharField(max_length=3, blank=True)
    telefone_1 = models.CharField(max_length=20, blank=True)
    ddd_telefone_2 = models.CharField(max_length=3, blank=True)
    telefone_2 = models.CharField(max_length=20, blank=True)
    ddd_fax = models.CharField(max_length=3, blank=True)
    fax = models.CharField(max_length=20, blank=True)
    email = models.CharField(max_length=255, blank=True)  # CharField para aceitar valores diversos da Receita

    # Situação especial
    situacao_especial = models.CharField(max_length=255, blank=True)
    data_situacao_especial = models.CharField(max_length=8, blank=True)

    importada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'crm_importacao_estabelecimento_cnpj'
        verbose_name = "Estabelecimento CNPJ (Receita Federal)"
        verbose_name_plural = "Estabelecimentos CNPJ (Receita Federal)"
        ordering = ['-importada_em']
        indexes = [
            models.Index(fields=['cnpj_completo']),
            models.Index(fields=['cnae_fiscal', 'codigo_municipio']),
            models.Index(fields=['situacao_cadastral']),
        ]

    def __str__(self):
        return f"{self.cnpj_completo or self.cnpj_raiz} - {self.nome_fantasia or '(sem nome)'}"


class CepLocalidade(models.Model):
    """
    Base local CEP -> cidade/UF para consulta rápida.
    Preenchida por importação de CSV (ex.: CEP Aberto, Base dos Dados, etc.).
    """
    cep = models.CharField(max_length=8, unique=True, db_index=True, help_text="CEP apenas dígitos (8)")
    localidade = models.CharField(max_length=255, help_text="Nome do município/cidade")
    uf = models.CharField(max_length=2, db_index=True, help_text="Sigla UF")

    class Meta:
        db_table = 'crm_cep_localidade'
        verbose_name = "CEP Localidade"
        verbose_name_plural = "CEP Localidades"
        ordering = ['cep']

    def __str__(self):
        return f"{self.cep} - {self.localidade}/{self.uf}"


class LogImportacaoEstabelecimentoCNPJ(models.Model):
    """Log de importações de arquivos ESTABELE da Receita Federal"""

    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.BigIntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)

    total_linhas = models.IntegerField(default=0)
    total_importadas = models.IntegerField(default=0)
    total_erros = models.IntegerField(default=0)

    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        db_table = 'crm_log_importacao_estabelecimento_cnpj'
        verbose_name = "Log Importação CNPJ"
        verbose_name_plural = "Logs Importação CNPJ"
        ordering = ['-iniciado_em']

    def __str__(self):
        return f"{self.nome_arquivo} - {self.status}"


class AuditoriaLigacao(models.Model):
    STATUS_CHOICES = [
        ("INICIADA", "Iniciada"),
        ("PROCESSANDO", "Processando"),
        ("FINALIZADA", "Finalizada"),
        ("ARQUIVADA", "Arquivada"),
        ("ERRO", "Erro"),
    ]

    PROVEDOR_CHOICES = [
        ("ZENVIA", "Zenvia Voice API"),
        ("SONAX", "Sonax PABX / click2call"),
    ]

    venda = models.ForeignKey(
        Venda,
        on_delete=models.CASCADE,
        related_name="auditoria_ligacoes",
    )
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ligacoes_auditoria_realizadas",
    )

    provedor = models.CharField(max_length=30, choices=PROVEDOR_CHOICES, default="ZENVIA")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="INICIADA", db_index=True)

    provider_call_id = models.CharField(max_length=120, db_index=True)
    provider_recording_id = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    id_contato = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    numero_origem = models.CharField(max_length=20, blank=True, null=True)
    numero_destino = models.CharField(max_length=20, blank=True, null=True)
    numero_receptivo = models.CharField(max_length=20, blank=True, null=True)
    status_chamada_provedor = models.CharField(max_length=80, blank=True, null=True, db_index=True)
    status_atendimento = models.CharField(max_length=5, blank=True, null=True, db_index=True)
    duracao_segundos = models.PositiveIntegerField(default=0)
    data_inicio_chamada = models.DateTimeField(blank=True, null=True)
    data_fim_chamada = models.DateTimeField(blank=True, null=True)

    consentimento_declarado = models.BooleanField(default=True)
    consentimento_observacao = models.CharField(max_length=255, blank=True, null=True)

    link_gravacao_provedor = models.TextField(blank=True, null=True)
    link_gravacao_onedrive = models.TextField(blank=True, null=True)
    expira_em = models.DateTimeField(blank=True, null=True)

    payload_inicio = models.JSONField(default=dict, blank=True)
    payload_webhook = models.JSONField(default=dict, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "crm_auditoria_ligacao"
        verbose_name = "Auditoria Ligação"
        verbose_name_plural = "Auditoria Ligações"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Venda {self.venda_id} - {self.provider_call_id} - {self.status}"


class FunilVendaWppTentativa(models.Model):
    """
    Uma jornada de venda pelo WhatsApp (fluxo VENDER), iniciada ao digitar o CEP.
    Dados sensíveis: acesso restrito à diretoria/admin (API + política interna).
    """
    STATUS_EM_ANDAMENTO = "em_andamento"
    STATUS_CONCLUIDO = "concluido"
    STATUS_ERRO = "erro"
    STATUS_ABANDONADO = "abandonado"
    STATUS_CHOICES = (
        (STATUS_EM_ANDAMENTO, "Em andamento"),
        (STATUS_CONCLUIDO, "Concluído"),
        (STATUS_ERRO, "Erro"),
        (STATUS_ABANDONADO, "Abandonado"),
    )

    FUNIL_VIABILIDADE = "viabilidade"
    FUNIL_CADASTRO = "cadastro"
    FUNIL_CONTATO = "contato"
    FUNIL_CREDITO = "credito"
    FUNIL_OFERTA = "oferta"
    FUNIL_PEDIDO = "pedido"
    FUNIL_ESTAGIO_CHOICES = (
        (FUNIL_VIABILIDADE, "Viabilidade"),
        (FUNIL_CADASTRO, "Cadastro"),
        (FUNIL_CONTATO, "Contato"),
        (FUNIL_CREDITO, "Crédito"),
        (FUNIL_OFERTA, "Oferta"),
        (FUNIL_PEDIDO, "Pedido"),
    )

    telefone = models.CharField(max_length=100, db_index=True)
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="funil_vendas_wpp",
    )
    matricula_pap_snapshot = models.CharField(max_length=80, blank=True, default="")
    bo_usuario_id = models.IntegerField(null=True, blank=True)
    sessao_whatsapp = models.ForeignKey(
        SessaoWhatsapp,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="funil_tentativas",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_EM_ANDAMENTO,
        db_index=True,
    )
    etapa_codigo_atual = models.CharField(max_length=80, blank=True, default="")
    funil_estagio_max = models.CharField(
        max_length=20,
        choices=FUNIL_ESTAGIO_CHOICES,
        blank=True,
        default="",
        db_index=True,
    )

    protocolo_pap = models.CharField(max_length=160, blank=True, default="")
    mensagem_erro = models.TextField(blank=True, default="")
    credito_resultado = models.CharField(max_length=255, blank=True, default="")

    iniciado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)

    dados_agregados = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_funil_venda_wpp_tentativa"
        verbose_name = "Funil Venda WPP (tentativa)"
        verbose_name_plural = "Funil Vendas WPP (tentativas)"
        ordering = ["-iniciado_em"]
        indexes = [
            models.Index(fields=["-iniciado_em", "status"]),
            models.Index(fields=["telefone", "-iniciado_em"]),
        ]

    def __str__(self):
        return f"{self.telefone} — {self.get_status_display()} ({self.iniciado_em})"


class FunilVendaWppEvento(models.Model):
    """Evento pontual dentro de uma tentativa (entrada do usuário ou marco da automação)."""

    TIPO_INPUT = "input"
    TIPO_TRANSICAO = "transicao"
    TIPO_ERRO_PAP = "erro_pap"
    TIPO_CREDITO = "credito"
    TIPO_PROTOCOLO = "protocolo"
    TIPO_STATUS = "status"
    TIPO_CHOICES = (
        (TIPO_INPUT, "Input"),
        (TIPO_TRANSICAO, "Transição"),
        (TIPO_ERRO_PAP, "Erro PAP"),
        (TIPO_CREDITO, "Crédito"),
        (TIPO_PROTOCOLO, "Protocolo"),
        (TIPO_STATUS, "Status"),
    )

    tentativa = models.ForeignKey(
        FunilVendaWppTentativa,
        on_delete=models.CASCADE,
        related_name="eventos",
    )
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    etapa_codigo = models.CharField(max_length=80, db_index=True)
    funil_estagio = models.CharField(
        max_length=20,
        choices=FunilVendaWppTentativa.FUNIL_ESTAGIO_CHOICES,
        default=FunilVendaWppTentativa.FUNIL_VIABILIDADE,
    )
    tipo_evento = models.CharField(max_length=30, choices=TIPO_CHOICES, default=TIPO_INPUT)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crm_funil_venda_wpp_evento"
        verbose_name = "Funil Venda WPP (evento)"
        verbose_name_plural = "Funil Vendas WPP (eventos)"
        ordering = ["id"]

    def __str__(self):
        return f"{self.tentativa_id} {self.etapa_codigo} @ {self.criado_em}"


class WhatsAppIntegracaoConfig(models.Model):
    """Configuração única do provedor WhatsApp (Z-API, Evolution+n8n, WhatsAtende ou híbrido)."""

    PROVIDER_ZAPI = "zapi"
    PROVIDER_EVOLUTION = "evolution"
    PROVIDER_WHATSATENDE = "whatsatende"
    PROVIDER_HYBRID = "hybrid"
    PROVIDER_CHOICES = (
        (PROVIDER_ZAPI, "Z-API (legado / plano B)"),
        (PROVIDER_EVOLUTION, "Evolution + n8n (Opção B)"),
        (PROVIDER_WHATSATENDE, "WhatsAtende (A+B)"),
        (
            PROVIDER_HYBRID,
            "Híbrido: Z-API (equipe) + WhatsAtende oficial (cliente)",
        ),
    )

    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_ZAPI,
        verbose_name="Provedor ativo",
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "Config. integração WhatsApp"
        verbose_name_plural = "Config. integração WhatsApp"

    def __str__(self) -> str:
        return f"WhatsApp: {self.get_provider_display()}"

    @classmethod
    def load(cls) -> "WhatsAppIntegracaoConfig":
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"provider": cls.PROVIDER_ZAPI})
        return obj


class WhatsAppIaConfig(models.Model):
    """Configuração singleton da IA no atendimento WhatsApp."""

    ia_contatos_externos_ativa = models.BooleanField(
        default=True,
        verbose_name="IA para contatos externos",
        help_text="Responde automaticamente números sem usuário/venda cadastrados.",
    )
    ia_clientes_venda_ativa = models.BooleanField(
        default=True,
        verbose_name="IA para clientes com venda",
        help_text="Atendimento automático com dados do pedido (boas-vindas, lembrete, etc.).",
    )
    ia_vendedores_duvidas_ativa = models.BooleanField(
        default=True,
        verbose_name="IA para dúvidas de vendedores",
        help_text="Responde perguntas livres de vendedores na etapa inicial.",
    )
    ia_boas_vindas_sugestao_ativa = models.BooleanField(
        default=True,
        verbose_name="IA sugere status em boas-vindas",
        help_text="Classifica a primeira resposta do cliente (OK/ERRO/etc.) para o backoffice.",
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "Config. IA WhatsApp"
        verbose_name_plural = "Config. IA WhatsApp"

    def __str__(self) -> str:
        return "Configuração IA WhatsApp"

    @classmethod
    def load(cls) -> "WhatsAppIaConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WhatsAppTelefoneSemIa(models.Model):
    """Números em que o bot não responde (conversa manual, sem IA)."""

    MOTIVO_CONVERSA_MANUAL = "conversa_manual"
    MOTIVO_LOOP_IA = "loop_ia"
    MOTIVO_OUTRO = "outro"
    MOTIVO_CHOICES = (
        (MOTIVO_CONVERSA_MANUAL, "Conversa manual (externo)"),
        (MOTIVO_LOOP_IA, "Loop de respostas IA"),
        (MOTIVO_OUTRO, "Outro"),
    )

    telefone = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Telefone",
        help_text="Somente dígitos (ex.: 5511999998888 ou 11999998888).",
    )
    descricao = models.CharField(max_length=200, blank=True, default="")
    motivo = models.CharField(
        max_length=30,
        choices=MOTIVO_CHOICES,
        default=MOTIVO_CONVERSA_MANUAL,
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="telefones_sem_ia_criados",
    )

    class Meta:
        verbose_name = "Telefone sem IA (WhatsApp)"
        verbose_name_plural = "Telefones sem IA (WhatsApp)"
        ordering = ["-criado_em"]
        db_table = "crm_whatsapp_telefone_sem_ia"

    def __str__(self) -> str:
        return f"{self.telefone} ({self.get_motivo_display()})"

    def save(self, *args, **kwargs) -> None:
        from crm_app.whatsapp_telefone_blocklist import normalizar_telefone_blocklist

        self.telefone = normalizar_telefone_blocklist(self.telefone)
        super().save(*args, **kwargs)


class SessaoTratamento(models.Model):
    """Cronômetro server-side do tempo que um usuário gasta tratando uma venda.

    Uma venda pode ter várias sessões (alocar → liberar → retomar), por isso o
    tempo é medido por sessão e não por um único campo na ``Venda``. O relógio é
    sempre do servidor (``timezone.now``) para não depender do frontend.
    """

    MODULO_AUDITORIA = 'AUDITORIA'
    MODULO_ESTEIRA = 'ESTEIRA'
    MODULO_CHOICES = (
        (MODULO_AUDITORIA, 'Auditoria'),
        (MODULO_ESTEIRA, 'Esteira'),
    )

    # Motivos de encerramento. Os "produtivos" indicam que houve uma decisão.
    MOTIVO_APROVADO = 'APROVADO'
    MOTIVO_CADASTRADO = 'CADASTRADO'
    MOTIVO_REPROVADO = 'REPROVADO'
    MOTIVO_SALVO = 'SALVO'
    MOTIVO_LIBERADO = 'LIBERADO'
    MOTIVO_ABANDONO = 'ABANDONO'
    MOTIVO_TIMEOUT = 'TIMEOUT'
    MOTIVO_CHOICES = (
        (MOTIVO_APROVADO, 'Aprovado/Auditado'),
        (MOTIVO_CADASTRADO, 'Cadastrado'),
        (MOTIVO_REPROVADO, 'Reprovado/Pendenciado'),
        (MOTIVO_SALVO, 'Salvo (esteira)'),
        (MOTIVO_LIBERADO, 'Liberado sem decisão'),
        (MOTIVO_ABANDONO, 'Abandono (saiu da tela)'),
        (MOTIVO_TIMEOUT, 'Timeout (ociosidade)'),
    )

    # Motivos que representam trabalho efetivamente concluído (para produtividade).
    MOTIVOS_PRODUTIVOS = (MOTIVO_APROVADO, MOTIVO_CADASTRADO, MOTIVO_REPROVADO, MOTIVO_SALVO)

    venda = models.ForeignKey(
        Venda, on_delete=models.CASCADE, related_name='sessoes_tratamento', db_index=True,
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sessoes_tratamento', db_index=True,
    )
    modulo = models.CharField(max_length=16, choices=MODULO_CHOICES, db_index=True)
    iniciado_em = models.DateTimeField(db_index=True)
    ultimo_ping = models.DateTimeField()
    finalizado_em = models.DateTimeField(null=True, blank=True, db_index=True)
    duracao_segundos = models.PositiveIntegerField(null=True, blank=True)
    motivo_fim = models.CharField(max_length=16, choices=MOTIVO_CHOICES, blank=True, default='')
    status_resultado = models.CharField(
        max_length=120, blank=True, default='',
        help_text='Nome do status aplicado ao encerrar (ex.: CADASTRADA, REPROVADA).',
    )

    class Meta:
        db_table = 'crm_sessao_tratamento'
        verbose_name = 'Sessão de tratamento'
        verbose_name_plural = 'Sessões de tratamento'
        ordering = ['-iniciado_em']
        indexes = [
            models.Index(fields=['modulo', 'iniciado_em']),
            models.Index(fields=['usuario', 'iniciado_em']),
            models.Index(fields=['finalizado_em']),
            models.Index(fields=['venda', 'modulo', 'finalizado_em']),
        ]

    def __str__(self) -> str:
        return f'Sessão #{self.pk} venda #{self.venda_id} {self.modulo} ({self.usuario_id})'

    @property
    def esta_aberta(self) -> bool:
        return self.finalizado_em is None


class RelatorioTratamentoConfig(models.Model):
    """Configuração (singleton) do relatório diário de tempo de tratamento via WhatsApp."""

    ativo = models.BooleanField(default=False, verbose_name='Relatório diário ativo')
    destino_telefone = models.CharField(
        max_length=60, blank=True, default='',
        verbose_name='Destino (telefone ou ID de grupo)',
        help_text='Telefone da diretoria (com DDD) ou ID de grupo WhatsApp (ex.: 12036...@g.us).',
    )
    horario_envio = models.TimeField(
        null=True, blank=True, verbose_name='Horário de envio (HH:MM)',
        help_text='Horário no fim do dia para disparar o relatório (seg-sex).',
    )
    incluir_auditoria = models.BooleanField(default=True)
    incluir_esteira = models.BooleanField(default=True)
    limite_outlier_minutos = models.PositiveIntegerField(
        default=15,
        help_text='Sessões acima deste tempo são destacadas como fora do padrão no relatório.',
    )
    timeout_ociosidade_minutos = models.PositiveIntegerField(
        default=10,
        help_text='Sem heartbeat por este tempo, a sessão é encerrada como TIMEOUT.',
    )
    controle_disparos = models.JSONField(default=dict, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'crm_relatorio_tratamento_config'
        verbose_name = 'Config. relatório de tratamento'
        verbose_name_plural = 'Config. relatório de tratamento'

    def __str__(self) -> str:
        estado = 'ativo' if self.ativo else 'inativo'
        return f'Relatório tempo de tratamento ({estado})'