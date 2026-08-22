import calendar
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone


def is_member(user, groups):
    """Verifica se o usuário pertence a algum dos grupos (por Group ou Perfil). Usado para regras de permissão."""
    if not user:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if user.groups.filter(name__in=groups).exists():
        return True
    try:
        if hasattr(user, 'perfil_id') and user.perfil_id:
            perfil = user.perfil
            if perfil and perfil.nome in groups:
                return True
    except Exception:
        pass
    return False


def vendedor_ou_supervisor_restrito_mes(user):
    return is_member(user, ['Vendedor', 'Supervisor'])


def mes_completo_vendedor_supervisor_valido(dt_ini: date, dt_fim: date, hoje_d: date) -> bool:
    """Mês civil completo (dia 1 ao último dia) e apenas mês atual ou mês anterior ao atual."""
    if dt_ini.day != 1:
        return False
    ultimo = calendar.monthrange(dt_ini.year, dt_ini.month)[1]
    if dt_fim != date(dt_ini.year, dt_ini.month, ultimo):
        return False
    cy, cm = hoje_d.year, hoje_d.month
    permitidos = {(cy, cm)}
    if cm == 1:
        permitidos.add((cy - 1, 12))
    else:
        permitidos.add((cy, cm - 1))
    return (dt_ini.year, dt_ini.month) in permitidos


def q_venda_acesso_retrieve_vendedor_supervisor():
    """
    Recorte permitido para detalhe: mês atual (criação a partir do dia 1 OU instalação no mês)
    OU qualquer venda com criação/instalação no mês civil anterior.
    """
    agora = timezone.localtime(timezone.now())
    hoje_d = agora.date()
    curr_start = hoje_d.replace(day=1)
    curr_start_dt = timezone.make_aware(datetime.combine(curr_start, datetime.min.time()))
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    atual_q = Q(data_criacao__gte=curr_start_dt) | Q(data_instalacao__gte=curr_start)
    anterior_q = (
        Q(data_criacao__date__gte=prev_start, data_criacao__date__lte=prev_end)
        | Q(data_instalacao__gte=prev_start, data_instalacao__lte=prev_end)
    )
    return atual_q | anterior_q


def listar_fachadas_dfv_por_endereco(endereco):
    """
    Busca fachadas por endereço (logradouro, bairro ou município) na base DFV.
    """
    if not endereco:
        return ["❌ *Endereço não informado.*"]
    endereco = endereco.strip().upper()
    fachadas = DFV.objects.filter(
        Q(logradouro__icontains=endereco) |
        Q(bairro__icontains=endereco) |
        Q(municipio__icontains=endereco)
    ).filter(
        Q(tipo_viabilidade__icontains='VIAVEL') | Q(tipo_viabilidade__icontains='VIÁVEL')
    ).values_list('num_fachada', 'complemento', 'logradouro', 'bairro', 'tipo_rede', 'nome_cdo', 'cep')
    if not fachadas:
        return [f"❌ *NENHUMA FACHADA ENCONTRADA*\n\nNão encontramos nenhum número viável cadastrado na base DFV para o endereço informado."]
    exemplo = fachadas[0]
    logradouro = exemplo[2] or "Rua Desconhecida"
    bairro = exemplo[3] or "Bairro Desconhecido"
    tecnologia = exemplo[4] or "-"
    nome_cdo = exemplo[5] or "-"
    cep = exemplo[6] or "-"
    def num_compl(num, compl):
        num = (num or '').strip()
        compl = (compl or '').strip()
        if compl:
            return f"{num} ({compl})"
        return num
    numeros = [num_compl(f[0], f[1]) for f in fachadas if f[0]]
    try:
        numeros.sort(key=lambda x: int(''.join(filter(str.isdigit, x.split(' ')[0]))) if any(c.isdigit() for c in x.split(' ')[0]) else 0)
    except:
        numeros.sort()
    total = len(numeros)
    lista_str = ", ".join(numeros)
    cdos = sorted(set([f[5] for f in fachadas if f[5]]))
    cdos_str = ', '.join(cdos) if cdos else '-'
    if len(lista_str) > 3000:
        lista_str = lista_str[:3000] + "... (lista muito longa)"
    mensagem = (
        f"🏢 *RELATÓRIO DE FACHADAS (DFV)*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro}\n"
        f"🏢 *NOME_CDO(s):* {cdos_str}\n"
        f"📡 *Tecnologia:* {tecnologia}\n"
        f"📬 *CEP:* {cep}\n"
        f"✅ *Total Viáveis:* {total}\n\n"
        f"🔢 *Números Disponíveis (com complemento):*\n"
        f"{lista_str}"
    )
    def split_message(msg, max_len=4096):
        return [msg[i:i+max_len] for i in range(0, len(msg), max_len)]
    return split_message(mensagem)
import logging
import requests
import re
from .models import DFV, AreaVenda
from .models import Venda # Certifique-se que Venda está importado

logger = logging.getLogger(__name__)

def limpar_texto(texto):
    if not texto: return ""
    return ''.join(filter(str.isdigit, str(texto)))

def buscar_coordenadas_viacep_nominatim(cep, numero):
    """
    Busca Lat/Lng usando o CEP para achar a rua e o Número para precisão.
    """
    try:
        # 1. Pega dados da Rua pelo ViaCEP
        url_viacep = f"https://viacep.com.br/ws/{cep}/json/"
        resp = requests.get(url_viacep, timeout=5)
        if resp.status_code != 200: return None
        data = resp.json()
        if 'erro' in data: return None
        
        logradouro = data.get('logradouro')
        cidade = data.get('localidade')
        uf = data.get('uf')
        bairro = data.get('bairro')
        
        # 2. Monta Query para OpenStreetMap (Nominatim)
        # Ex: "Rua das Flores, 123, Belo Horizonte - MG, Brasil"
        query = f"{logradouro}, {numero}, {cidade} - {uf}, Brasil"
        
        headers = {'User-Agent': 'RecordPAP_System/2.0'}
        url_geo = "https://nominatim.openstreetmap.org/search"
        # O '1' no limit tenta pegar o mais preciso
        params = {'q': query, 'format': 'json', 'limit': 1}
        
        resp_geo = requests.get(url_geo, params=params, headers=headers, timeout=5)
        
        # Se não achar com número, tenta só com a rua (menos preciso, mas serve de fallback)
        if not resp_geo.json():
            query_fallback = f"{logradouro}, {cidade} - {uf}, Brasil"
            params['q'] = query_fallback
            resp_geo = requests.get(url_geo, params=params, headers=headers, timeout=5)

        if resp_geo.status_code == 200 and resp_geo.json():
            res = resp_geo.json()[0]
            return {
                'lat': float(res['lat']),
                'lng': float(res['lon']),
                'endereco_str': f"{logradouro}, {numero} - {bairro}",
                'cidade': cidade,
                'bairro': bairro
            }
            
    except Exception as e:
        print(f"Erro geocoding: {e}")
    
    return None

def ponto_dentro_poligono(x, y, poligono):
    """
    Algoritmo Ray Casting para verificar se ponto (x,y) está dentro do polígono.
    x = lng, y = lat
    poligono = lista de tuplas [(lng, lat), (lng, lat)...]
    """
    n = len(poligono)
    inside = False
    p1x, p1y = poligono[0]
    for i in range(n + 1):
        p2x, p2y = poligono[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def parse_kml_coordinates(coords_str):
    """
    Transforma string do KML "lon,lat,z lon,lat,z" em lista de tuplas [(lon, lat)]
    """
    pontos = []
    if not coords_str: return []
    
    # KML separa por espaço ou quebra de linha
    items = coords_str.replace('\n', ' ').split(' ')
    for item in items:
        if not item: continue
        parts = item.split(',')
        if len(parts) >= 2:
            try:
                # KML é (Longitude, Latitude)
                lon = float(parts[0])
                lat = float(parts[1])
                pontos.append((lon, lat))
            except: pass
    return pontos

# --- FUNÇÕES DE CONSULTA ---

def consultar_fachada_dfv(cep, numero):
    """
    Busca EXATA na base DFV (Fachada). (Legado/Compatibilidade)
    Essa função valida um número específico se necessário.
    """
    cep_limpo = limpar_texto(cep)
    numero_limpo = str(numero).strip().upper()
    print(f"\n🔎 BUSCA DFV (FACHADA) -> CEP: {cep_limpo} | NUM: {numero_limpo}")

    dfv = DFV.objects.filter(cep=cep_limpo, num_fachada=numero_limpo).first()
    if not dfv and numero_limpo.isdigit():
        dfv = DFV.objects.filter(cep=cep_limpo, num_fachada=str(int(numero_limpo))).first()

    if dfv:
        tipo = dfv.tipo_viabilidade.upper() if dfv.tipo_viabilidade else ""
        return f"✅ *FACHADA LOCALIZADA (DFV)*\nStatus: *{tipo}*\nEnd: {dfv.logradouro}, {dfv.num_fachada}"
    else:
        return f"❌ *FACHADA NÃO ENCONTRADA*\nO número {numero_limpo} no CEP {cep_limpo} não consta na base DFV."

def listar_fachadas_dfv(cep):
    """
    Busca TODAS as fachadas (números) disponíveis para um CEP na base DFV.
    """
    cep_limpo = limpar_texto(cep)
    print(f"\n🔎 LISTAR FACHADAS DFV -> CEP: {cep_limpo}")

    # Busca todos os registros com esse CEP que sejam VIÁVEIS
    fachadas = DFV.objects.filter(
        cep=cep_limpo
    ).filter(
        Q(tipo_viabilidade__icontains='VIAVEL') | Q(tipo_viabilidade__icontains='VIÁVEL')
    ).values_list('num_fachada', 'complemento', 'logradouro', 'bairro', 'tipo_rede', 'nome_cdo')

    if not fachadas:
        return (
            f"❌ *NENHUMA FACHADA ENCONTRADA*\n\n"
            f"Não encontramos nenhum número viável cadastrado na base DFV para o CEP {cep_limpo}.\n"
            f"Tente a consulta de *Viabilidade (KMZ)* para ver se a região tem cobertura."
        )

    # Pega dados do logradouro do primeiro resultado para cabeçalho
    exemplo = fachadas[0]
    logradouro = exemplo[2] or "Rua Desconhecida"
    bairro = exemplo[3] or "Bairro Desconhecido"
    tecnologia = exemplo[4] or "-"
    nome_cdo = exemplo[5] or "-"

    # Monta lista de números + complemento
    def num_compl(num, compl):
        num = (num or '').strip()
        compl = (compl or '').strip()
        if compl:
            return f"{num} ({compl})"
        return num

    numeros = [num_compl(f[0], f[1]) for f in fachadas if f[0]]
    try:
        # Ordena pelo número (ignorando complemento)
        numeros.sort(key=lambda x: int(''.join(filter(str.isdigit, x.split(' ')[0]))) if any(c.isdigit() for c in x.split(' ')[0]) else 0)
    except:
        numeros.sort()

    total = len(numeros)
    lista_str = ", ".join(numeros)

    # Listar todos os NOME_CDOs distintos para o CEP
    cdos = sorted(set([f[5] for f in fachadas if f[5]]))
    cdos_str = ', '.join(cdos) if cdos else '-'

    # Se a lista for muito grande, corta para não travar o Zap
    if len(lista_str) > 3000:
        lista_str = lista_str[:3000] + "... (lista muito longa)"

    mensagem = (
        f"🏢 *RELATÓRIO DE FACHADAS (DFV)*\n\n"
        f"📍 *Endereço:* {logradouro}\n"
        f"🏙️ *Bairro:* {bairro}\n"
        f"🏢 *NOME_CDO(s):* {cdos_str}\n"
        f"📡 *Tecnologia:* {tecnologia}\n"
        f"✅ *Total Viáveis:* {total}\n\n"
        f"🔢 *Números Disponíveis (com complemento):*\n"
        f"{lista_str}"
    )

    # Função para dividir mensagem longa em partes de até 4096 caracteres
    def split_message(msg, max_len=4096):
        return [msg[i:i+max_len] for i in range(0, len(msg), max_len)]

    return split_message(mensagem)

def _cep_numero_viavel_no_dfv(cep_limpo, numero):
    """Retorna True se o CEP+número consta na base DFV como viável (fallback quando o mapa não localiza)."""
    if not cep_limpo or not numero:
        return False
    num_str = str(numero).strip()
    # Busca exata (391) ou só o número antes de parênteses (391 (BL 2) -> 391)
    num_limpo = num_str.split("(")[0].strip() if "(" in num_str else num_str
    if not num_limpo.isdigit():
        return False
    existe = DFV.objects.filter(
        cep=cep_limpo,
        num_fachada=num_limpo
    ).filter(
        Q(tipo_viabilidade__icontains='VIAVEL') | Q(tipo_viabilidade__icontains='VIÁVEL')
    ).exists()
    return existe


def consultar_viabilidade_kmz(cep, numero):
    """
    Lógica: CEP+Num -> Lat/Lng -> Verifica Polígono (KMZ).
    Se a geolocalização falhar, consulta a base DFV (fachadas); se o número estiver viável no DFV, retorna viável.
    """
    cep_limpo = limpar_texto(cep)
    print(f"\n🔎 BUSCA KMZ (GEO) -> CEP: {cep_limpo} | NUM: {numero}")

    # 1. Obter Coordenadas
    geo_data = buscar_coordenadas_viacep_nominatim(cep_limpo, numero)

    if not geo_data:
        # Fallback: verificar se CEP+número consta no DFV (base de fachadas viáveis)
        if _cep_numero_viavel_no_dfv(cep_limpo, numero):
            return (
                "✅ *VIABILIDADE TÉCNICA (DFV)*\n\n"
                "O endereço não foi localizado no mapa (KMZ), mas o número consta na base de fachadas como *viável*.\n\n"
                "⚠️ _Sujeito a vistoria técnica local._"
            )
        return "❌ *ENDEREÇO NÃO LOCALIZADO*\nNão conseguimos converter esse CEP e número em coordenadas GPS. Tente enviar a localização (pino) ou use o comando *DFV* para ver os números viáveis do CEP."

    cliente_lat = geo_data['lat']
    cliente_lng = geo_data['lng']
    print(f"📍 Cliente está em: {cliente_lat}, {cliente_lng}")

    # 2. Filtrar Áreas Prováveis (Pelo Bairro ou Cidade para não varrer tudo)
    # Isso otimiza a busca. Pegamos areas que tenham o nome da cidade ou bairro.
    areas_candidatas = AreaVenda.objects.filter(
        Q(municipio__icontains=geo_data['cidade']) | 
        Q(bairro__icontains=geo_data['bairro']) |
        Q(nome_kml__icontains=geo_data['bairro'])
    )
    
    # Se não achar por bairro/cidade, pega tudo (pode ser lento se tiver milhares)
    if not areas_candidatas.exists():
        print("⚠️ Bairro/Cidade não bateu com KMZ, verificando todas as áreas...")
        areas_candidatas = AreaVenda.objects.all()

    # 3. Teste Matemático (Ponto dentro do Polígono)
    for area in areas_candidatas:
        # Transforma texto do banco em lista de pontos
        poligono = parse_kml_coordinates(area.coordenadas)
        if not poligono: continue
        
        # Testa
        if ponto_dentro_poligono(cliente_lng, cliente_lat, poligono):
            return (
                f"✅ *VIABILIDADE TÉCNICA (KMZ)*\n\n"
                f"O endereço está DENTRO da área de cobertura!\n"
                f"🗺️ *Área/Cluster:* {area.nome_kml}\n"
                f"🏙️ *Bairro:* {area.bairro}\n"
                f"📍 *Local:* {geo_data['endereco_str']}\n\n"
                f"⚠️ _Sujeito a vistoria técnica local._"
            )

    return (
        f"❌ *FORA DA MANCHA (KMZ)*\n\n"
        f"O endereço foi localizado no mapa, mas as coordenadas ({cliente_lat}, {cliente_lng}) caem FORA das áreas cadastradas no sistema.\n"
        f"📍 *Local:* {geo_data['endereco_str']}"
    )

def verificar_viabilidade_por_coordenadas(lat, lng):
    # Fallback para o pino
    return {'msg': f"📍 Recebido ({lat}, {lng}). Use a opção de CEP para validação precisa."}

# Compatibilidade
def verificar_viabilidade_por_cep(cep): return {'msg': 'Use a nova busca.'}
def verificar_viabilidade_exata(cep, num): return {'msg': consultar_fachada_dfv(cep, num)}
def consultar_status_venda(tipo_busca, valor):
    """
    Busca a última venda baseada em CPF ou OS e retorna os status.
    tipo_busca: 'CPF' ou 'OS'
    """
    valor_limpo = limpar_texto(valor) # Remove pontos e traços
    print(f"\n🔎 BUSCA STATUS ({tipo_busca}) -> Valor: {valor_limpo}")

    venda = None

    if tipo_busca == 'CPF':
        # Busca pela venda mais recente desse CPF (ordena por ID decrescente ou data)
        # Nota: cliente__cpf_cnpj é o campo de busca no relacionamento
        venda = Venda.objects.filter(
            cliente__cpf_cnpj__icontains=valor_limpo, 
            ativo=True
        ).order_by('-data_criacao').first()

    elif tipo_busca == 'OS':
        # Busca exata pela OS
        venda = Venda.objects.filter(
            ordem_servico=valor_limpo, 
            ativo=True
        ).first()

    if venda:
        # Formata os dados para exibir
        cliente_nome = venda.cliente.nome_razao_social.upper() if venda.cliente else "NÃO INFORMADO"
        plano = venda.plano.nome if venda.plano else "-"
        
        st_tratamento = venda.status_tratamento.nome if venda.status_tratamento else "Sem Tratamento"
        st_esteira = venda.status_esteira.nome if venda.status_esteira else "Não iniciada"
        
        # Detalhe extra se tiver pendência
        extra_info = ""
        if "PENDEN" in st_esteira.upper() and venda.motivo_pendencia:
            extra_info = f"\n⚠️ *Motivo:* {venda.motivo_pendencia.nome}"
        
        if "AGENDADO" in st_esteira.upper() and venda.data_agendamento:
             data_fmt = venda.data_agendamento.strftime('%d/%m/%Y')
             extra_info = f"\n📅 *Data:* {data_fmt} ({venda.get_periodo_agendamento_display()})"

        return (
            f"📋 *STATUS DO PEDIDO*\n\n"
            f"👤 *Cliente:* {cliente_nome}\n"
            f"📦 *Plano:* {plano}\n"
            f"🔢 *O.S:* {venda.ordem_servico or 'S/N'}\n\n"
            f"🔧 *Status Esteira:* {st_esteira}"
            f"{extra_info}\n"
            f"📂 *Status Tratamento:* {st_tratamento}"
        )
    else:
        return (
            f"❌ *PEDIDO NÃO ENCONTRADO*\n\n"
            f"Não localizei nenhuma venda ativa com o {tipo_busca}: *{valor}*.\n"
            f"Verifique a digitação e tente novamente."
        )


def validar_venda_para_resumo_auditoria(venda):
    """
    Valida se a venda está completa para enviar o resumo ao cliente (auditoria).
    Retorna (True, None) se OK, ou (False, mensagem_erro) se faltar algo.
    Exige: endereço (CEP, logradouro, número), plano e forma de pagamento.
    """
    if not venda:
        return False, "Venda não informada."
    if not (venda.cep and str(venda.cep).strip()):
        return False, "Preencha o CEP (aba Endereço) antes de enviar o resumo."
    if not (venda.logradouro and str(venda.logradouro).strip()):
        return False, "Preencha o Logradouro (aba Endereço) antes de enviar o resumo."
    if not (venda.numero_residencia and str(venda.numero_residencia).strip()):
        return False, "Preencha o Número (aba Endereço) antes de enviar o resumo."
    if not venda.plano_id:
        return False, "Selecione o Plano (aba Oferta & Pagamento) antes de enviar o resumo."
    if not venda.forma_pagamento_id:
        return False, "Selecione a Forma de Pagamento (aba Oferta & Pagamento) antes de enviar o resumo."
    return True, None


def montar_resumo_plano_para_whatsapp(venda):
    """
    Monta o texto do resumo da venda (plano, pagamento, endereço completo, cliente) no mesmo
    formato usado no fluxo VENDER, para envio manual (ex.: auditoria enviar ao celular).
    Retorna string pronta para WhatsApp. Use validar_venda_para_resumo_auditoria antes.
    """
    if not venda:
        return ""
    cpf = (venda.cliente.cpf_cnpj or "") if venda.cliente else ""
    cpf_limpo = "".join(filter(str.isdigit, cpf))
    cpf_fmt = f"{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}" if len(cpf_limpo) == 11 else cpf

    celular = (venda.telefone1 or "")
    cel_limpo = "".join(filter(str.isdigit, celular))
    cel_fmt = f"({cel_limpo[:2]}) {cel_limpo[2:7]}-{cel_limpo[7:]}" if len(cel_limpo) >= 10 else celular

    email = (venda.cliente.email or "") if venda.cliente else ""

    # Endereço completo: CEP, logradouro, número, complemento, bairro, cidade, UF, referência
    cep = (venda.cep or "").strip()
    if len(cep) == 8 and cep.isdigit():
        cep = f"{cep[:5]}-{cep[5:]}"
    logradouro = (venda.logradouro or "").strip()
    numero = (venda.numero_residencia or "").strip()
    complemento = (venda.complemento or "").strip()
    bairro = (venda.bairro or "").strip()
    cidade = (venda.cidade or "").strip()
    estado = (venda.estado or "").strip()
    referencia = (venda.ponto_referencia or "").strip()

    linhas_endereco = [f"CEP: {cep}", f"Número: {numero}"]
    if logradouro:
        linhas_endereco.insert(1, f"Logradouro: {logradouro}")
    if complemento:
        linhas_endereco.append(f"Complemento: {complemento}")
    if bairro:
        linhas_endereco.append(f"Bairro: {bairro}")
    if cidade or estado:
        linhas_endereco.append(f"Cidade: {cidade}" + (f" - {estado}" if estado else ""))
    if referencia:
        linhas_endereco.append(f"Referência: {referencia}")
    bloco_endereco = "\n".join(linhas_endereco)

    forma_nome = (venda.forma_pagamento.nome or "") if venda.forma_pagamento else ""

    if venda.plano:
        from crm_app.services.gdp_preco_service import (
            VALOR_FIXO_NIO_MENSAL,
            formatar_moeda_br,
            resolver_valor_plano_venda,
        )

        valor_plano, _meta = resolver_valor_plano_venda(venda)
        plano_linha = f"{venda.plano.nome} - {formatar_moeda_br(valor_plano)}/mês"
        if venda.tem_fixo:
            total = float(valor_plano) + float(VALOR_FIXO_NIO_MENSAL)
            plano_linha = (
                f"{venda.plano.nome} - {formatar_moeda_br(valor_plano)}/mês "
                f"+ Fixo {formatar_moeda_br(VALOR_FIXO_NIO_MENSAL)}/mês "
                f"= {formatar_moeda_br(total)}/mês"
            )
    else:
        plano_linha = "Não informado"

    linhas_servicos_adicionais = []
    if venda.tem_fixo:
        linhas_servicos_adicionais.append(
            f"📞 *Fixo:* Sim – {formatar_moeda_br(VALOR_FIXO_NIO_MENSAL)}/mês"
        )
    # Modelo Venda não tem streaming; não exibir linha genérica "Não".

    nome_cliente = (venda.cliente.nome_razao_social or "").strip() if venda.cliente else ""
    if not nome_cliente:
        nome_cliente = "Não informado"

    bloco_servicos = ""
    if linhas_servicos_adicionais:
        bloco_servicos = "\n".join(linhas_servicos_adicionais) + "\n\n"

    return (
        f"📋 *RESUMO DO PEDIDO NIO FIBRA*\n\n"
        f"👤 *Cliente:* {nome_cliente}\n"
        f"CPF: {cpf_fmt}\n"
        f"Celular: {cel_fmt}\n"
        f"E-mail: {email}\n\n"
        f"📍 *Endereço:*\n"
        f"{bloco_endereco}\n\n"
        f"💳 *Pagamento:* {forma_nome}\n"
        f"📦 *Plano:* {plano_linha}\n"
        f"{bloco_servicos}"
        f"📅 *Fidelidade:* 12 meses\n\n"
        f"💰 *Taxa de habilitação:*\n"
        f"Você ganha isenção da taxa de habilitação se permanecer no mínimo 12 meses conosco.\n\n"
        f"Sua primeira fatura irá vencer *25 dias* após a instalação da internet; nos demais meses, "
        f"o vencimento segue o ciclo de *30 em 30 dias*.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Confirma a venda?\n\n"
        f"Digite *CONFIRMAR* para enviar ao PAP\n"
        f"Digite *CANCELAR* para desistir"
    )


def formatar_status_pap_para_whatsapp(status_texto):
    """Quando o PAP retorna Concluído, exibe Instalado para o consultor no WhatsApp."""
    if not status_texto:
        return status_texto
    s = (status_texto or "").strip()
    sl = s.lower()
    if "concluí" in sl or "concluido" in sl:
        return "Instalado"
    return s


def _normalizar_texto_status_pap(status_tabela):
    """Remove acentos/combinações Unicode para comparar status do PAP (ex.: Técnica vs Técnica NFC)."""
    import unicodedata

    st = (status_tabela or "").strip().lower()
    st = unicodedata.normalize("NFKD", st)
    return "".join(c for c in st if not unicodedata.combining(c))


def pap_status_indica_concluido(status_tabela, status_agendamento=None):
    """Indica instalação concluída no PAP (coluna Status ou detalhe Status agendamento)."""
    st = _normalizar_texto_status_pap(status_tabela)
    if "concluí" in st or "concluido" in st:
        return True
    sa = (status_agendamento or "").strip().lower()
    if sa and ("concluí" in sa or "concluido" in sa or "sucesso" in sa):
        return True
    return False


def pap_status_indica_pendencia_lista(status_tabela):
    """Coluna Status da lista PAP = Pendência Cliente ou Pendência Técnica."""
    st = _normalizar_texto_status_pap(status_tabela)
    if "penden" not in st:
        return False
    return "cliente" in st or "tecnica" in st


def pap_status_indica_em_aprovisionamento(status_tabela):
    """Coluna Status da lista PAP = Em Aprovisionamento (agendado no PAP)."""
    st = _normalizar_texto_status_pap(status_tabela)
    return "aprovisionamento" in st


def extrair_data_instalacao_texto_pap(agendamento_texto, status_agendamento_texto=None):
    """Extrai a data (date) do texto Agendamento (ex.: 26/03/2026 - Manhã)."""
    import re
    from datetime import datetime

    for texto in (agendamento_texto, status_agendamento_texto):
        if not texto:
            continue
        m = re.search(r"(\d{2}/\d{2}/\d{4})", texto)
        if m:
            try:
                return datetime.strptime(m.group(1), "%d/%m/%Y").date()
            except ValueError:
                pass
    return None


def _mapa_motivo_pendencia_por_codigo():
    """Mesma lógica da importação OSAB: chave = dígitos iniciais do nome (ex.: 7029, 0001)."""
    import re
    from crm_app.models import MotivoPendencia

    mapa = {}
    for m in MotivoPendencia.objects.all():
        match = re.match(r"^(\d+)", (m.nome or "").strip())
        if match:
            mapa[match.group(1)] = m
    return mapa


def resolver_motivo_pendencia_por_texto_pap(pendencia_texto):
    """
    Extrai os 4 primeiros dígitos do texto de pendência do PAP (ex.: 7029 - AGENDAMENTO…)
    e busca MotivoPendencia cadastrado (sem motivo genérico).
    """
    import re

    if not pendencia_texto or not str(pendencia_texto).strip():
        return None
    m = re.match(r"^(\d{4})", str(pendencia_texto).strip())
    if not m:
        return None
    codigo = m.group(1)
    mapa = _mapa_motivo_pendencia_por_codigo()
    return mapa.get(codigo)


def extrair_periodo_agendamento_texto_pap(agendamento_texto):
    """Extrai MANHA/TARDE do texto de Agendamento do PAP.

    Formatos comuns:
    - ``02/06/2026 - Tarde`` / ``… - Manhã``
    - ``31/07/2026 - 08:00 às 12:00`` (manhã)
    - ``31/07/2026 - 13:00 às 18:00`` (tarde)
    - ``08h às 12h``, ``10h-12h``, ``13h às 15h`` (2 ou 4 faixas)
    """
    import re

    if not agendamento_texto:
        return None
    t = (agendamento_texto or "").lower()
    if "tarde" in t:
        return "TARDE"
    if "manh" in t:
        return "MANHA"

    # Faixa horária: início < 13h = manhã; 13h+ = tarde
    m = re.search(
        r"(\d{1,2})\s*(?::|h)\s*\d{0,2}\s*(?:às|as|-|–|—)\s*(\d{1,2})",
        t,
        re.IGNORECASE,
    )
    if m:
        hora_inicio = int(m.group(1))
        if 0 <= hora_inicio < 13:
            return "MANHA"
        if hora_inicio <= 23:
            return "TARDE"
    return None


def pap_detalhe_tem_agendamento_com_data(agendamento_texto):
    return extrair_data_instalacao_texto_pap(agendamento_texto) is not None


def _os_pap_coincide(os_pap_raw, os_crm_raw):
    import re

    os_p = re.sub(r"\D", "", str(os_pap_raw or "")).strip()
    os_c = re.sub(r"\D", "", str(os_crm_raw or "")).strip()
    if not os_p or not os_c:
        return False
    return os_p == os_c or (os_p.lstrip("0") or os_p) == (os_c.lstrip("0") or os_c)


def buscar_venda_ativa_por_os_cpf(cpf_limpo, numero_os):
    """Venda ativa cuja O.S. coincide com a do PAP (mesmo CPF)."""
    import re
    from crm_app.models import Venda

    cpf_digits = limpar_texto(cpf_limpo)
    if len(cpf_digits) not in (11, 14):
        return None
    os_digits = re.sub(r"\D", "", str(numero_os or "")).strip()
    if not os_digits:
        return None
    for v in Venda.objects.filter(ativo=True, cliente__cpf_cnpj__icontains=cpf_digits).select_related(
        "status_esteira", "motivo_pendencia"
    ):
        if _os_pap_coincide(os_digits, v.ordem_servico):
            return v
    return None


def _esteira_permite_sync_status_pap(venda):
    st_u = ((venda.status_esteira.nome if venda.status_esteira else "") or "").upper()
    if "INSTALAD" in st_u:
        return False
    return "AGENDADO" in st_u or "PENDENCI" in st_u


def obter_os_prioridade_crm_por_cpf(cpf_limpo):
    """O.S. de vendas ativas do CPF (normalizadas) — usar em thread sync antes do Playwright."""
    import re
    from crm_app.models import Venda

    cpf_digits = limpar_texto(cpf_limpo)
    if len(cpf_digits) not in (11, 14):
        return set()
    os_set = set()
    for os_val in Venda.objects.filter(
        ativo=True, cliente__cpf_cnpj__icontains=cpf_digits
    ).values_list("ordem_servico", flat=True):
        os_d = re.sub(r"\D", "", str(os_val or "")).strip()
        if not os_d:
            continue
        os_set.add(os_d)
        os_sem = os_d.lstrip("0") or os_d
        if os_sem:
            os_set.add(os_sem)
    return os_set


def ordenar_detalhes_pap_por_os_prioridade(detalhes_pap, os_prioridade):
    """Prioriza linhas cuja O.S. está em os_prioridade (sem acesso ao ORM)."""
    if not detalhes_pap:
        return []
    if not os_prioridade:
        return list(detalhes_pap)
    import re

    com_crm = []
    sem_crm = []
    for d in detalhes_pap:
        os_d = re.sub(r"\D", "", str(d.get("numero_os") or "")).strip()
        os_sem = (os_d.lstrip("0") or os_d) if os_d else ""
        if os_d and (os_d in os_prioridade or os_sem in os_prioridade):
            com_crm.append(d)
        else:
            sem_crm.append(d)
    return com_crm + sem_crm


def ordenar_detalhes_pap_crm_primeiro(cpf_limpo, detalhes_pap):
    """Prioriza linhas cuja O.S. existe no CRM (ativo). Só em contexto sync (não durante Playwright)."""
    return ordenar_detalhes_pap_por_os_prioridade(
        detalhes_pap, obter_os_prioridade_crm_por_cpf(cpf_limpo)
    )


def montar_legenda_pedido_status_pap(d, tempo_decorrido=None):
    """Legenda de um único pedido para envio separado no WhatsApp."""
    st_exibir = formatar_status_pap_para_whatsapp(d.get("status", ""))
    partes = ["📡 *Status online (PAP)*\n\n"]
    if d.get("nao_pertence_pdv"):
        partes.append("⚠️ Pedido emitido, porém não pertence ao seu PDV.\n\n")
    partes.append(f"• *Status:* {st_exibir}\n")
    partes.append(f"• *Data:* {d.get('data_hora', '')}\n")
    partes.append(f"• *Plano:* {d.get('plano', '')}\n")
    partes.append(f"• *Nº OS:* {d.get('numero_os', '')}\n")
    if not d.get("nao_pertence_pdv"):
        if d.get("status_agendamento"):
            partes.append(f"• *Status agendamento:* {d.get('status_agendamento')}\n")
        if d.get("agendamento"):
            partes.append(f"• *Agendamento:* {d.get('agendamento')}\n")
        if d.get("pendencia"):
            partes.append(f"• *Pendência:* {d.get('pendencia')}\n")
    if tempo_decorrido is not None:
        partes.append(f"\n⏱ _{tempo_decorrido}s_")
    return "".join(partes)


def _snapshot_venda_sync_pap(venda):
    """Estado da venda antes/depois da sincronização PAP."""
    return {
        "status_esteira_id": venda.status_esteira_id,
        "status_esteira_nome": (venda.status_esteira.nome if venda.status_esteira else "") or "",
        "motivo_pendencia_id": venda.motivo_pendencia_id,
        "status_agendamento_id": venda.status_agendamento_id,
        "data_agendamento": venda.data_agendamento,
        "periodo_agendamento": venda.periodo_agendamento or "",
        "data_instalacao": venda.data_instalacao,
    }


def _venda_sync_pap_alterou(antes, depois):
    return (
        antes["status_esteira_id"] != depois["status_esteira_id"]
        or antes["motivo_pendencia_id"] != depois["motivo_pendencia_id"]
        or antes.get("status_agendamento_id") != depois.get("status_agendamento_id")
        or antes["data_agendamento"] != depois["data_agendamento"]
        or antes["periodo_agendamento"] != (depois["periodo_agendamento"] or "")
        or antes["data_instalacao"] != depois["data_instalacao"]
    )


def _venda_sync_pap_alterou_para_whatsapp(antes, depois) -> bool:
    """
    Só notifica o vendedor quando muda o que importa na esteira comercial:
    status, pendência, data/turno ou instalação.
    Mudança só de status_agendamento (Atribuído/Em Execução…) não gera WhatsApp.
    """
    return (
        antes["status_esteira_id"] != depois["status_esteira_id"]
        or antes["motivo_pendencia_id"] != depois["motivo_pendencia_id"]
        or antes["data_agendamento"] != depois["data_agendamento"]
        or antes["periodo_agendamento"] != (depois["periodo_agendamento"] or "")
        or antes["data_instalacao"] != depois["data_instalacao"]
    )


def _texto_status_agendamento_pap_e_conclusao(texto: str) -> bool:
    """Textos de conclusão/sucesso no detalhe ou lista PAP → Concluído com sucesso."""
    sa = _normalizar_texto_status_pap(texto)
    return bool(sa) and (
        "conclui" in sa or "concluido" in sa or "sucesso" in sa
    )


def obter_status_agendamento_concluido():
    """Garante o catálogo 'Concluído com sucesso' (criado na migration 0177)."""
    from crm_app.models import StatusAgendamento

    st, _ = StatusAgendamento.objects.get_or_create(
        nome="Concluído com sucesso",
        defaults={"ordem": 50, "cor": "#198754", "ativo": True},
    )
    return st


def resolver_status_agendamento_por_texto_pap(texto_pap: str):
    """
    Mapeia o texto do detalhe PAP para StatusAgendamento do CRM.

    Retorna (status|None, texto_nao_mapeado|None).
    - Match / conclusão → (StatusAgendamento, None)
    - Texto vazio → (None, None)
    - Texto sem match no catálogo → (None, texto_original) — dispara alerta
    """
    from crm_app.models import StatusAgendamento

    raw = (texto_pap or "").strip()
    if not raw:
        return None, None
    if _texto_status_agendamento_pap_e_conclusao(raw):
        return obter_status_agendamento_concluido(), None

    alvo = _normalizar_texto_status_pap(raw)
    for st in StatusAgendamento.objects.filter(ativo=True).only("id", "nome"):
        if _normalizar_texto_status_pap(st.nome) == alvo:
            return st, None
    # Match parcial (PAP às vezes acrescenta sufixo)
    for st in StatusAgendamento.objects.filter(ativo=True).only("id", "nome"):
        nome_n = _normalizar_texto_status_pap(st.nome)
        if nome_n and (nome_n in alvo or alvo in nome_n):
            return st, None
    return None, raw


def alertar_status_agendamento_pap_nao_mapeado(
    *,
    texto_pap: str,
    venda_id: int | None = None,
    os_num: str = "",
) -> bool:
    """Avisa o número operacional para cadastrar status do agendamento faltante no CRM."""
    import re

    from django.conf import settings

    from crm_app.whatsapp_service import WhatsAppService

    tel = re.sub(
        r"\D",
        "",
        str(getattr(settings, "CONSULTA_ESTEIRA_TELEFONE_ALERTA_STATUS", "21979630377") or ""),
    )
    if len(tel) < 10:
        return False
    os_txt = (os_num or "").strip() or "?"
    venda_txt = f"#{venda_id}" if venda_id else "?"
    msg = (
        "⚠️ *Status de agendamento não mapeado no CRM Record*\n\n"
        f"*Texto no PAP:* {texto_pap}\n"
        f"*Venda:* {venda_txt}\n"
        f"*O.S.:* {os_txt}\n\n"
        "Inclua este status em Governança → Status do Agendamento "
        "para que a consulta PAP atualize o CRM."
    )
    try:
        ok, _ = WhatsAppService().enviar_mensagem_texto(tel, msg, variar=False)
        return bool(ok)
    except Exception:
        return False


def aplicar_status_agendamento_pap_na_venda(venda, texto_pap: str) -> dict:
    """
    Atualiza status_agendamento da venda a partir do texto PAP.
    Não salva a venda — o caller faz save.
    Retorna dict: alterou, nao_mapeado, texto.
    """
    st, nao_mapeado = resolver_status_agendamento_por_texto_pap(texto_pap)
    out = {"alterou": False, "nao_mapeado": nao_mapeado, "texto": (texto_pap or "").strip()}
    if st and venda.status_agendamento_id != st.id:
        venda.status_agendamento = st
        out["alterou"] = True
    return out


def registrar_auditoria_consulta_status_pap(
    venda,
    *,
    matricula: str,
    erro: str = "",
) -> None:
    """Grava matrícula, horário e eventual erro da consulta (coluna Status Atual)."""
    from django.utils import timezone

    venda.pap_status_consultado_em = timezone.now()
    venda.pap_status_consultado_matricula = (matricula or "").strip()[:50]
    venda.pap_status_consulta_erro = (erro or "").strip()[:255]
    venda.save(
        update_fields=[
            "pap_status_consultado_em",
            "pap_status_consultado_matricula",
            "pap_status_consulta_erro",
        ]
    )



def montar_mensagem_whatsapp_esteira_vendedor(venda, *, prefixo_atualizacao=False):
    """Mensagem ao vendedor quando a esteira muda (mesmo padrão da API de vendas)."""
    from datetime import date

    if not venda or not venda.status_esteira:
        return ""
    novo_status_nome = (venda.status_esteira.nome or "").upper()
    if not (
        ("PENDEN" in novo_status_nome or "AGENDADO" in novo_status_nome or "INSTALADA" in novo_status_nome)
        and "CANCEL" not in novo_status_nome
    ):
        return ""

    prefixo = "🔄 *ATUALIZAÇÃO - " if prefixo_atualizacao else ""
    cliente_nome = venda.cliente.nome_razao_social if venda.cliente else "Cliente"
    os_num = venda.ordem_servico or "Não informada"
    status_label = venda.status_esteira.nome
    obs = venda.observacoes or "Sem observações"

    if "PENDEN" in novo_status_nome:
        motivo = venda.motivo_pendencia.nome if venda.motivo_pendencia else "Não informado"
        titulo = f"{prefixo}VENDA PENDENCIADA*" if prefixo else "⚠️ *VENDA PENDENCIADA*"
        return (
            f"{titulo}\n\n"
            f"*Nome do cliente:* {cliente_nome}\n"
            f"*O.S:* {os_num}\n"
            f"*Status:* {status_label}\n"
            f"*Motivo pendência:* {motivo}\n"
            f"*Observação:* {obs}"
        )
    if "AGENDADO" in novo_status_nome:
        data_ag = venda.data_agendamento.strftime("%d/%m/%Y") if venda.data_agendamento else "Não informada"
        turno = venda.get_periodo_agendamento_display() if venda.periodo_agendamento else "Não informado"
        titulo = f"{prefixo}VENDA AGENDADA*" if prefixo else "📅 *VENDA AGENDADA*"
        return (
            f"{titulo}\n\n"
            f"*Nome do cliente:* {cliente_nome}\n"
            f"*O.S:* {os_num}\n"
            f"*Status:* {status_label}\n"
            f"*Data e turno agendado:* {data_ag} - {turno}\n"
            f"*Observação:* {obs}\n\n"
            "Lembrete: Peça ao seu cliente que salve o número 21 4040-1810, o técnico toda vez que coloca uma "
            "pendência o CO Digital faz uma ligação automática ao cliente para confirmar. Salvando o número ele "
            "atende e evita pendências indevidas!"
        )
    if "INSTALADA" in novo_status_nome:
        data_inst = (
            venda.data_instalacao.strftime("%d/%m/%Y")
            if venda.data_instalacao
            else date.today().strftime("%d/%m/%Y")
        )
        titulo = f"{prefixo}VENDA INSTALADA*" if prefixo else "✅ *VENDA INSTALADA*"
        return (
            f"{titulo}\n\n"
            f"*Nome do cliente:* {cliente_nome}\n"
            f"*O.S:* {os_num}\n"
            f"*Status:* {status_label}\n"
            f"*Data instalada:* {data_inst}\n"
            f"*Observação:* {obs}"
        )
    return ""


def sincronizar_venda_crm_apos_status_pap(cpf_limpo, detalhes_pap, os_filtro=None):
    """
    Sincroniza CRM a partir do detalhe PAP (por O.S. cadastrada, venda ativa):
    - Concluído → INSTALADA (de AGENDADO ou PENDENCIADA; mantém data/turno agendado; + data_instalacao do PAP)
    - Status lista = Pendência Cliente ou Técnica + código no detalhe (cadastrado) → PENDENCIADA
      (limpa data_agendamento e periodo_agendamento)
    - Status lista = Em Aprovisionamento + Agendamento com data/turno no detalhe → AGENDADO
      (inclusive se CRM estava PENDENCIADA; limpa motivo_pendencia)
    - Status do agendamento (detalhe PAP) → FK StatusAgendamento quando mapeado;
      se não mapeado, mantém o atual e dispara alerta WhatsApp operacional
    Se o código de pendência não existir no CRM, não altera motivo/esteira.

    Retorna lista de dicts: venda_id, alterou, status_anterior, status_novo, os,
    status_agendamento_nao_mapeado (opcional).
    """
    import logging
    import re

    from crm_app.models import StatusCRM

    logger = logging.getLogger(__name__)
    alteracoes = []
    cpf_digits = limpar_texto(cpf_limpo)
    if len(cpf_digits) not in (11, 14):
        return alteracoes
    status_inst = StatusCRM.objects.filter(tipo="Esteira", nome__iexact="INSTALADA").first()
    status_agendado = StatusCRM.objects.filter(tipo="Esteira", nome__iexact="AGENDADO").first()
    status_pendenciada = StatusCRM.objects.filter(tipo="Esteira", nome__iexact="PENDENCIADA").first()

    os_filtro_digits = re.sub(r"\D", "", str(os_filtro or "")).strip() if os_filtro else ""

    for d in detalhes_pap or []:
        if not d or d.get("nao_pertence_pdv"):
            continue
        os_raw = (d.get("numero_os") or "").strip()
        if not os_raw:
            continue
        if os_filtro_digits:
            os_d = re.sub(r"\D", "", os_raw).strip()
            os_sem = os_d.lstrip("0") or os_d
            filtro_sem = os_filtro_digits.lstrip("0") or os_filtro_digits
            if os_d not in (os_filtro_digits, filtro_sem) and os_sem not in (os_filtro_digits, filtro_sem):
                continue
        venda = buscar_venda_ativa_por_os_cpf(cpf_digits, os_raw)
        if not venda:
            logger.info(
                "[STATUS SYNC] OS %s: venda ativa não encontrada no CRM (CPF).",
                os_raw,
            )
            continue
        esteira_nome = (venda.status_esteira.nome if venda.status_esteira else "") or ""
        if not _esteira_permite_sync_status_pap(venda):
            logger.info(
                "[STATUS SYNC] OS %s: esteira '%s' fora de AGENDADO/PENDENCIADA — não atualiza.",
                os_raw,
                esteira_nome,
            )
            continue

        antes = _snapshot_venda_sync_pap(venda)
        status_anterior = antes["status_esteira_nome"]
        sa_info = aplicar_status_agendamento_pap_na_venda(venda, d.get("status_agendamento"))
        sa_nao_mapeado = sa_info.get("nao_mapeado")
        salvou = False

        def _registrar_alteracao_se_houve():
            nonlocal salvou
            salvou = True
            depois = _snapshot_venda_sync_pap(venda)
            if not _venda_sync_pap_alterou(antes, depois):
                return
            item = {
                "venda_id": venda.id,
                "alterou": True,
                "notificar_whatsapp": _venda_sync_pap_alterou_para_whatsapp(antes, depois),
                "status_anterior": status_anterior,
                "status_novo": depois["status_esteira_nome"],
                "os": os_raw,
            }
            if sa_nao_mapeado:
                item["status_agendamento_nao_mapeado"] = sa_nao_mapeado
            alteracoes.append(item)

        if status_inst and pap_status_indica_concluido(d.get("status"), d.get("status_agendamento")):
            st_u = esteira_nome.upper()
            if "AGENDADO" in st_u or "PENDENCI" in st_u:
                dt = extrair_data_instalacao_texto_pap(d.get("agendamento"), d.get("status_agendamento"))
                venda.status_esteira = status_inst
                venda.motivo_pendencia = None
                # Instalada no PAP ⇒ status do agendamento = Concluído com sucesso
                st_concluido = obter_status_agendamento_concluido()
                if venda.status_agendamento_id != st_concluido.id:
                    venda.status_agendamento = st_concluido
                sa_nao_mapeado = None
                if dt:
                    venda.data_instalacao = dt
                venda.save()
                logger.info(
                    "[STATUS SYNC] OS %s: marcada INSTALADA (PAP concluído, era %s).",
                    os_raw,
                    esteira_nome,
                )
                _registrar_alteracao_se_houve()
            else:
                logger.info(
                    "[STATUS SYNC] OS %s: PAP concluído, mas esteira '%s' não é AGENDADO/PENDENCIADA — não altera.",
                    os_raw,
                    esteira_nome,
                )
            if sa_nao_mapeado:
                alertar_status_agendamento_pap_nao_mapeado(
                    texto_pap=sa_nao_mapeado, venda_id=venda.id, os_num=os_raw
                )
            elif not salvou and sa_info.get("alterou"):
                venda.save()
                _registrar_alteracao_se_houve()
            continue

        pendencia_txt = (d.get("pendencia") or "").strip()
        motivo = resolver_motivo_pendencia_por_texto_pap(pendencia_txt) if pendencia_txt else None
        m_cod = re.match(r"^(\d{4})", pendencia_txt) if pendencia_txt else None
        codigo = m_cod.group(1) if m_cod else None

        status_pap = (d.get("status") or "").strip()
        if motivo and status_pendenciada and pap_status_indica_pendencia_lista(status_pap):
            venda.motivo_pendencia = motivo
            venda.status_esteira = status_pendenciada
            venda.data_agendamento = None
            venda.periodo_agendamento = None
            venda.save()
            logger.info(
                "[STATUS SYNC] OS %s: PENDENCIADA — motivo %s (Status PAP: %s).",
                os_raw,
                motivo.nome,
                status_pap[:60],
            )
            _registrar_alteracao_se_houve()
            if sa_nao_mapeado:
                alertar_status_agendamento_pap_nao_mapeado(
                    texto_pap=sa_nao_mapeado, venda_id=venda.id, os_num=os_raw
                )
            continue

        if motivo and status_pendenciada and not pap_status_indica_pendencia_lista(status_pap):
            logger.info(
                "[STATUS SYNC] OS %s: pendência %s no detalhe, mas Status PAP '%s' "
                "(norm: %s) não é Pendência Cliente/Técnica — não altera esteira.",
                os_raw,
                pendencia_txt[:50],
                status_pap[:60],
                _normalizar_texto_status_pap(status_pap)[:60],
            )

        if pendencia_txt and not motivo:
            logger.info(
                "[STATUS SYNC] OS %s: pendência PAP '%s' (código %s) sem MotivoPendencia no CRM — não altera.",
                os_raw,
                pendencia_txt[:80],
                codigo or "?",
            )
            if sa_info.get("alterou"):
                venda.save()
                _registrar_alteracao_se_houve()
            if sa_nao_mapeado:
                alertar_status_agendamento_pap_nao_mapeado(
                    texto_pap=sa_nao_mapeado, venda_id=venda.id, os_num=os_raw
                )
            continue

        if not pendencia_txt:
            logger.info(
                "[STATUS SYNC] OS %s: sem texto de pendência no detalhe PAP.",
                os_raw,
            )

        agendamento_txt = (d.get("agendamento") or "").strip()
        if (
            status_agendado
            and pap_status_indica_em_aprovisionamento(status_pap)
            and pap_detalhe_tem_agendamento_com_data(agendamento_txt)
        ):
            dt_ag = extrair_data_instalacao_texto_pap(agendamento_txt)
            periodo = extrair_periodo_agendamento_texto_pap(agendamento_txt) or (
                extrair_periodo_agendamento_texto_pap(d.get("status_agendamento"))
            )
            venda.status_esteira = status_agendado
            venda.motivo_pendencia = None
            if dt_ag:
                venda.data_agendamento = dt_ag
            if periodo:
                venda.periodo_agendamento = periodo
            elif not venda.periodo_agendamento:
                logger.warning(
                    "[STATUS SYNC] OS %s: AGENDADO sem turno reconhecido no texto PAP (%s).",
                    os_raw,
                    agendamento_txt[:80],
                )
            venda.save()
            depois_ag = _snapshot_venda_sync_pap(venda)
            if _venda_sync_pap_alterou(antes, depois_ag):
                logger.info(
                    "[STATUS SYNC] OS %s: AGENDADO via PAP (Status: %s, %s → turno=%s).",
                    os_raw,
                    status_pap[:40],
                    agendamento_txt[:60],
                    periodo or venda.periodo_agendamento or "?",
                )
            else:
                logger.info(
                    "[STATUS SYNC] OS %s: consultado PAP (AGENDADO, sem alteração CRM).",
                    os_raw,
                )
            _registrar_alteracao_se_houve()
        elif pap_detalhe_tem_agendamento_com_data(agendamento_txt) and not pap_status_indica_em_aprovisionamento(
            status_pap
        ):
            logger.info(
                "[STATUS SYNC] OS %s: agendamento no detalhe (%s), mas Status PAP '%s' "
                "não é Em Aprovisionamento — não altera para AGENDADO.",
                os_raw,
                agendamento_txt[:50],
                status_pap[:60],
            )

        if not salvou and sa_info.get("alterou"):
            venda.save()
            _registrar_alteracao_se_houve()
        if sa_nao_mapeado:
            alertar_status_agendamento_pap_nao_mapeado(
                texto_pap=sa_nao_mapeado, venda_id=venda.id, os_num=os_raw
            )
            if not any(a.get("venda_id") == venda.id for a in alteracoes):
                alteracoes.append(
                    {
                        "venda_id": venda.id,
                        "alterou": False,
                        "status_anterior": status_anterior,
                        "status_novo": status_anterior,
                        "os": os_raw,
                        "status_agendamento_nao_mapeado": sa_nao_mapeado,
                    }
                )

    return alteracoes


def consultar_status_venda_com_decisao(tipo_busca, valor):
    """
    Igual a consultar_status_venda, mas retorna também se deve fazer consulta online no PAP
    e o CPF a usar. Usado pelo fluxo Status no WhatsApp para decidir se dispara Consulta OS.
    Retorna: (resultado_texto, fazer_consulta_online, cpf_para_consulta)
    - fazer_consulta_online: True sempre que houver CPF/CNPJ válido (11 ou 14 dígitos) para a Consulta OS.
    - cpf_para_consulta: CPF/CNPJ (só dígitos) para a Consulta OS, ou None.
    """
    valor_limpo = limpar_texto(valor)
    venda = None
    cpf_para_consulta = None

    if tipo_busca == 'CPF':
        venda = Venda.objects.filter(
            cliente__cpf_cnpj__icontains=valor_limpo,
            ativo=True
        ).order_by('-data_criacao').select_related('cliente', 'status_esteira', 'status_tratamento', 'plano').first()
        cpf_para_consulta = valor_limpo if len(valor_limpo) in (11, 14) else None
    elif tipo_busca == 'OS':
        venda = Venda.objects.filter(
            ordem_servico=valor_limpo,
            ativo=True
        ).select_related('cliente', 'status_esteira', 'status_tratamento', 'plano').first()
        if venda and venda.cliente and venda.cliente.cpf_cnpj:
            cpf_para_consulta = limpar_texto(venda.cliente.cpf_cnpj)
            if len(cpf_para_consulta) not in (11, 14):
                cpf_para_consulta = None

    texto = consultar_status_venda(tipo_busca, valor)
    # Consulta online no PAP sempre que houver CPF/CNPJ válido (com ou sem venda no CRM)
    return (texto, bool(cpf_para_consulta), cpf_para_consulta)


def consultar_previsao_agendamento(numero_pedido):
    """
    Busca a previsão de instalação na base de agendamentos futuros e tarefas fechadas.
    Retorna a data/hora de início e fim da execução real.
    """
    from .models import ImportacaoAgendamento
    from django.db.models import Q
    
    numero_limpo = str(numero_pedido).strip()
    numero_sem_zero = numero_limpo.lstrip("0") or numero_limpo
    print(f"\n📅 BUSCA PREVISÃO -> Pedido: {numero_limpo} | sem zero: {numero_sem_zero}")
    
    # Busca combinando ordem e ordem de venda, considerando zeros à esquerda
    filtros = Q(nr_ordem__icontains=numero_limpo) | Q(nr_ordem_venda__icontains=numero_limpo)
    if numero_sem_zero != numero_limpo:
        filtros |= Q(nr_ordem__icontains=numero_sem_zero) | Q(nr_ordem_venda__icontains=numero_sem_zero)
        filtros |= Q(nr_ordem__iexact=numero_sem_zero) | Q(nr_ordem_venda__iexact=numero_sem_zero)
    filtros |= Q(nr_ordem__iexact=numero_limpo) | Q(nr_ordem_venda__iexact=numero_limpo)

    agendamento = ImportacaoAgendamento.objects.filter(filtros).first()
    
    if agendamento:
        # Formata as datas
        dt_inicio = agendamento.dt_inicio_execucao_real
        dt_fim = agendamento.dt_fim_execucao_real
        
        # Informações do agendamento
        municipio = agendamento.nm_municipio or "Não informado"
        uf = agendamento.sg_uf or ""
        status_ba = agendamento.st_ba or "Em andamento"
        atividade = agendamento.ds_atividade or "Instalação"
        
        # Monta a mensagem
        if dt_inicio and dt_fim:
            # Formata as datas
            inicio_fmt = dt_inicio.strftime('%d/%m/%Y às %H:%M')
            fim_fmt = dt_fim.strftime('%d/%m/%Y às %H:%M')
            
            return (
                f"📅 *PREVISÃO DE INSTALAÇÃO*\n\n"
                f"🔢 *Pedido:* {numero_limpo}\n"
                f"📍 *Local:* {municipio}/{uf}\n"
                f"🔧 *Atividade:* {atividade}\n"
                f"📊 *Status:* {status_ba}\n\n"
                f"⏰ *Previsão de Início:*\n{inicio_fmt}\n\n"
                f"⏰ *Previsão de Término:*\n{fim_fmt}"
            )
        elif agendamento.dt_agendamento:
            # Só tem data de agendamento
            agend_fmt = agendamento.dt_agendamento.strftime('%d/%m/%Y')
            return (
                f"📅 *PREVISÃO DE INSTALAÇÃO*\n\n"
                f"🔢 *Pedido:* {numero_limpo}\n"
                f"📍 *Local:* {municipio}/{uf}\n"
                f"🔧 *Atividade:* {atividade}\n"
                f"📊 *Status:* {status_ba}\n\n"
                f"⏰ *Data Agendada:* {agend_fmt}\n"
                f"⚠️ *Horário de execução ainda não disponível*"
            )
        else:
            return (
                f"📅 *PREVISÃO DE INSTALAÇÃO*\n\n"
                f"🔢 *Pedido:* {numero_limpo}\n"
                f"📍 *Local:* {municipio}/{uf}\n"
                f"📊 *Status:* {status_ba}\n\n"
                f"⚠️ *Datas de execução ainda não disponíveis*\n"
                f"O agendamento está registrado mas ainda sem previsão de horário."
            )
    else:
        return (
            f"❌ *PEDIDO NÃO ENCONTRADO*\n\n"
            f"Não localizei o pedido *{numero_limpo}* na base de agendamentos.\n\n"
            f"Verifique:\n"
            f"• Se o número está correto\n"
            f"• Se o pedido já foi agendado\n"
            f"• Se foi importado na última base"
        )


def consultar_andamento_agendamentos(telefone_vendedor=None):
    """
    Busca agendamentos do dia atual com horários de execução real definidos.
    Se telefone_vendedor for fornecido, filtra apenas agendamentos do vendedor.
    Para Diretoria, Admin e BackOffice, mostra todos os agendamentos.
    Retorna mensagem formatada com os clientes e intervalos de horário.
    """
    from .models import ImportacaoAgendamento, Venda
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from django.db.models import Q
    
    # Importar is_member (definida em outro arquivo, geralmente em views.py ou utils.py)
    try:
        from crm_app.views import is_member
    except ImportError:
        # Fallback: função simples para verificar grupos
        def is_member(user, grupos):
            if not user or not user.groups.exists():
                return False
            grupos_user = [g.name for g in user.groups.all()]
            return any(grupo in grupos_user for grupo in grupos)
    
    User = get_user_model()
    hoje = timezone.now().date()
    
    # Se telefone fornecido, buscar vendedor
    vendedor = None
    mostrar_todos = False
    if telefone_vendedor:
        # Limpar telefone (remover caracteres não numéricos)
        telefone_limpo = "".join(filter(str.isdigit, str(telefone_vendedor)))
        # Tentar buscar com e sem código 55
        if telefone_limpo.startswith('55'):
            telefone_limpo_sem_55 = telefone_limpo[2:]
        else:
            telefone_limpo_sem_55 = telefone_limpo
        
        vendedor = User.objects.filter(
            Q(tel_whatsapp__icontains=telefone_limpo) |
            Q(tel_whatsapp__icontains=telefone_limpo_sem_55) |
            Q(tel_whatsapp_2__icontains=telefone_limpo) |
            Q(tel_whatsapp_2__icontains=telefone_limpo_sem_55) |
            Q(tel_whatsapp_3__icontains=telefone_limpo) |
            Q(tel_whatsapp_3__icontains=telefone_limpo_sem_55)
        ).first()
        
        if not vendedor:
            return (
                "📅 *AGENDAMENTOS DO DIA*\n\n"
                f"❌ Vendedor não encontrado para o número {telefone_vendedor}.\n"
                "Verifique se o número está cadastrado no sistema."
            )
        
        # Verificar se é Diretoria, Admin ou BackOffice
        grupos_gestao = ['Diretoria', 'Admin', 'BackOffice']
        mostrar_todos = is_member(vendedor, grupos_gestao)
    
    # Buscar agendamentos do dia com horários de execução real preenchidos
    agendamentos_qs = ImportacaoAgendamento.objects.filter(
        dt_agendamento=hoje,
        dt_inicio_execucao_real__isnull=False,
        dt_fim_execucao_real__isnull=False
    )
    
    # Se vendedor especificado e NÃO for gestão, filtrar apenas suas vendas
    if vendedor and not mostrar_todos:
        # Buscar ordens_servico das vendas desse vendedor
        vendas_vendedor = Venda.objects.filter(
            vendedor=vendedor,
            ativo=True,
            ordem_servico__isnull=False
        ).exclude(ordem_servico='').values_list('ordem_servico', flat=True)
        
        ordens_list = list(vendas_vendedor)
        
        if not ordens_list:
            return (
                "📅 *AGENDAMENTOS DO DIA*\n\n"
                f"❌ Não há agendamentos para hoje ({hoje.strftime('%d/%m/%Y')}) "
                f"relacionados às suas vendas."
            )
        
        # Filtrar agendamentos cujo nr_ordem_venda está nas ordens do vendedor
        agendamentos_qs = agendamentos_qs.filter(
            Q(nr_ordem_venda__in=ordens_list) | Q(nr_ordem__in=ordens_list)
        )
    
    agendamentos = agendamentos_qs.order_by('dt_inicio_execucao_real')
    
    if not agendamentos.exists():
        msg_base = f"📅 *AGENDAMENTOS DO DIA*\n\n"
        if vendedor:
            msg_base += f"Vendedor: {vendedor.username}\n\n"
        msg_base += f"❌ Não há agendamentos para hoje ({hoje.strftime('%d/%m/%Y')}) com horários de execução definidos."
        return msg_base
    
    mensagens = []
    mensagens.append(f"📅 *AGENDAMENTOS DO DIA*\n\nData: {hoje.strftime('%d/%m/%Y')}\n")
    if vendedor:
        mensagens.append(f"Vendedor: *{vendedor.username}*\n")
    mensagens.append(f"Total: {agendamentos.count()} agendamento(s)\n")
    mensagens.append("=" * 30 + "\n")
    
    for idx, agend in enumerate(agendamentos, 1):
        # Tentar encontrar a venda relacionada
        cliente_nome = "Cliente não identificado"
        os_num = agend.nr_ordem_venda or agend.nr_ordem or "N/A"
        
        if agend.nr_ordem_venda:
            # Buscar venda por ordem_servico
            venda = Venda.objects.filter(
                ordem_servico=agend.nr_ordem_venda,
                ativo=True
            ).select_related('cliente').first()
            
            if venda and venda.cliente:
                cliente_nome = venda.cliente.nome_razao_social or cliente_nome
        
        # Formatar horários
        inicio_fmt = agend.dt_inicio_execucao_real.strftime('%H:%M')
        fim_fmt = agend.dt_fim_execucao_real.strftime('%H:%M')
        intervalo = f"{inicio_fmt} - {fim_fmt}"
        
        # Informações adicionais
        municipio = agend.nm_municipio or ""
        atividade = agend.ds_atividade or "Instalação"
        
        mensagens.append(f"{idx}. *{cliente_nome}*\n")
        mensagens.append(f"   🔢 O.S: {os_num}\n")
        mensagens.append(f"   ⏰ Horário: {intervalo}\n")
        if municipio:
            mensagens.append(f"   📍 Local: {municipio}\n")
        if atividade:
            mensagens.append(f"   🔧 Atividade: {atividade}\n")
        mensagens.append("\n")
    
    return "".join(mensagens).strip()


def buscar_venda_os_ja_cadastrada(ordem_servico, excluir_venda_id=None):
    """
    Retorna outra venda com a mesma O.S. já em status de tratamento CADASTRADA.
    excluir_venda_id: venda atual (auditoria em andamento) — não conta como duplicata.
    """
    from .models import Venda

    os_val = (ordem_servico or '').strip()
    if not os_val:
        return None
    qs = Venda.objects.filter(
        ordem_servico__iexact=os_val,
        status_tratamento__nome__iexact='CADASTRADA',
    ).select_related('cliente', 'vendedor', 'status_tratamento')
    if excluir_venda_id:
        qs = qs.exclude(pk=excluir_venda_id)
    return qs.first()


def mensagem_os_ja_cadastrada(ordem_servico, venda_existente):
    """Texto padrão para bloqueio de O.S. duplicada."""
    os_val = (ordem_servico or '').strip()
    vid = getattr(venda_existente, 'id', None)
    cliente = ''
    if venda_existente and getattr(venda_existente, 'cliente', None):
        cliente = venda_existente.cliente.nome_razao_social or ''
    base = f'O pedido (O.S. {os_val}) já foi cadastrado no sistema'
    if vid:
        base += f' (venda #{vid}'
        if cliente:
            base += f' — {cliente}'
        base += ')'
    base += '.'
    return base