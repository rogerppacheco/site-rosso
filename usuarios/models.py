from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError

class Perfil(models.Model):
    cod_perfil = models.CharField(max_length=50, unique=True, blank=False, null=False, verbose_name="Código do Perfil")
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfis"

    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    matricula_pap = models.CharField(max_length=50, blank=True, null=True, verbose_name="Matrícula PAP")
    senha_pap = models.CharField(max_length=128, blank=True, null=True, verbose_name="Senha PAP")
    # --- CANAIS ---
    # Adicionado DIGITAL, RECEPTIVO e PARCEIRO para o Dashboard
    CANAL_CHOICES = [
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
        ('TELAG', 'TelAg'), # Mantido para compatibilidade se já usado
        ('INTERNO', 'Interno'),   # Mantido para compatibilidade se já usado
    ]
    canal = models.CharField(
        max_length=20, 
        choices=CANAL_CHOICES, 
        blank=True, 
        null=True, 
        default='PAP',
        verbose_name="Canal de Venda"
    )
    
    # --- CLUSTER ---
    CLUSTER_CHOICES = [
        ('CLUSTER_1', 'CLUSTER 1'),
        ('CLUSTER_2', 'CLUSTER 2'),
        ('CLUSTER_3', 'CLUSTER 3'),
    ]
    cluster = models.CharField(
        max_length=20,
        choices=CLUSTER_CHOICES,
        blank=True,
        null=True,
        verbose_name="Cluster"
    )
    
    # --- IDENTIFICAÇÃO ---
    cpf = models.CharField(max_length=14, blank=True, null=True, unique=True)
    
    # --- RELAÇÕES ---
    perfil = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='liderados')
    
    # --- FINANCEIRO ---
    valor_almoco = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    valor_passagem = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    valor_ajuda_custo_mensal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        blank=True,
        verbose_name="Ajuda de custo mensal fixa (R$)",
        help_text="Valor fixo mensal de ajuda de custo (ex.: parceiros). Diferente de almoço+passagem."
    )
    chave_pix = models.CharField(max_length=255, blank=True, null=True)
    nome_da_conta = models.CharField(max_length=255, blank=True, null=True)

    # --- COMISSIONAMENTO ---
    meta_comissao = models.IntegerField(default=0)
    desconto_boleto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inclusao_viabilidade = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_instalacao_antecipada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True, db_index=True)
    adiantamento_cnpj = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    recebe_adiantamento_cnpj = models.BooleanField(
        default=True,
        verbose_name="Recebe adiantamento de CNPJ?",
        help_text="Se desmarcado, o usuário não pode receber lançamento do tipo Adiantamento CNPJ."
    )
    recebe_adiantamento_sabado = models.BooleanField(
        default=False,
        verbose_name="Recebe adiantamento de comissão (vendas O.S. aberta em sábado)?",
        help_text="Se marcado, a venda pode ser lançada como adiantada na esteira (aba Agendados) conforme Regras por Faixa (Finalidade Adiantamento).",
    )
    desconto_inss_fixo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # --- CONTROLE DE PRESENÇA ---
    participa_controle_presenca = models.BooleanField(
        default=True,
        verbose_name="Participa do Controle de Presença?",
        help_text="Marque se este usuário deve aparecer na tela de controle de presença."
    )
    vendedor_solo = models.BooleanField(
        default=False,
        verbose_name="Vendedor solo",
        help_text="Permite ao vendedor acessar a ferramenta Presença para registrar a própria selfie/confirmar presença sem equipe."
    )

    # --- WHATSAPP ---
    # Envios do sistema (notificações, OSAB, etc.) vão SEMPRE apenas para WhatsApp 1 (tel_whatsapp).
    tel_whatsapp = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="WhatsApp 1",
        help_text="Número principal com DDD (apenas números). Notificações do sistema são enviadas só para este número. Qualquer um dos 3 pode interagir com o bot."
    )
    tel_whatsapp_2 = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="WhatsApp 2",
        help_text="Segundo número (opcional). Só para interagir com o bot; envios do sistema vão apenas para WhatsApp 1."
    )
    tel_whatsapp_3 = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="WhatsApp 3",
        help_text="Terceiro número (opcional). Só para interagir com o bot; envios do sistema vão apenas para WhatsApp 1."
    )

    # --- SEGURANÇA ---
    obriga_troca_senha = models.BooleanField(
        default=False, 
        verbose_name="Obrigar troca de senha?",
        help_text="Se marcado, o usuário deverá trocar a senha no próximo login."
    )

    # --- AUTOMAÇÃO PAP ---
    autorizar_venda_sem_auditoria = models.BooleanField(
        default=False,
        verbose_name="Autorizar venda sem auditoria?",
        help_text="Se marcado, o vendedor pode realizar vendas pelo WhatsApp usando automação do PAP."
    )
    autorizar_venda_automatica = models.BooleanField(
        default=False,
        verbose_name="Autorizar venda Automática",
        help_text="Se marcado, o vendedor poderá informar se a O.S. foi gerada automaticamente ao cadastrar vendas."
    )
    autorizar_analise_credito_wpp = models.BooleanField(
        default=False,
        verbose_name="Autorizar fazer análise de crédito pelo Wpp",
        help_text="Se marcado, o usuário pode consultar análise de crédito pelo WhatsApp (palavra-chave CRÉDITO)."
    )
    autorizar_inclusao_wpp = models.BooleanField(
        default=False,
        verbose_name="Autorizar Inclusão/Viabilidade pelo Wpp",
        help_text="Se marcado, o usuário pode usar o comando INCLUSÃO pelo WhatsApp (solicitar viabilidade via formulário)."
    )
    autorizado_chamar_no_bot = models.BooleanField(
        default=True,
        verbose_name="Autorizado chamar no bot",
        help_text="Se desmarcado, o usuário continua recebendo mensagens do bot, mas ao interagir receberá aviso (uma vez por dia) de que não está liberado para acesso; no mesmo dia, interações adicionais não recebem resposta."
    )
    login_pap_disponivel_para_automacao = models.BooleanField(
        default=True,
        verbose_name="Disponibilizar login PAP para o bot (WhatsApp)",
        help_text="Se desmarcado, o bot/automação do WhatsApp não usará este login no pool. Use quando o BO estiver atuando no PAP para não disputar o mesmo login."
    )
    # Quais automações podem usar este login BO (só aplica se login_pap_disponivel_para_automacao=True)
    pap_automacao_vender = models.BooleanField(
        default=True,
        verbose_name="PAP: automação Vender",
        help_text="Se marcado, este login pode ser usado pela automação VENDER (nova venda pelo WhatsApp)."
    )
    pap_automacao_credito = models.BooleanField(
        default=True,
        verbose_name="PAP: automação Crédito",
        help_text="Se marcado, este login pode ser usado pela automação CRÉDITO (análise de crédito pelo WhatsApp)."
    )
    pap_automacao_pedido = models.BooleanField(
        default=True,
        verbose_name="PAP: automação Pedido",
        help_text="Se marcado, este login pode ser usado pela automação PEDIDO (consulta de pedido/O.S. pelo WhatsApp)."
    )
    pap_automacao_status = models.BooleanField(
        default=True,
        verbose_name="PAP: automação Status",
        help_text="Se marcado, este login pode ser usado pela automação STATUS (consulta online de pedido no PAP)."
    )

    # --- BR PRONTO PDV (Biometria - Auditoria / WhatsApp BIO) ---
    brpronto_login = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Login Br Pronto PDV",
        help_text="Login (matrícula TT) para consulta de biometria no ged360. Preferir perfil NIVEL2_BOPAP.",
    )
    brpronto_senha = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        verbose_name="Senha Br Pronto PDV",
        help_text="Senha do Br Pronto. Gerenciada na Governança; usada pelo pool da automação.",
    )
    brpronto_dominio = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Domínio Br Pronto PDV",
        help_text="Domínio no login do Br Pronto (ex.: BrPronto).",
    )
    brpronto_disponivel_para_automacao = models.BooleanField(
        default=False,
        verbose_name="Disponibilizar login Br Pronto para o bot",
        help_text=(
            "Se marcado, este login entra no pool de consulta de biometria "
            "(auditoria Checar biometria e comando BIO no WhatsApp)."
        ),
    )
    autorizar_consulta_bio_wpp = models.BooleanField(
        default=False,
        verbose_name="Autorizar consulta Bio pelo Wpp",
        help_text="Se marcado, o usuário pode usar o comando BIO no WhatsApp.",
    )

    # --- GESTÃO DE ACESSOS (DELEGAÇÃO) ---
    pode_gestao_acessos = models.BooleanField(
        default=False,
        verbose_name="Pode usar a ferramenta Gestão de Acessos?",
        help_text="Se marcado, o usuário verá o card 'Gestão de Acessos' na área interna e poderá gerenciar usuários (exceto perfis Admin e Diretoria)."
    )

    class Meta(AbstractUser.Meta):
        pass

    def __str__(self):
        return self.username

    def clean(self):
        """
        Validação padrão do Django.
        OBS: A validação de existência do WhatsApp na API externa (Z-API) foi REMOVIDA daqui 
        para não bloquear o salvamento. Ela deve ser feita via endpoint dedicado no Frontend.
        """
        super().clean()

    def save(self, *args, **kwargs):
        # Salva diretamente sem chamadas externas bloqueantes
        super().save(*args, **kwargs)

class PermissaoPerfil(models.Model):
    perfil = models.ForeignKey(Perfil, on_delete=models.CASCADE, related_name='permissoes')
    recurso = models.CharField(max_length=100, help_text="O nome do recurso (ex: 'operadoras', 'planos')")
    pode_ver = models.BooleanField(default=False)
    pode_criar = models.BooleanField(default=False)
    pode_editar = models.BooleanField(default=False)
    pode_excluir = models.BooleanField(default=False)

    class Meta:
        unique_together = ('perfil', 'recurso')
        verbose_name = "Permissão de Perfil"
        verbose_name_plural = "Permissões de Perfis"

    def __str__(self):
        return f"Permissões do {self.perfil.nome} para {self.recurso}"