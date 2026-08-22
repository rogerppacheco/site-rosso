# site-record/usuarios/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Perfil, PermissaoPerfil

class PermissaoPerfilInline(admin.TabularInline):
    model = PermissaoPerfil
    extra = 1
    fields = ('recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir')
    verbose_name = "Permissão"
    verbose_name_plural = "Permissões"
    can_delete = True
    show_change_link = False

@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('nome', 'cod_perfil')
    list_filter = ('nome',)
    search_fields = ('nome', 'cod_perfil')
    inlines = [PermissaoPerfilInline]

class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informações Pessoais', {'fields': ('first_name', 'last_name', 'email', 'cpf')}),
        ('Função e Estrutura', {'fields': ('perfil', 'supervisor', 'canal')}),
        ('Financeiro', {'fields': (
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta'
        )}),
        ('Comissionamento', {'fields': (
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 'adiantamento_cnpj', 'recebe_adiantamento_cnpj',
            'recebe_adiantamento_sabado', 'desconto_inss_fixo'
        )}),
        ('Automação PAP / WhatsApp', {
            'fields': (
                'matricula_pap', 'senha_pap',
                'autorizar_venda_sem_auditoria', 'autorizar_venda_automatica',
                'autorizar_analise_credito_wpp', 'autorizar_inclusao_wpp',
                'login_pap_disponivel_para_automacao',
                'pap_automacao_vender', 'pap_automacao_credito', 'pap_automacao_pedido', 'pap_automacao_status',
            ),
            'description': 'Login PAP: se "Disponibilizar login PAP para o bot" estiver desmarcado, o bot não usará este login. Use os checkboxes de automação para definir em quais fluxos (Vender, Crédito, Pedido, Status) este login BO pode ser usado.'
        }),
        ('Br Pronto PDV (Biometria)', {
            'fields': (
                'brpronto_login', 'brpronto_senha', 'brpronto_dominio',
                'brpronto_disponivel_para_automacao', 'autorizar_consulta_bio_wpp',
            ),
            'description': (
                'Credenciais ged360 (perfil NIVEL2_BOPAP). '
                'Marque "Disponibilizar" para entrar no pool da auditoria/BIO. '
                'Sempre há logoff automático após cada consulta.'
            ),
        }),
        ('Delegação', {
            'fields': ('pode_gestao_acessos',),
            'description': 'Se "Pode usar a ferramenta Gestão de Acessos?" estiver marcado, o usuário verá o card Gestão de Acessos na área interna e poderá gerenciar apenas usuários que não são Admin ou Diretoria.'
        }),
        ('WhatsApp', {'fields': ('tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3')}),
        ('Permissões', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'description': 'OBS: O campo "Groups" acima também pode ser usado para definir perfis. O campo "Perfil" é opcional e legado.'
        }),
        ('Datas Importantes', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Informações Adicionais', {
            'fields': ('perfil', 'supervisor', 'canal', 'cpf'),
        }),
    )

    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_groups_display', 'perfil', 'canal')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups', 'perfil', 'canal')
    
    def get_groups_display(self, obj):
        """Mostra os grupos do usuário na listagem"""
        if obj.groups.exists():
            return ', '.join([g.name for g in obj.groups.all()])
        return '-'
    get_groups_display.short_description = 'Groups (Perfil)'

    def save_model(self, request, obj, form, change):
        """Override para sincronizar perfil com groups quando salvar pelo Django admin"""
        # Salva o modelo primeiro
        super().save_model(request, obj, form, change)
        
        # SEMPRE sincroniza grupo baseado no perfil (perfil é a fonte de verdade)
        if obj.perfil:
            from django.contrib.auth.models import Group
            try:
                # Busca o grupo com o mesmo nome do perfil
                group = Group.objects.get(name__iexact=obj.perfil.nome)
                # Define apenas este grupo (remove outros e adiciona este)
                obj.groups.set([group])
            except Group.DoesNotExist:
                # Se não encontrar grupo correspondente, mantém os grupos atuais
                pass
        else:
            # Se perfil está vazio, limpa os grupos
            obj.groups.clear()

# ======================================================
# --- CORREÇÃO APLICADA AQUI ---
# A linha admin.site.unregister(Usuario) foi REMOVIDA.
# Apenas registramos nosso admin customizado.
# ======================================================
admin.site.register(Usuario, CustomUserAdmin)