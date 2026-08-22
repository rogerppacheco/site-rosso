
from rest_framework import serializers
from django.db import transaction
import re
from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia, StatusAgendamento,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda, Campanha,
    ComissaoOperadora, Comunicado, LancamentoFinanceiro,
    RegraCampanha, FaturaM10, GrupoDisparo,
    RegraComissaoFaixa, ConfigComissaoVendedor, RegraComissaoFaixaPlano,
    EtapaErroAjudaGc, PlanoValoresComissao, CidadeOfertaEspecial,
)
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer


# --- SERIALIZER PARA REGRAS DE CAMPANHA (FAIXAS) ---
class RegraCampanhaSerializer(serializers.ModelSerializer):
    """Serializer para as faixas de premiação dentro de uma Campanha."""
    class Meta:
        model = RegraCampanha
        fields = ('id', 'meta', 'valor_premio')


# --- SERIALIZERS BÁSICOS ---

class OperadoraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operadora
        fields = '__all__'


class PlanoSerializer(serializers.ModelSerializer):
    operadora_nome = serializers.CharField(source='operadora.nome', read_only=True)
    recebimento_operadora_base = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, write_only=True,
    )
    comissao_operadora_valor = serializers.SerializerMethodField()
    usa_comissao_cidade_especial = serializers.BooleanField(required=False)
    valor_pap_cidade_especial = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True,
    )
    valor_cnpj_cidade_especial = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True,
    )

    class Meta:
        model = Plano
        fields = [
            'id', 'nome', 'valor', 'operadora', 'operadora_nome', 'beneficios', 'ativo',
            'comissao_base', 'gdp_velocidade_mbps', 'gdp_indice_oferta',
            'recebimento_operadora_base', 'comissao_operadora_valor',
            'usa_comissao_cidade_especial', 'valor_pap_cidade_especial',
            'valor_cnpj_cidade_especial',
        ]

    def get_comissao_operadora_valor(self, obj: Plano):
        try:
            return obj.comissao_operadora.valor_base
        except ComissaoOperadora.DoesNotExist:
            return None

    def to_representation(self, instance: Plano):
        data = super().to_representation(instance)
        try:
            vc = instance.valores_comissao
            data['usa_comissao_cidade_especial'] = bool(vc.usa_comissao_cidade_especial)
            data['valor_pap_cidade_especial'] = vc.valor_pap_cidade_especial
            data['valor_cnpj_cidade_especial'] = vc.valor_cnpj_cidade_especial
        except PlanoValoresComissao.DoesNotExist:
            data['usa_comissao_cidade_especial'] = False
            data['valor_pap_cidade_especial'] = None
            data['valor_cnpj_cidade_especial'] = None
        return data

    def _pop_comissao_cidade_especial(self, validated_data: dict) -> dict:
        """Extrai campos de cidade especial; chave ausente = não alterar."""
        extras: dict = {}
        for campo in (
            'usa_comissao_cidade_especial',
            'valor_pap_cidade_especial',
            'valor_cnpj_cidade_especial',
        ):
            if campo in validated_data:
                extras[campo] = validated_data.pop(campo)
        return extras

    def _sync_comissao_cidade_especial(self, plano: Plano, extras: dict) -> None:
        """Persiste override de comissão em cidade de oferta especial no PlanoValoresComissao."""
        if not extras:
            return
        vc, _created = PlanoValoresComissao.objects.get_or_create(plano=plano)
        update_fields: list[str] = []
        if 'usa_comissao_cidade_especial' in extras:
            vc.usa_comissao_cidade_especial = bool(extras['usa_comissao_cidade_especial'])
            update_fields.append('usa_comissao_cidade_especial')
        if 'valor_pap_cidade_especial' in extras:
            vc.valor_pap_cidade_especial = extras['valor_pap_cidade_especial']
            update_fields.append('valor_pap_cidade_especial')
        if 'valor_cnpj_cidade_especial' in extras:
            vc.valor_cnpj_cidade_especial = extras['valor_cnpj_cidade_especial']
            update_fields.append('valor_cnpj_cidade_especial')
        if update_fields:
            vc.save(update_fields=update_fields)

    def _sync_plano_comissao(self, plano: Plano, recebimento) -> None:
        from crm_app.services.comissao_matriz_service import sincronizar_plano_em_todas_faixas
        from crm_app.services.plano_comissao_service import garantir_comissao_operadora
        sincronizar_plano_em_todas_faixas(plano)
        if recebimento is not None:
            garantir_comissao_operadora(plano, recebimento)

    def _aplicar_mapeamento_gdp_plano(self, plano: Plano, validated_data: dict) -> None:
        """Preenche velocidade GDP pelo nome quando não informado no cadastro."""
        if validated_data.get('gdp_velocidade_mbps'):
            return
        from crm_app.services.gdp_preco_service import resolver_chave_gdp_plano

        velocidade, indice = resolver_chave_gdp_plano(plano)
        plano.gdp_velocidade_mbps = velocidade
        plano.gdp_indice_oferta = indice
        plano.save(update_fields=['gdp_velocidade_mbps', 'gdp_indice_oferta'])

    def create(self, validated_data):
        recebimento = validated_data.pop('recebimento_operadora_base', None)
        extras = self._pop_comissao_cidade_especial(validated_data)
        plano = Plano.objects.create(**validated_data)
        self._aplicar_mapeamento_gdp_plano(plano, validated_data)
        self._sync_plano_comissao(plano, recebimento)
        self._sync_comissao_cidade_especial(plano, extras)
        return plano

    def update(self, instance, validated_data):
        recebimento = validated_data.pop('recebimento_operadora_base', None)
        extras = self._pop_comissao_cidade_especial(validated_data)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if 'gdp_velocidade_mbps' not in validated_data and 'nome' in validated_data:
            self._aplicar_mapeamento_gdp_plano(instance, validated_data)
        self._sync_plano_comissao(instance, recebimento)
        self._sync_comissao_cidade_especial(instance, extras)
        return instance

class FormaPagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormaPagamento
        fields = ['id', 'nome', 'ativo', 'aplica_desconto']

# --- CAMPANHA SERIALIZER ---
class CampanhaSerializer(serializers.ModelSerializer):
    # Campo aninhado: indica que esperamos uma lista (many=True) de objetos RegraCampanha
    regras_meta = RegraCampanhaSerializer(many=True, required=False) 
    
    # Campo M2M (Many to Many)
    planos_elegiveis = serializers.PrimaryKeyRelatedField(many=True, queryset=Plano.objects.all(), required=False)
    formas_pagamento_elegiveis = serializers.PrimaryKeyRelatedField(many=True, queryset=FormaPagamento.objects.all(), required=False)

    class Meta:
        model = Campanha
        fields = ('id', 'nome', 'data_inicio', 'data_fim', 
                  'meta_vendas', 'valor_premio', 'tipo_meta', 
                  'canal_alvo', 'planos_elegiveis', 'formas_pagamento_elegiveis', 
                  'regras', 'ativo', 'data_criacao', 
                  'regras_meta')

    def create(self, validated_data):
        # 1. Pop a lista de faixas do dicionário principal
        regras_data = validated_data.pop('regras_meta', [])
        
        # 2. Pop M2M fields para salvar depois
        planos_data = validated_data.pop('planos_elegiveis', [])
        pagamentos_data = validated_data.pop('formas_pagamento_elegiveis', [])
        
        # 3. Cria o objeto Campanha principal
        with transaction.atomic():
            campanha = Campanha.objects.create(**validated_data)
            
            # 4. Cria os objetos RegraCampanha (Faixas)
            for regra_data in regras_data:
                RegraCampanha.objects.create(campanha=campanha, **regra_data)
                
            # 5. Salva os relacionamentos M2M
            campanha.planos_elegiveis.set(planos_data)
            campanha.formas_pagamento_elegiveis.set(pagamentos_data)
        
        return campanha

    def update(self, instance, validated_data):
        # 1. Pop a lista de faixas para atualização
        regras_data = validated_data.pop('regras_meta', None)
        
        # 2. Pop M2M fields
        planos_data = validated_data.pop('planos_elegiveis', None)
        pagamentos_data = validated_data.pop('formas_pagamento_elegiveis', None)

        with transaction.atomic():
            # 3. Atualiza Campanha principal (campos simples)
            for key, value in validated_data.items():
                setattr(instance, key, value)
            
            instance.save()
            
            # 4. Atualiza os relacionamentos M2M
            if planos_data is not None:
                instance.planos_elegiveis.set(planos_data)
            if pagamentos_data is not None:
                instance.formas_pagamento_elegiveis.set(pagamentos_data)

            # 5. Atualiza/Substitui Faixas de Premiação
            if regras_data is not None:
                # Exclui todas as regras antigas desta campanha
                instance.regras_meta.all().delete()
                
                # Cria as novas regras enviadas pelo frontend
                for regra_data in regras_data:
                    RegraCampanha.objects.create(campanha=instance, **regra_data)

        return instance
# --- FIM CAMPANHA SERIALIZER ---


class StatusCRMSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusCRM
        fields = '__all__'

    def validate_nome(self, value):
        """Normaliza espaços; evita colisão falsa por espaços nas pontas."""
        nome = (value or '').strip()
        if not nome:
            raise serializers.ValidationError('Informe o nome do status.')
        if len(nome) > 100:
            raise serializers.ValidationError('Nome pode ter no máximo 100 caracteres.')
        return nome

    def validate_estado(self, value):
        """Normaliza string vazia para None (campo opcional)."""
        if value is not None and str(value).strip() == '':
            return None
        return value

    def validate(self, attrs):
        """Garante que (nome, tipo) seja único (evita 500 por IntegrityError)."""
        nome = attrs.get('nome', getattr(self.instance, 'nome', None))
        tipo = attrs.get('tipo', getattr(self.instance, 'tipo', None))
        if nome is not None and tipo is not None:
            qs = StatusCRM.objects.filter(nome__iexact=str(nome).strip(), tipo=tipo)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                existente = qs.first()
                raise serializers.ValidationError({
                    'nome': (
                        f'Já existe um status com este nome e tipo '
                        f'(id={existente.id}, tipo={existente.tipo}).'
                    )
                })
        return attrs

class MotivoPendenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MotivoPendencia
        fields = '__all__'
    
    def validate_nome(self, value):
        # Verifica se já existe um motivo com o mesmo nome (case-insensitive)
        # Exclui a instância atual se estiver editando
        queryset = MotivoPendencia.objects.filter(nome__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise serializers.ValidationError("Já existe um motivo de pendência cadastrado com este nome.")
        return value


class StatusAgendamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusAgendamento
        fields = '__all__'

    def validate_nome(self, value: str) -> str:
        nome = (value or '').strip()
        if not nome:
            raise serializers.ValidationError('Informe o nome do status.')
        qs = StatusAgendamento.objects.filter(nome__iexact=nome)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                'Já existe um status de agendamento com este nome.'
            )
        return nome


class CidadeOfertaEspecialSerializer(serializers.ModelSerializer):
    class Meta:
        model = CidadeOfertaEspecial
        fields = [
            'id', 'uf', 'municipio', 'municipio_normalizado', 'ativo',
            'criado_em', 'atualizado_em',
        ]
        read_only_fields = ['municipio_normalizado', 'criado_em', 'atualizado_em']

    def validate_uf(self, value: str) -> str:
        uf = (value or '').strip().upper()
        if len(uf) != 2:
            raise serializers.ValidationError('UF deve ter 2 letras.')
        return uf

    def validate_municipio(self, value: str) -> str:
        municipio = (value or '').strip()
        if not municipio:
            raise serializers.ValidationError('Informe o município.')
        return municipio


class EtapaErroAjudaGcSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtapaErroAjudaGc
        fields = '__all__'

    def validate_nome(self, value: str) -> str:
        nome = (value or '').strip()
        if not nome:
            raise serializers.ValidationError('Informe o nome da etapa.')
        return nome

    def validate(self, attrs):
        contexto = attrs.get('contexto') or getattr(self.instance, 'contexto', None)
        nome = attrs.get('nome')
        if nome is None and self.instance:
            nome = self.instance.nome
        nome = (nome or '').strip()
        qs = EtapaErroAjudaGc.objects.filter(contexto=contexto, nome__iexact=nome)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {'nome': 'Já existe esta etapa para o mesmo contexto.'}
            )
        attrs['nome'] = nome
        return attrs


class RegraComissaoSerializer(serializers.ModelSerializer):
    consultor_nome = serializers.CharField(source='consultor.get_full_name', read_only=True)
    plano_nome = serializers.CharField(source='plano.nome', read_only=True)
    class Meta:
        model = RegraComissao
        fields = '__all__'


class RegraComissaoFaixaSerializer(serializers.ModelSerializer):
    vendedor_username = serializers.CharField(source='vendedor.username', read_only=True)
    class Meta:
        model = RegraComissaoFaixa
        fields = '__all__'


class ConfigComissaoVendedorSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='usuario.username', read_only=True)
    valores_por_plano = serializers.SerializerMethodField()

    class Meta:
        model = ConfigComissaoVendedor
        fields = '__all__'
        extra_kwargs = {'usuario': {'read_only': True}}

    def get_valores_por_plano(self, instance: ConfigComissaoVendedor) -> list[dict]:
        from crm_app.services.comissao_matriz_service import listar_valores_manuais_vendedor
        return listar_valores_manuais_vendedor(instance)

    def update(self, instance, validated_data):
        valores = None
        if hasattr(self, 'initial_data') and isinstance(self.initial_data, dict):
            if 'valores_por_plano' in self.initial_data:
                valores = self.initial_data.get('valores_por_plano')
        instance = super().update(instance, validated_data)
        if valores is not None:
            from crm_app.services.comissao_matriz_service import salvar_valores_manuais_vendedor
            salvar_valores_manuais_vendedor(instance, valores)
        return instance


class ClienteSerializer(serializers.ModelSerializer):
    vendas_count = serializers.IntegerField(read_only=True, required=False)
    telefone1 = serializers.SerializerMethodField()
    telefone2 = serializers.SerializerMethodField()
    nome_mae = serializers.SerializerMethodField()
    data_nascimento = serializers.SerializerMethodField()

    classificacao_mei_descricao = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            'id', 'cpf_cnpj', 'nome_razao_social', 'email', 'vendas_count',
            'telefone1', 'telefone2', 'nome_mae', 'data_nascimento',
            'classificacao_mei', 'classificacao_mei_consultada_em', 'classificacao_mei_descricao',
        ]

    def get_classificacao_mei_descricao(self, obj):
        from crm_app.services.cnpj_mei_service import rotulo_classificacao_mei
        return rotulo_classificacao_mei(obj.classificacao_mei, documento=obj.cpf_cnpj)

    def get_last_sale(self, obj):
        if not hasattr(obj, '_last_sale_cache'):
            obj._last_sale_cache = obj.vendas.filter(ativo=True).order_by('-data_criacao').first()
        return obj._last_sale_cache

    def get_telefone1(self, obj):
        last = self.get_last_sale(obj)
        return last.telefone1 if last and last.telefone1 else ""

    def get_telefone2(self, obj):
        last = self.get_last_sale(obj)
        return last.telefone2 if last and last.telefone2 else ""

    def get_nome_mae(self, obj):
        last = self.get_last_sale(obj)
        return last.nome_mae if last and last.nome_mae else ""

    def get_data_nascimento(self, obj):
        last = self.get_last_sale(obj)
        return last.data_nascimento if last and last.data_nascimento else None

class HistoricoAlteracaoVendaSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = HistoricoAlteracaoVenda
        fields = ('usuario', 'data_alteracao', 'alteracoes')

# --- SERIALIZERS DE VENDA ---

class VendaSerializer(serializers.ModelSerializer):
    """
    Serializer otimizado para LISTAGEM (evita N+1 queries)
    Carrega APENAS campos achatados, sem serializers aninhados complexos
    """
    # Campos Achatados (Legacy Support para outras telas)
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social', read_only=True)
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    cliente_email = serializers.CharField(source='cliente.email', read_only=True)
    vendedor_nome = serializers.ReadOnlyField(source='vendedor.username')
    
    # Status como SimpleFields (sem serializers aninhados)
    status_tratamento_nome = serializers.CharField(source='status_tratamento.nome', read_only=True)
    status_esteira_nome = serializers.CharField(source='status_esteira.nome', read_only=True)
    status_comissionamento_nome = serializers.CharField(source='status_comissionamento.nome', read_only=True)
    
    plano_nome = serializers.CharField(source='plano.nome', read_only=True)
    forma_pagamento_nome = serializers.CharField(source='forma_pagamento.nome', read_only=True)
    motivo_pendencia_nome = serializers.CharField(source='motivo_pendencia.nome', read_only=True, allow_null=True)
    motivo_pendencia_tipo = serializers.CharField(
        source='motivo_pendencia.tipo_pendencia',
        read_only=True,
        allow_null=True,
    )
    status_agendamento_nome = serializers.CharField(
        source='status_agendamento.nome',
        read_only=True,
        allow_null=True,
    )
    status_agendamento_cor = serializers.CharField(
        source='status_agendamento.cor',
        read_only=True,
        allow_null=True,
    )
    
    # Auditoria
    nome_editor = serializers.SerializerMethodField()
    auditor_atual_nome = serializers.SerializerMethodField()
    auditor_atual_id = serializers.SerializerMethodField()
    
    # Campos de Escrita
    cliente_id = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all(), source='cliente', write_only=False)

    vendedor_recebe_adiantamento_sabado = serializers.SerializerMethodField()
    classificacao_mei = serializers.SerializerMethodField()
    classificacao_mei_descricao = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'vendedor_nome', 'vendedor_recebe_adiantamento_sabado', 'cliente_id',
            'cliente_nome_razao_social', 'cliente_cpf_cnpj', 'cliente_email',
            'classificacao_mei', 'classificacao_mei_descricao',
            'plano_nome', 'forma_pagamento_nome',
            'status_tratamento', 'status_tratamento_nome',
            'status_esteira', 'status_esteira_nome',
            'status_comissionamento', 'status_comissionamento_nome',
            'motivo_pendencia', 'motivo_pendencia_nome', 'motivo_pendencia_tipo',
            'status_agendamento', 'status_agendamento_nome', 'status_agendamento_cor',
            'pap_status_consultado_em', 'pap_status_consultado_matricula', 'pap_status_consulta_erro',
            'nio_reagendamento_status', 'nio_reagendamento_em', 'nio_reagendamento_msg',
            'data_criacao', 'forma_entrada', 'cpf_representante_legal', 'nome_representante_legal',
            'nome_mae', 'data_nascimento', 'mes_nascimento_pap', 'telefone1', 'telefone2', 'cep', 'logradouro', 'numero_residencia',
            'complemento', 'bairro', 'cidade', 'estado',             'data_abertura', 'ordem_servico', 'data_agendamento',
            'periodo_agendamento', 'data_instalacao', 'data_instalacao_fisica', 'antecipou_instalacao', 'antecipacao_comissao',
            'flag_adiant_cnpj', 'adiantamento_cnpj_realizado_em', 'adiantamento_cnpj_realizado_por',
            'ponto_referencia', 'observacoes', 'data_pagamento', 'valor_pago',
            'auditor_atual', 'auditor_atual_nome', 'auditor_atual_id',
            'nome_editor', 'data_ultima_alteracao', 'gerada_os_automatica',
            'bloquear_atualizacao_status_osab',
            'biometria_aprovada', 'biometria_consultada_em', 'biometria_data_apta',
            'cliente_confirmou_auditoria', 'protocolo_confirmacao_auditoria', 'data_confirmacao_auditoria',
            'cliente_confirmou_lembrete_instalacao', 'cliente_resposta_lembrete_instalacao', 'data_resposta_lembrete_instalacao',
            'vendedor_pode_antecipar', 'vendedor_pode_antecipar_turno',
            'vendedor_resposta_posso_antecipar', 'vendedor_obs_posso_antecipar',
            'data_solicitacao_posso_antecipar', 'data_resposta_posso_antecipar',
            'consultor_pode_reagendar', 'consultor_reagendar_data', 'consultor_reagendar_turno',
            'consultor_reagendar_resposta',
            'data_solicitacao_reagendar_consultor', 'data_resposta_reagendar_consultor',
            'vendedor_lista_agendamento_status', 'vendedor_lista_reagendar_data',
            'vendedor_lista_reagendar_turno', 'vendedor_lista_agendamento_resposta',
            'data_envio_lista_agendamento', 'data_resposta_lista_agendamento',
            'boas_vindas_enviado_em', 'cliente_resposta_boas_vindas', 'data_resposta_boas_vindas',
            'adiantamento_sabado_marcado', 'adiantamento_sabado_valor', 'adiantamento_sabado_marcado_em',
            'adiantamento_sabado_manual', 'adiantamento_sabado_obs_manual', 'adiantamento_sabado_quitado_em',
            'flag_desc_adiantamento_sabado',
        ]

    def get_auditor_atual_nome(self, obj):
        return obj.auditor_atual.get_full_name() or obj.auditor_atual.username if obj.auditor_atual else None
    
    def get_auditor_atual_id(self, obj):
        return obj.auditor_atual.id if obj.auditor_atual else None
    
    def get_nome_editor(self, obj):
        return obj.editado_por.username if obj.editado_por else None

    def get_vendedor_recebe_adiantamento_sabado(self, obj):
        if not obj.vendedor_id:
            return False
        return bool(getattr(obj.vendedor, 'recebe_adiantamento_sabado', False))

    def get_classificacao_mei(self, obj):
        from crm_app.services.cnpj_mei_service import classificacao_mei_venda
        return classificacao_mei_venda(obj)

    def get_classificacao_mei_descricao(self, obj):
        from crm_app.services.cnpj_mei_service import classificacao_mei_venda, rotulo_classificacao_mei
        doc = obj.cliente.cpf_cnpj if obj.cliente_id else ''
        return rotulo_classificacao_mei(classificacao_mei_venda(obj), documento=doc)


class VendaListSerializer(VendaSerializer):
    """Listagem enxuta — omite textos longos irrelevantes para tabelas (esteira, auditoria, comissão)."""

    class Meta(VendaSerializer.Meta):
        fields = [
            f for f in VendaSerializer.Meta.fields
            if f not in (
                'observacoes',
                'cliente_email',
                'vendedor_obs_posso_antecipar',
                'adiantamento_sabado_obs_manual',
                'cliente_resposta_lembrete_instalacao',
                'cliente_resposta_boas_vindas',
                'boas_vindas_enviado_em',
                'data_resposta_boas_vindas',
            )
        ]


class VendaResumoAuditoriaSerializer(serializers.ModelSerializer):
    """Campos mínimos para tabelas do resumo mensal de auditoria."""

    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social', read_only=True)
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    vendedor_nome = serializers.ReadOnlyField(source='vendedor.username')
    plano_nome = serializers.CharField(source='plano.nome', read_only=True)
    status_tratamento_nome = serializers.CharField(source='status_tratamento.nome', read_only=True)

    class Meta:
        model = Venda
        fields = [
            'id',
            'data_criacao',
            'data_confirmacao_auditoria',
            'cliente_nome_razao_social',
            'cliente_cpf_cnpj',
            'vendedor_nome',
            'plano_nome',
            'status_tratamento_nome',
        ]


class VendaDetailSerializer(serializers.ModelSerializer):
    """
    Serializer COMPLETO para visualizar detalhes (retrieve/PUT)
    Carrega serializers aninhados completos
    """
    # Objetos completos (apenas em detail view, não em list)
    cliente = ClienteSerializer(read_only=True)
    vendedor_detalhes = UsuarioSerializer(source='vendedor', read_only=True)
    plano = PlanoSerializer(read_only=True)
    forma_pagamento = FormaPagamentoSerializer(read_only=True)
    status_tratamento = StatusCRMSerializer(read_only=True)
    status_esteira = StatusCRMSerializer(read_only=True)
    status_comissionamento = StatusCRMSerializer(read_only=True)
    motivo_pendencia = MotivoPendenciaSerializer(read_only=True)
    status_agendamento = StatusAgendamentoSerializer(read_only=True)
    
    # Campos Achatados para compatibilidade
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social')
    cliente_email = serializers.CharField(source='cliente.email', read_only=True)
    
    # Histórico (apenas em detail, NÃO em list)
    historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True, read_only=True)
    classificacao_mei_descricao = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'vendedor_detalhes', 'cliente',
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'classificacao_mei', 'classificacao_mei_descricao',
            'plano', 'forma_pagamento', 'status_tratamento', 'status_esteira',
            'status_comissionamento',             'motivo_pendencia', 'status_agendamento',
            'pap_status_consultado_em', 'pap_status_consultado_matricula', 'pap_status_consulta_erro',
            'nome_mae', 'data_nascimento', 'mes_nascimento_pap', 'telefone1', 'telefone2',
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro', 'cidade', 'estado',
            'ponto_referencia', 'observacoes', 'ordem_servico', 'data_abertura',
            'data_agendamento', 'periodo_agendamento', 'data_instalacao', 'data_instalacao_fisica', 'antecipou_instalacao', 'antecipacao_comissao',
            'flag_adiant_cnpj', 'adiantamento_cnpj_realizado_em', 'adiantamento_cnpj_realizado_por',
            'data_pagamento', 'valor_pago', 'cpf_representante_legal', 'nome_representante_legal',
            'forma_entrada', 'tem_fixo', 'historico_alteracoes', 'data_criacao', 'data_ultima_alteracao',
            'gerada_os_automatica',
            'bloquear_atualizacao_status_osab',
            'biometria_aprovada', 'biometria_consultada_em', 'biometria_data_apta',
            'cliente_confirmou_auditoria', 'protocolo_confirmacao_auditoria', 'data_confirmacao_auditoria',
            'cliente_confirmou_lembrete_instalacao', 'cliente_resposta_lembrete_instalacao', 'data_resposta_lembrete_instalacao',
            'vendedor_pode_antecipar', 'vendedor_pode_antecipar_turno',
            'vendedor_resposta_posso_antecipar', 'vendedor_obs_posso_antecipar',
            'data_solicitacao_posso_antecipar', 'data_resposta_posso_antecipar',
            'consultor_pode_reagendar', 'consultor_reagendar_data', 'consultor_reagendar_turno',
            'consultor_reagendar_resposta',
            'data_solicitacao_reagendar_consultor', 'data_resposta_reagendar_consultor',
            'vendedor_lista_agendamento_status', 'vendedor_lista_reagendar_data',
            'vendedor_lista_reagendar_turno', 'vendedor_lista_agendamento_resposta',
            'data_envio_lista_agendamento', 'data_resposta_lista_agendamento',
            'boas_vindas_enviado_em', 'cliente_resposta_boas_vindas', 'data_resposta_boas_vindas',
            'adiantamento_sabado_marcado', 'adiantamento_sabado_valor', 'adiantamento_sabado_marcado_em',
            'adiantamento_sabado_marcado_por', 'adiantamento_sabado_manual', 'adiantamento_sabado_obs_manual',
            'adiantamento_sabado_quitado_em', 'flag_desc_adiantamento_sabado',
        ]

    def get_classificacao_mei_descricao(self, obj):
        from crm_app.services.cnpj_mei_service import rotulo_classificacao_mei
        doc = obj.cliente.cpf_cnpj if obj.cliente_id else ''
        return rotulo_classificacao_mei(obj.classificacao_mei, documento=doc)

class VendaCreateSerializer(serializers.ModelSerializer):
    # Campos de Plano e Pagamento opcionais para criação flexível
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False, allow_null=True)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False, allow_null=True)
    
    cliente_cpf_cnpj = serializers.CharField(write_only=True, max_length=18)
    cliente_nome_razao_social = serializers.CharField(write_only=True, max_length=255)
    cliente_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    
    telefone1 = serializers.CharField(max_length=20, required=True)
    telefone2 = serializers.CharField(max_length=20, required=True)
    
    def validate_telefone1(self, value):
        """Valida Telefone 1: DDD válido no Brasil e 11 dígitos"""
        import re
        telefone_limpo = re.sub(r'\D', '', value)
        
        # Verifica se tem 11 dígitos
        if len(telefone_limpo) != 11:
            raise serializers.ValidationError("O telefone deve ter 11 dígitos (DDD + número).")
        
        # Extrai DDD (2 primeiros dígitos)
        ddd = telefone_limpo[:2]
        ddd_num = int(ddd)
        
        # DDDs válidos no Brasil (lista oficial)
        ddd_validos = [11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 52, 53, 54, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99]
        
        if ddd_num not in ddd_validos:
            raise serializers.ValidationError("DDD inválido. Informe um DDD válido do Brasil (não aceita código 55).")
        
        return value
    
    def validate_telefone2(self, value):
        """Valida Telefone 2: DDD válido no Brasil e 11 dígitos"""
        import re
        telefone_limpo = re.sub(r'\D', '', value)
        
        # Verifica se tem 11 dígitos
        if len(telefone_limpo) != 11:
            raise serializers.ValidationError("O telefone deve ter 11 dígitos (DDD + número).")
        
        # Extrai DDD (2 primeiros dígitos)
        ddd = telefone_limpo[:2]
        ddd_num = int(ddd)
        
        # DDDs válidos no Brasil (lista oficial)
        ddd_validos = [11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 52, 53, 54, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99]
        
        if ddd_num not in ddd_validos:
            raise serializers.ValidationError("DDD inválido. Informe um DDD válido do Brasil (não aceita código 55).")
        
        return value
    
    # Campos de endereço opcionais no Serializer
    cep = serializers.CharField(required=False, allow_blank=True)
    logradouro = serializers.CharField(required=False, allow_blank=True)
    numero_residencia = serializers.CharField(required=False, allow_blank=True)
    bairro = serializers.CharField(required=False, allow_blank=True)
    cidade = serializers.CharField(required=False, allow_blank=True)
    estado = serializers.CharField(required=False, allow_blank=True)
    ponto_referencia = serializers.CharField(max_length=255, required=False, allow_blank=True)
    
    cpf_representante_legal = serializers.CharField(max_length=14, required=False, allow_blank=True)
    nome_representante_legal = serializers.CharField(max_length=255, required=False, allow_blank=True)
    nome_mae = serializers.CharField(max_length=255, required=False, allow_blank=True)
    data_nascimento = serializers.DateField(required=False, allow_null=True)
    observacoes = serializers.CharField(required=False, allow_blank=True)
    gerada_os_automatica = serializers.BooleanField(required=False, default=False)
    vendedor = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all(), required=False, allow_null=True)
    classificacao_mei = serializers.CharField(read_only=True)
    classificacao_mei_descricao = serializers.CharField(read_only=True)

    class Meta:
        model = Venda
        fields = [
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'classificacao_mei', 'classificacao_mei_descricao',
            'nome_mae', 'data_nascimento', 'mes_nascimento_pap', 'forma_pagamento', 'plano', 'cep',
            'logradouro', 'numero_residencia', 'complemento', 'bairro', 'cidade', 'estado',
            'forma_entrada', 'tem_fixo', 'telefone1', 'telefone2', 'cpf_representante_legal',
            'nome_representante_legal', 'ponto_referencia', 'observacoes',
            'gerada_os_automatica', 'vendedor'
        ]

    def validate(self, data):
        for key, value in data.items():
            if isinstance(value, str) and key not in ['cliente_email', 'observacoes', 'nome_mae']:
                data[key] = value.upper()
        return data

class VendaUpdateSerializer(serializers.ModelSerializer):
    # data_instalacao_fisica: editável apenas por BackOffice/Diretoria/Admin (validado em validate)
    data_criacao = serializers.DateTimeField(required=False)
    # Campos "Manuais" para evitar conflito de nesting e validação
    cliente_nome_razao_social = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)
    cliente_cpf_cnpj = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)
    cliente_email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, write_only=True)

    vendedor = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all(), required=False)
    
    # --- CORREÇÃO: allow_null=True em todos os campos que podem ser nulos no rascunho ---
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False, allow_null=True)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False, allow_null=True)
    status_tratamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Tratamento'), required=False, allow_null=True)
    status_esteira = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Esteira'), required=False, allow_null=True)
    status_comissionamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Comissionamento'), required=False, allow_null=True)
    motivo_pendencia = serializers.PrimaryKeyRelatedField(queryset=MotivoPendencia.objects.all().order_by('nome'), required=False, allow_null=True)
    status_agendamento = serializers.PrimaryKeyRelatedField(
        queryset=StatusAgendamento.objects.all().order_by('ordem', 'nome'),
        required=False,
        allow_null=True,
    )
    # ------------------------------------------------------------------------------------

    class Meta:
        model = Venda
        fields = '__all__'
        read_only_fields = (
            'forma_entrada', 'cliente',
            'adiantamento_sabado_marcado', 'adiantamento_sabado_valor', 'adiantamento_sabado_marcado_em',
            'adiantamento_sabado_marcado_por', 'adiantamento_sabado_manual', 'adiantamento_sabado_obs_manual',
            'adiantamento_sabado_quitado_em', 'flag_desc_adiantamento_sabado',
        )

    @staticmethod
    def _os_valida(valor):
        if not valor:
            return False
        return bool(re.fullmatch(r'(\d{8}|\d-\d{12})', str(valor).strip()))

    def validate(self, data):
        # data_instalacao_fisica: somente BackOffice/Diretoria/Admin podem alterar
        from crm_app.utils import is_member
        request = self.context.get('request')
        if request and 'data_criacao' in data:
            if not is_member(request.user, ['Diretoria', 'Admin']):
                data.pop('data_criacao', None)
            else:
                from datetime import datetime
                from django.utils import timezone

                data_criacao = data.get('data_criacao')
                if isinstance(data_criacao, datetime) and timezone.is_naive(data_criacao):
                    data['data_criacao'] = timezone.make_aware(
                        data_criacao,
                        timezone.get_current_timezone(),
                    )
        if request and 'data_abertura' in data:
            if not is_member(request.user, ['Diretoria', 'Admin', 'BackOffice']):
                data.pop('data_abertura', None)
            else:
                from datetime import datetime
                from django.utils import timezone

                data_abertura = data.get('data_abertura')
                if data_abertura == '':
                    data['data_abertura'] = None
                elif isinstance(data_abertura, datetime) and timezone.is_naive(data_abertura):
                    data['data_abertura'] = timezone.make_aware(
                        data_abertura,
                        timezone.get_current_timezone(),
                    )
        if request and 'data_instalacao_fisica' in data and not is_member(request.user, ['Diretoria', 'Admin', 'BackOffice', 'Auditoria', 'Qualidade']):
            data.pop('data_instalacao_fisica', None)
        # Antecipação de comissão: somente perfis de gestão da esteira
        if request and 'antecipacao_comissao' in data and not is_member(request.user, ['Diretoria', 'Admin', 'BackOffice', 'Supervisor']):
            data.pop('antecipacao_comissao', None)
        # Converte para maiúsculo, exceto email, obs e campos de data/hora
        for key, value in data.items():
            if value is None: continue
            if isinstance(value, str) and key not in [
                'cliente_email', 'observacoes', 'nome_mae', 'data_criacao', 'data_abertura',
            ]:
                data[key] = value.upper()

        ordem_servico = (data.get('ordem_servico', getattr(self.instance, 'ordem_servico', None)) or '').strip()
        if ordem_servico and not self._os_valida(ordem_servico):
            raise serializers.ValidationError({
                'ordem_servico': 'Formato inválido. Use 8 dígitos (ex: 08907507) ou X-12DÍGITOS (ex: 4-212051254235).'
            })

        status_esteira = data.get('status_esteira', getattr(self.instance, 'status_esteira', None))
        status_tratamento = data.get('status_tratamento', getattr(self.instance, 'status_tratamento', None))
        status_esteira_nome = (getattr(status_esteira, 'nome', '') or '').upper()
        status_tratamento_nome = (getattr(status_tratamento, 'nome', '') or '').upper()

        exige_os = ('INSTALADA' in status_esteira_nome) or (status_tratamento_nome == 'CADASTRADA')
        if exige_os and not self._os_valida(ordem_servico):
            raise serializers.ValidationError({
                'ordem_servico': 'O.S obrigatória e válida para status INSTALADA/CADASTRADA. Use 8 dígitos ou X-12DÍGITOS.'
            })

        if request and 'bloquear_atualizacao_status_osab' in data:
            if not is_member(request.user, ['Diretoria', 'Admin']):
                if self.instance is not None:
                    data['bloquear_atualizacao_status_osab'] = self.instance.bloquear_atualizacao_status_osab
                else:
                    data.pop('bloquear_atualizacao_status_osab', None)

        return data

    def _get_field_repr(self, instance_value):
        if hasattr(instance_value, 'nome'): return instance_value.nome
        return str(instance_value)

    def update(self, instance, validated_data):
        request = self.context.get('request')
        user = request.user if request else None

        # 1. Atualização Manual dos Dados do Cliente
        cliente_instance = instance.cliente
        mudou_cliente = False
        
        # Pega os valores "write_only" validados
        novo_nome = validated_data.pop('cliente_nome_razao_social', None)
        novo_cpf = validated_data.pop('cliente_cpf_cnpj', None)
        novo_email = validated_data.pop('cliente_email', None)

        if novo_nome and novo_nome.strip() and novo_nome != cliente_instance.nome_razao_social:
            cliente_instance.nome_razao_social = novo_nome.upper()
            mudou_cliente = True
        
        if novo_cpf and novo_cpf.strip():
            novo_cpf_limpo = re.sub(r'\D', '', str(novo_cpf))
            cpf_atual_limpo = re.sub(r'\D', '', str(cliente_instance.cpf_cnpj or ''))

            if novo_cpf_limpo and novo_cpf_limpo != cpf_atual_limpo:
                cliente_duplicado = (
                    Cliente.objects
                    .filter(cpf_cnpj__in=[str(novo_cpf), novo_cpf_limpo])
                    .exclude(pk=cliente_instance.pk)
                    .first()
                )
                if cliente_duplicado:
                    raise serializers.ValidationError({
                        'cliente_cpf_cnpj': 'Este CPF/CNPJ já está cadastrado em outro cliente.'
                    })

                # Salva sempre em formato normalizado para reduzir conflitos de máscara.
                cliente_instance.cpf_cnpj = novo_cpf_limpo
                mudou_cliente = True
            
        if novo_email is not None and novo_email != cliente_instance.email:
            cliente_instance.email = novo_email
            mudou_cliente = True

        if mudou_cliente:
            cliente_instance.save()

        # 2. Histórico de Alterações
        alteracoes = {}
        campos_status = ['status_tratamento', 'status_esteira', 'status_comissionamento']
        for campo in campos_status:
            novo = validated_data.get(campo)
            if novo:
                antigo = getattr(instance, campo)
                if novo != antigo:
                    alteracoes[campo] = {'de': self._get_field_repr(antigo) if antigo else "Nenhum", 'para': self._get_field_repr(novo)}

        # 3. Automatização de Esteira
        novo_tratamento = validated_data.get('status_tratamento', instance.status_tratamento)
        if novo_tratamento and novo_tratamento.nome.lower() == 'cadastrada' and not instance.status_esteira:
            try:
                st_ini = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                validated_data['status_esteira'] = st_ini
            except: pass

        # 4. Automatização: Quando reemissão é marcada, definir status_esteira como AGENDADO
        nova_reemissao = validated_data.get('reemissao')
        if nova_reemissao is not None:  # Campo foi enviado na requisição
            if nova_reemissao and not instance.reemissao:  # Reemissão foi marcada como True (mudou de False para True)
                try:
                    st_agendado = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                    validated_data['status_esteira'] = st_agendado
                    if 'status_esteira' not in alteracoes:
                        alteracoes['status_esteira'] = {
                            'de': self._get_field_repr(instance.status_esteira) if instance.status_esteira else "Nenhum",
                            'para': 'AGENDADO'
                        }
                except StatusCRM.DoesNotExist:
                    pass

        novo_esteira = validated_data.get('status_esteira', instance.status_esteira)
        if novo_esteira and novo_esteira.nome.lower() == 'instalada' and not instance.status_comissionamento:
            try:
                st_com = StatusCRM.objects.get(nome__iexact="PENDENTE", tipo__iexact="Comissionamento")
                validated_data['status_comissionamento'] = st_com
            except: pass

        updated_instance = super().update(instance, validated_data)

        # 4. Atualiza auditor/editor
        if user:
            updated_instance.editado_por = user
            updated_instance.save(update_fields=['editado_por'])

        if alteracoes and user:
            HistoricoAlteracaoVenda.objects.create(venda=updated_instance, usuario=user, alteracoes=alteracoes)

        return updated_instance

    def validate_telefone(self, value, field_name):
        if not value: return value
        telefone_limpo = re.sub(r'\D', '', str(value))
        
        # Verifica se tem 11 dígitos
        if len(telefone_limpo) != 11:
            raise serializers.ValidationError(f"{field_name}: O telefone deve ter 11 dígitos (DDD + número).")
        
        # Extrai DDD (2 primeiros dígitos)
        ddd = telefone_limpo[:2]
        ddd_num = int(ddd)
        
        # DDDs válidos no Brasil (lista oficial)
        ddd_validos = [11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 52, 53, 54, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99]
        
        if ddd_num not in ddd_validos:
            raise serializers.ValidationError(f"{field_name}: DDD inválido. Informe um DDD válido do Brasil (não aceita código 55).")
        
        return value
    def validate_telefone1(self, value): return self.validate_telefone(value, "Telefone 1")
    def validate_telefone2(self, value): return self.validate_telefone(value, "Telefone 2")

class ImportacaoOsabSerializer(serializers.ModelSerializer):
    class Meta: model = ImportacaoOsab; fields = '__all__'
class ImportacaoChurnSerializer(serializers.ModelSerializer):
    class Meta: model = ImportacaoChurn; fields = '__all__'
class CicloPagamentoSerializer(serializers.ModelSerializer):
    class Meta: model = CicloPagamento; fields = '__all__'

class ComissaoOperadoraSerializer(serializers.ModelSerializer):
    plano_nome = serializers.ReadOnlyField(source='plano.nome')
    class Meta:
        model = ComissaoOperadora
        fields = '__all__'

class ComunicadoSerializer(serializers.ModelSerializer):
    criado_por_nome = serializers.ReadOnlyField(source='criado_por.username')
    vendedor_nome = serializers.SerializerMethodField()
    filtros_resumo = serializers.SerializerMethodField()

    def get_vendedor_nome(self, obj: Comunicado) -> str | None:
        if not obj.vendedor_id:
            return None
        vendedor = obj.vendedor
        if not vendedor:
            return None
        nome = getattr(vendedor, 'get_full_name', None) and vendedor.get_full_name()
        if nome and str(nome).strip():
            return str(nome).strip()
        return vendedor.username

    def get_filtros_resumo(self, obj: Comunicado) -> str:
        partes: list[str] = [obj.get_perfil_destino_display()]
        if obj.canal_alvo and obj.canal_alvo != 'TODOS':
            partes.append(f"Canal: {obj.get_canal_alvo_display()}")
        cluster = (obj.cluster_alvo or '').strip()
        if cluster and cluster.upper() != 'TODOS':
            partes.append(f"Cluster: {cluster}")
        if obj.vendedor_id:
            partes.append(f"Vendedor: {self.get_vendedor_nome(obj) or obj.vendedor_id}")
        status = (obj.status_destinatarios or 'somente_ativos')
        if status != 'somente_ativos':
            partes.append(obj.get_status_destinatarios_display())
        if (obj.representatividade_minima or 0) > 0:
            partes.append(f"Repr. ≥ {obj.representatividade_minima}%")
        return ' · '.join(partes)

    class Meta:
        model = Comunicado
        fields = '__all__'
        read_only_fields = ['criado_por', 'criado_em']
class GrupoDisparoSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrupoDisparo
        fields = '__all__'
class LancamentoFinanceiroSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.SerializerMethodField()
    criado_por_nome = serializers.ReadOnlyField(source='criado_por.username')

    def get_usuario_nome(self, obj):
        if not obj.usuario:
            return 'N/A'
        nome = getattr(obj.usuario, 'get_full_name', None) and obj.usuario.get_full_name()
        if nome and nome.strip():
            return nome.strip()
        return obj.usuario.username or 'N/A'

    class Meta:
        model = LancamentoFinanceiro
        fields = '__all__'

class FaturaM10Serializer(serializers.ModelSerializer):
    """Serializer para as faturas do Bônus M-10"""
    arquivo_pdf_url = serializers.SerializerMethodField()
    
    class Meta:
        model = FaturaM10
        fields = [
            'id', 'contrato', 'numero_fatura', 'numero_fatura_operadora',
            'valor', 'data_vencimento', 'data_pagamento', 'dias_atraso',
            'status', 'codigo_pix', 'codigo_barras', 'pdf_url', 'arquivo_pdf',
            'arquivo_pdf_url', 'observacao', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['criado_em', 'atualizado_em']
    
    def get_arquivo_pdf_url(self, obj):
        """Retorna a URL completa do PDF se existir"""
        if obj.pdf_url:
            return obj.pdf_url
        if obj.arquivo_pdf:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.arquivo_pdf.url)
            return obj.arquivo_pdf.url
        return None