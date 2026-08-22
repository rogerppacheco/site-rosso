import logging
import base64
import io
from datetime import datetime

from crm_app.services.whatsapp.factory import (
    PURPOSE_CLIENTE,
    PURPOSE_INTERNO,
    get_whatsapp_provider,
)
from crm_app.services.whatsapp.phone_utils import destino_zapi, formatar_telefone_br

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Facade: variacao de texto, geracao de imagens e delegacao ao provider."""

    def __init__(self, purpose: str = PURPOSE_INTERNO) -> None:
        """
        purpose=interno → Número A (bot/equipe).
        purpose=cliente → Número B (oficial / cliente final).
        """
        self.purpose = (
            PURPOSE_CLIENTE
            if (purpose or "").strip().lower() == PURPOSE_CLIENTE
            else PURPOSE_INTERNO
        )
        self._provider = get_whatsapp_provider(purpose=self.purpose)

    @classmethod
    def para_cliente(cls) -> "WhatsAppService":
        """Atalho para envios a cliente final (Número B)."""
        return cls(purpose=PURPOSE_CLIENTE)

    @property
    def instance_id(self) -> str:
        return getattr(self._provider, "instance_id", "") or ""

    @property
    def token(self) -> str:
        return getattr(self._provider, "token", "") or ""

    def _formatar_telefone(self, telefone):
        return formatar_telefone_br(telefone)

    def _destino_send_text(self, telefone_ou_grupo):
        return destino_zapi(telefone_ou_grupo)

    def verificar_numero_existe(self, telefone):
        return self._provider.verificar_numero_existe(telefone)

    def enviar_mensagem_texto(self, telefone, mensagem, variar=True):
        try:
            if variar and mensagem and len(mensagem) > 20:
                from crm_app.whatsapp_variacao import aplicar_variacao, aplicar_variacao_lote
                if len(mensagem) > 400:
                    mensagem = aplicar_variacao_lote(mensagem, chance_substituir=0.5)
                else:
                    mensagem = aplicar_variacao(mensagem, chance_substituir=0.5)
        except Exception as e:
            logger.debug("[WhatsAppService] Variacao nao aplicada: %s", e)
        ok, resp = self._provider.enviar_mensagem_texto_raw(telefone, mensagem)
        self._registrar_custo_oficial(
            telefone=telefone,
            tipo_envio="TEXTO",
            sucesso=bool(ok),
            resposta=resp,
        )
        return ok, resp

    def enviar_mensagem_com_botoes_reply(
        self, telefone, mensagem, button_actions, title=None, footer=None
    ):
        ok, resp = self._provider.enviar_mensagem_com_botoes_reply(
            telefone, mensagem, button_actions, title=title, footer=footer
        )
        self._registrar_custo_oficial(
            telefone=telefone,
            tipo_envio="BOTOES",
            sucesso=bool(ok),
            resposta=resp,
        )
        return ok, resp

    def enviar_lista_opcoes(
        self,
        telefone,
        mensagem,
        opcoes,
        titulo_lista="Opções",
        botao_label="Ver opções",
    ):
        fn = getattr(self._provider, "enviar_lista_opcoes", None)
        if not callable(fn):
            return False, None
        ok, resp = fn(
            telefone,
            mensagem,
            opcoes,
            titulo_lista=titulo_lista,
            botao_label=botao_label,
        )
        self._registrar_custo_oficial(
            telefone=telefone,
            tipo_envio="BOTOES",
            sucesso=bool(ok),
            resposta=resp,
        )
        return ok, resp

    def enviar_resumo_pap_com_botao_confirmar(self, telefone, resumo, texto_extra=""):
        message = f"{resumo}{texto_extra}".strip()
        return self.enviar_mensagem_com_botoes_reply(
            telefone,
            message,
            [{"id": "pap_confirmar_sim", "type": "REPLY", "label": "SIM"}],
        )

    def enviar_template(
        self,
        telefone,
        template_name,
        language_code="pt_BR",
        body_params=None,
        template_params=None,
    ):
        """
        Envia template Meta aprovado (Cloud API / WhatsAtende Número B).
        Preferir WhatsAppService.para_cliente() + body_params (lista {{1}}…).
        """
        fn = getattr(self._provider, "enviar_template", None)
        if not callable(fn):
            logger.error(
                "[WhatsAppService] Provider %s não suporta enviar_template",
                type(self._provider).__name__,
            )
            return False, "Provider sem suporte a templates Meta"
        ok, resp = fn(
            telefone,
            template_name,
            language_code=language_code,
            body_params=body_params,
            template_params=template_params,
        )
        self._registrar_custo_oficial(
            telefone=telefone,
            tipo_envio="TEMPLATE",
            sucesso=bool(ok),
            resposta=resp,
            template_name=template_name or "",
        )
        return ok, resp

    def _registrar_custo_oficial(
        self,
        *,
        telefone,
        tipo_envio: str,
        sucesso: bool,
        resposta=None,
        template_name: str = "",
    ) -> None:
        if self.purpose != PURPOSE_CLIENTE:
            return
        try:
            from crm_app.services.whatsapp.custo_oficial import registrar_envio_oficial

            registrar_envio_oficial(
                telefone=str(telefone or ""),
                tipo_envio=tipo_envio,
                sucesso=sucesso,
                resposta=resposta,
                template_name=template_name,
                origem=f"purpose={self.purpose}",
                erro="" if sucesso else str(resposta)[:500],
            )
        except Exception as exc:
            logger.debug("[WhatsAppService] Custo não registrado: %s", exc)

    def listar_templates(self):
        fn = getattr(self._provider, "listar_templates", None)
        if not callable(fn):
            return []
        return fn()

    def enviar_imagem_b64(self, telefone, img_b64, caption=""):
        return self._provider.enviar_imagem_b64(telefone, img_b64, caption=caption)

    def enviar_imagem_base64_direto(self, telefone, img_b64, caption=""):
        return self.enviar_imagem_b64(telefone, img_b64, caption)

    def enviar_pdf_url(self, telefone, pdf_url, nome_arquivo="extrato.pdf", caption=None):
        return self._provider.enviar_pdf_url(telefone, pdf_url, nome_arquivo, caption=caption)

    def enviar_pdf_b64(self, telefone, base64_data, nome_arquivo="extrato.pdf", caption=None):
        return self._provider.enviar_pdf_b64(telefone, base64_data, nome_arquivo, caption=caption)

    def listar_grupos(self):
        return self._provider.listar_grupos()

    def _gerar_imagem_resumo_bytes(self, dados):
        if not Image: return None
        return None

    def _fmt_br(self, val):
        try:
            n = float(val)
            return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return "R$ 0,00"

    def gerar_folha_comissao_card_b64(self, dados_vendedor, periodo):
        """
        Gera imagem do card da folha de comissão (igual ao que aparece no site) para envio via WhatsApp.
        dados_vendedor: dict com vendedor_nome, resumo (por_plano, faixa_aplicada, comissao_total_geral, total_descontos, total_bonus, liquido, detalhes_descontos, qtd_a_descontar).
        Retorna base64 da imagem (string, sem prefixo data:...) ou None se falhar.
        """
        if not Image or not ImageDraw or not ImageFont:
            return None
        try:
            W, H = 800, 1200
            cor_fundo = (255, 255, 255)
            cor_cabecalho = (13, 110, 253)
            cor_texto = (33, 37, 41)
            cor_texto_sec = (108, 117, 125)
            cor_verde = (25, 135, 84)
            cor_vermelho = (220, 53, 69)
            cor_borda = (222, 226, 230)
            font_paths = [
                "arial.ttf", "Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
            font_bold_paths = [
                "arialbd.ttf", "Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
            f_path = None
            for p in font_paths:
                try:
                    ImageFont.truetype(p, 14)
                    f_path = p
                    break
                except Exception:
                    continue
            fb_path = None
            for p in font_bold_paths:
                try:
                    ImageFont.truetype(p, 14)
                    fb_path = p
                    break
                except Exception:
                    continue
            if not f_path:
                f_path = font_bold_paths[0] if font_bold_paths else None
            font_sm = ImageFont.truetype(f_path, 12) if f_path else ImageFont.load_default()
            font_md = ImageFont.truetype(f_path, 14) if f_path else ImageFont.load_default()
            font_bold = ImageFont.truetype(fb_path, 14) if fb_path else ImageFont.load_default()
            font_title = ImageFont.truetype(fb_path, 18) if fb_path else ImageFont.load_default()

            img = Image.new('RGB', (W, H), color=cor_fundo)
            d = ImageDraw.Draw(img)
            y = 10
            r = dados_vendedor.get('resumo') or {}
            vendedor_nome = (dados_vendedor.get('vendedor_nome') or '').upper()
            faixa = r.get('faixa_aplicada') or '-'

            # Cabeçalho: faixa alinhada à direita para não cortar (anchor rm = right-middle)
            d.rectangle([(0, 0), (W, 56)], fill=cor_cabecalho)
            d.text((20, 28), vendedor_nome, fill='white', font=font_title)
            faixa_str = f"Faixa: {faixa}" if faixa else "Faixa: -"
            try:
                d.text((W - 20, 28), faixa_str, fill='white', font=font_md, anchor='rm')
            except TypeError:
                d.text((W - 20, 18), faixa_str, fill='white', font=font_md)
            y = 70

            # Tabela por plano — grade com linhas e colunas bem definidas
            por_plano = r.get('por_plano') or []
            col_w = [220, 80, 100, 110, 120]
            xs = [20]
            for cw in col_w:
                xs.append(xs[-1] + cw)
            xs.append(W - 20)
            row_h = 26
            cor_header_bg = (248, 249, 250)
            cor_total_bg = (248, 249, 250)
            linha_grossa = 2
            headers = ['PLANO', 'QTD', 'VALOR UNIT.', 'VALOR TOTAL', 'COMISSÃO']

            y_tabela_inicio = y
            # Cabeçalho da tabela (fundo cinza + bordas)
            d.rectangle([(xs[0], y), (xs[-1], y + row_h)], fill=cor_header_bg, outline=cor_borda, width=1)
            for i, h in enumerate(headers):
                px = xs[i] + 6
                d.text((px, y + 6), h, fill=cor_texto_sec, font=font_bold)
            y += row_h
            # Linha horizontal abaixo do cabeçalho (mais marcada)
            d.line([(xs[0], y), (xs[-1], y)], fill=cor_texto_sec, width=linha_grossa)
            y += 4
            # Linhas de dados + total de quantidade para a linha TOTAL
            total_qtd = 0
            for p in por_plano:
                if (
                    (p.get('qtd_instalada_a_pagar') or 0) == 0
                    and (p.get('valor_total_instalados') or 0) == 0
                    and (p.get('qtd_antecipada') or 0) == 0
                ):
                    continue
                plano = (p.get('plano') or '-')[:22]
                qtd = p.get('qtd_instalada_a_pagar') or 0
                total_qtd += int(qtd) if qtd is not None else 0
                vunit = p.get('valor_unitario_instalados')
                vtot = p.get('valor_total_instalados') or 0
                com = p.get('comissao_total') or 0
                vunit_str = self._fmt_br(vunit) if vunit is not None else '-'
                d.rectangle([(xs[0], y), (xs[-1], y + row_h)], outline=cor_borda, width=1)
                d.text((xs[0] + 6, y + 5), plano, fill=cor_texto, font=font_sm)
                d.text((xs[1] + 6, y + 5), str(qtd), fill=cor_texto, font=font_sm)
                d.text((xs[2] + 6, y + 5), vunit_str, fill=cor_texto, font=font_sm)
                d.text((xs[3] + 6, y + 5), self._fmt_br(vtot), fill=cor_texto, font=font_sm)
                d.text((xs[4] + 6, y + 5), self._fmt_br(com), fill=cor_texto, font=font_bold)
                y += row_h
            # Linha horizontal antes da linha TOTAL
            d.line([(xs[0], y), (xs[-1], y)], fill=cor_texto_sec, width=linha_grossa)
            y += 4
            # Linha TOTAL (fundo cinza + bordas): mostrar total de quantidade na coluna QTD
            d.rectangle([(xs[0], y), (xs[-1], y + row_h)], fill=cor_total_bg, outline=cor_borda, width=1)
            d.text((xs[0] + 6, y + 5), 'TOTAL', fill=cor_texto, font=font_bold)
            d.text((xs[1] + 6, y + 5), str(total_qtd), fill=cor_texto, font=font_bold)
            d.text((xs[4] + 6, y + 5), self._fmt_br(r.get('comissao_total_geral') or 0), fill=cor_texto, font=font_bold)
            y += row_h
            # Linhas verticais da tabela (do topo ao fim da tabela)
            y_tabela_fim = y
            for xi in xs[1:-1]:
                d.line([(xi, y_tabela_inicio), (xi, y_tabela_fim)], fill=cor_borda, width=1)
            # Borda esquerda e direita da tabela (reforço)
            d.line([(xs[0], y_tabela_inicio), (xs[0], y_tabela_fim)], fill=cor_borda, width=1)
            d.line([(xs[-1], y_tabela_inicio), (xs[-1], y_tabela_fim)], fill=cor_borda, width=1)
            y += 14

            info_ad = r.get('info_comissao_adiantada') or {}
            if (info_ad.get('quantidade_total') or 0) > 0:
                d.text(
                    (20, y),
                    f"Já adiantado (esteira, tabela Adiantamento): {info_ad['quantidade_total']} un. = {self._fmt_br(info_ad.get('valor_total') or 0)} (não é desconto)",
                    fill=cor_texto_sec,
                    font=font_sm,
                )
                y += 22

            # Resumo financeiro
            d.text((20, y), f"Descontos: - {self._fmt_br(r.get('total_descontos') or 0)}", fill=cor_vermelho, font=font_bold)
            d.text((280, y), f"Bônus: + {self._fmt_br(r.get('total_bonus') or 0)}", fill=cor_verde, font=font_md)
            d.text((500, y), f"LÍQUIDO A PAGAR: {self._fmt_br(r.get('liquido') or 0)}", fill=cor_verde, font=font_bold)
            y += 36

            if r.get('desconta_boleto_pap') is False:
                d.line([(20, y), (W - 20, y)], fill=cor_borda)
                y += 10
                d.text(
                    (20, y),
                    'Atenção: boleto não entra no líquido (Regras vendedor); linha de boleto = valor cheio.',
                    fill=(200, 120, 0),
                    font=font_sm,
                )
                y += 22

            # Detalhes descontos por grupo (alinhado à folha web)
            detalhes = r.get('detalhes_descontos') or []

            def _titulo_grupo(txt):
                nonlocal y
                d.text((20, y), txt, fill=cor_texto_sec, font=font_bold)
                y += 18

            def _linha_det(det):
                nonlocal y
                motivo = det.get('motivo') or 'Desconto'
                q = det.get('quantidade')
                if q is not None and q != '':
                    motivo = f"{motivo} ({int(q)} un.)"
                val = det.get('valor') or 0
                d.text((24, y), f"{motivo}: - {self._fmt_br(val)}", fill=cor_vermelho, font=font_sm)
                y += 18

            if detalhes:
                d.line([(20, y), (W - 20, y)], fill=cor_borda)
                y += 10
                d.text((20, y), 'Lançamentos descontados', fill=cor_texto_sec, font=font_bold)
                y += 22
                qadc = r.get('qtd_a_descontar')
                if qadc is not None and qadc > 0:
                    d.text((20, y), f"QTD A DESCONTAR: {qadc}", fill=cor_texto_sec, font=font_sm)
                    y += 18

                def _por_tipo(codigo, titulo):
                    nonlocal y
                    sub = [x for x in detalhes if (x.get('tipo_exibicao') or '').lower() == codigo]
                    if not sub:
                        return
                    _titulo_grupo(titulo)
                    for det in sub:
                        _linha_det(det)

                def _so_linhas(codigo):
                    nonlocal y
                    sub = [x for x in detalhes if (x.get('tipo_exibicao') or '').lower() == codigo]
                    for det in sub:
                        _linha_det(det)

                _so_linhas('folha_boleto_vendas')
                _so_linhas('folha_antecipacao_instalacao')
                _por_tipo('adiant_cnpj', 'Adiant. CNPJ')
                _por_tipo('churn_m0', 'Desconto Churn M0')
                _por_tipo('churn_m1', 'Desconto Churn M-1')
                codigos = {
                    'folha_boleto_vendas', 'folha_antecipacao_instalacao',
                    'boleto', 'antecipacao_instalacao', 'processamento_auto_misto',
                    'adiant_cnpj', 'adiant_comissao', 'churn_m0', 'churn_m1',
                }
                outros = [x for x in detalhes if (x.get('tipo_exibicao') or '').lower() not in codigos]
                if outros:
                    _titulo_grupo('Outros')
                    for det in outros:
                        _linha_det(det)
                y += 8

            # Rodapé período
            d.line([(20, y), (W - 20, y)], fill=cor_borda)
            y += 10
            d.text((W // 2, y), f"Período: {periodo}", fill=cor_texto_sec, font=font_sm)
            img = img.crop((0, 0, W, min(y + 30, H)))
            buffered = io.BytesIO()
            img.save(buffered, format='PNG')
            b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
            return b64
        except Exception as e:
            logger.exception("gerar_folha_comissao_card_b64: %s", e)
            return None

    def enviar_resumo_comissao(self, telefone, dados_comissao):
        # Fallback texto se imagem falhar ou Pillow não existir
        msg = (
            f"💰 *RESUMO COMISSÃO*\n"
            f"Vendedor: {dados_comissao.get('vendedor')}\n"
            f"Período: {dados_comissao.get('periodo')}\n"
            f"Total Líquido: {dados_comissao.get('total')}"
        )
        return self.enviar_mensagem_texto(telefone, msg)

    def enviar_mensagem_cadastrada(self, venda, telefone_destino=None):
        is_dacc = "NÃO"
        if venda.forma_pagamento and "DÉBITO" in venda.forma_pagamento.nome.upper(): is_dacc = "SIM"

        agendamento_str = "A confirmar"
        if venda.data_agendamento:
            try:
                dt = venda.data_agendamento
                if isinstance(dt, str): dt = datetime.strptime(dt, '%Y-%m-%d')
                data_fmt = dt.strftime('%d/%m/%Y')
                
                turno = venda.periodo_agendamento or ""
                if turno == 'MANHA': horario = "08:00 às 12:00"
                elif turno == 'TARDE': horario = "13:00 às 18:00"
                else: horario = turno 
                
                agendamento_str = f"Agendamento confirmado para o dia {data_fmt} {horario}"
            except: pass

        vendedor_nome = (venda.vendedor.first_name or venda.vendedor.username).upper() if venda.vendedor else "N/A"
        nome_cliente = venda.cliente.nome_razao_social.upper() if venda.cliente else '-'
        cpf_cnpj = venda.cliente.cpf_cnpj if venda.cliente else '-'
        nome_plano = venda.plano.nome.upper() if venda.plano else '-'
        os_num = venda.ordem_servico or "Gerando..."

        mensagem = (
            f"APROVADO!✅✅\n"
            f"PLANO ADQUIRIDO: {nome_plano}\n"
            f"NOME DO CLIENTE: {nome_cliente}\n"
            f"CPF/CNPJ: {cpf_cnpj}\n"
            f"OS: {os_num}\n"
            f"DACC: {is_dacc}\n"
            f"AGENDAMENTO: {agendamento_str}\n"
            f"VENDEDOR: {vendedor_nome}\n"
            f"⚠FATURA, SEGUNDA VIA OU DÚVIDAS\n"
            f"https://www.niointernet.com.br/\n"
            f"WhatsApp: 31985186530\n"
            f"Para que sua instalação seja concluída favor salvar esse CTO no seu telefone, Técnico Nio 21 4040-1810 para receber informações da Visita."
        )

        fone_para_envio = telefone_destino if telefone_destino else venda.telefone1
        if fone_para_envio:
            return self.enviar_mensagem_texto(fone_para_envio, mensagem)
        return False, "Telefone não informado"

    # ---------------------------------------------------------
    # NOVO MÉTODO: GERAR CARD DE CAMPANHA
    # ---------------------------------------------------------
    def gerar_card_campanha_b64(self, dados):
        """
        Gera um card visual limpo com barra de progresso e destaque financeiro.
        """
        if not Image: 
            return None

        try:
            # 1. Configuração do Canvas (Quadrado HD)
            W, H = 1080, 1080
            cor_fundo = (255, 255, 255) # Branco total
            cor_cabecalho = (10, 30, 60) # Azul Escuro Profissional
            cor_texto_pri = (40, 40, 40)
            cor_texto_sec = (100, 100, 100)
            cor_verde = (0, 160, 80)
            cor_laranja = (255, 120, 0)
            cor_barra_fundo = (230, 230, 230)

            img = Image.new('RGB', (W, H), color=cor_fundo)
            d = ImageDraw.Draw(img)

            # --- CARREGAMENTO DE FONTES (Tentativa robusta) ---
            font_paths = [
                "arial.ttf", "Arial.ttf", 
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "DejaVuSans-Bold.ttf"
            ]
            
            font_path_bold = None
            for path in font_paths:
                try:
                    ImageFont.truetype(path, 20)
                    font_path_bold = path
                    break
                except: continue
            
            if not font_path_bold:
                # print("AVISO: Fontes TTF não encontradas. Usando default (feio).")
                f_titulo = f_nome = f_num = f_label = f_premio = ImageFont.load_default()
            else:
                f_titulo = ImageFont.truetype(font_path_bold, 55)
                f_nome = ImageFont.truetype(font_path_bold, 50)
                f_num = ImageFont.truetype(font_path_bold, 160)
                f_label = ImageFont.truetype(font_path_bold, 35)
                f_destaque = ImageFont.truetype(font_path_bold, 45)
                f_premio = ImageFont.truetype(font_path_bold, 80)

            # =================== DESENHO ===================

            # 1. CABEÇALHO (Topo Azul)
            d.rectangle([(0, 0), (W, 180)], fill=cor_cabecalho)
            campanha_nome = str(dados.get('campanha', 'Campanha')).upper()
            d.text((W/2, 90), campanha_nome, fill="white", anchor="mm", font=f_titulo)

            # 2. IDENTIFICAÇÃO (Nome do Vendedor)
            nome_vendedor = str(dados.get('vendedor', '')).upper()
            d.text((W/2, 260), f"CONSULTOR: {nome_vendedor}", fill=cor_texto_pri, anchor="mm", font=f_label)

            # 3. SCORE PRINCIPAL (Número de Vendas)
            vendas = int(dados.get('vendas', 0))
            d.text((W/2, 380), str(vendas), fill=cor_cabecalho, anchor="mm", font=f_num)
            d.text((W/2, 480), "VENDAS VÁLIDAS", fill=cor_texto_sec, anchor="mm", font=f_label)

            # 4. ÁREA DE RESULTADO (Caixa Cinza Inferior)
            box_y_start = 550
            box_y_end = 950
            d.rounded_rectangle([(50, box_y_start), (W-50, box_y_end)], radius=30, fill=(245, 245, 245))

            prox_meta = dados.get('prox_meta')
            premio_atual = float(dados.get('premio_atual', 0))
            prox_premio = float(dados.get('prox_premio', 0)) if dados.get('prox_premio') else 0

            # --- CENÁRIO A: TEM PRÓXIMA META (FALTA POUCO) ---
            if prox_meta:
                falta = int(prox_meta) - vendas
                pct = min(vendas / prox_meta, 1.0)
                
                bar_x1, bar_y1 = 100, 620
                bar_x2, bar_y2 = W - 100, 660
                
                d.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], fill=cor_barra_fundo)
                fill_width = (bar_x2 - bar_x1) * pct
                color_fill = cor_verde if pct > 0.8 else cor_laranja
                d.rectangle([(bar_x1, bar_y1), (bar_x1 + fill_width, bar_y2)], fill=color_fill)
                
                d.text((W/2, 690), f"{int(pct*100)}% DA META DE {prox_meta}", fill=cor_texto_sec, anchor="mm", font=f_label)
                d.text((W/2, 800), f"FALTAM {falta} VENDAS PARA GANHAR:", fill=cor_laranja, anchor="mm", font=f_destaque)
                val_fmt = f"R$ {prox_premio:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                d.text((W/2, 880), val_fmt, fill=cor_verde, anchor="mm", font=f_premio)

            # --- CENÁRIO B: BATEU O MÁXIMO (LENDÁRIO) ---
            elif premio_atual > 0:
                d.text((W/2, 650), "🏆 META MÁXIMA ATINGIDA!", fill=cor_verde, anchor="mm", font=f_titulo)
                d.text((W/2, 750), "BÔNUS GARANTIDO:", fill=cor_texto_sec, anchor="mm", font=f_destaque)
                val_fmt = f"R$ {premio_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                d.text((W/2, 850), val_fmt, fill=cor_verde, anchor="mm", font=f_premio)

            # --- CENÁRIO C: INÍCIO (SEM PREMIO AINDA) ---
            else:
                alvo = dados.get('meta_atual') or "A PRIMEIRA META"
                d.text((W/2, 650), "VAMOS ACELERAR!", fill=cor_cabecalho, anchor="mm", font=f_titulo)
                d.text((W/2, 750), "O FOCO É BATER:", fill=cor_texto_sec, anchor="mm", font=f_destaque)
                d.text((W/2, 830), f"{alvo} VENDAS", fill=cor_laranja, anchor="mm", font=f_titulo)

            # 5. RODAPÉ
            d.line([(0, 1000), (W, 1000)], fill=(220, 220, 220), width=2)
            periodo = dados.get('periodo', '')
            d.text((W/2, 1040), f"Período: {periodo} | Atualizado em {datetime.now().strftime('%H:%M')}", fill=cor_texto_sec, anchor="mm", font=ImageFont.load_default())

            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            print(f"Erro imagem Pillow: {e}")
            return None

    # ---------------------------------------------------------
    # GERAR IMAGEM DE PERFORMANCE (TABELA) - Layout profissional
    # ---------------------------------------------------------
    def _font_performance(self, name, size):
        """Carrega fonte para a imagem de performance (múltiplos caminhos)."""
        if not ImageFont:
            return ImageFont.load_default()
        paths = [
            "arial.ttf",
            "Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    def gerar_imagem_performance_b64(self, dados_relatorio):
        """
        Gera imagem da tabela de performance:
        título "Performance - Hoje" (ou Semanal/Mensal), tabela com Vendedor, Cluster,
        V. Hoje/Total, Cartão, % CC; linha TOTAL primeiro; cores por faixa de vendas.
        """
        if not Image:
            return None

        try:
            from crm_app.performance_helpers import cor_linha_item_whatsapp, ordenar_lista_performance

            lista = ordenar_lista_performance(dados_relatorio.get('lista', []), key_cluster='cluster', key_nome='nome')
            totais = dados_relatorio.get('totais', {})
            tipo = dados_relatorio.get('tipo', 'HOJE')
            ctx_cores = {
                'dias_decorridos': dados_relatorio.get('dias_decorridos', 1),
                'ctx_faixas': dados_relatorio.get('ctx_faixas'),
            }
            titulo = dados_relatorio.get('titulo', 'Performance - Hoje')
            data_str = dados_relatorio.get('data', '')

            # Coluna "Vendas" muda de nome conforme tipo (labels curtos para evitar sobreposição)
            col_vendas_label = "V. Hoje" if tipo == "HOJE" else "Total"
            is_mensal = tipo == "MENSAL"

            # Uma linha TOTAL + N linhas de dados
            qtd_linhas = 1 + len(lista)
            H_LINHA = 44
            H_TITULO = 72
            H_HEADER = 48
            W = 1200 if is_mensal else 1400  # Mensal: 7 colunas bem separadas, ocupando toda a largura
            H = H_TITULO + H_HEADER + (qtd_linhas * H_LINHA) + 40

            # Cores iguais ao manual (Bootstrap/painel)
            cor_fundo = (255, 255, 255)
            cor_azul_header = (78, 115, 223)   # #4e73df
            cor_azul_total = (44, 62, 80)       # #2c3e50
            cor_texto = (33, 37, 41)
            cor_borda = (227, 230, 240)        # #e3e6f0

            img = Image.new('RGB', (W, H), color=cor_fundo)
            d = ImageDraw.Draw(img)

            f_titulo = self._font_performance("arial", 52)
            f_texto = self._font_performance("arial", 32)
            f_bold = self._font_performance("arial", 32)

            # Título centralizado (preto, como no manual)
            d.text((W / 2, H_TITULO // 2), titulo, fill=cor_texto, anchor="mm", font=f_titulo)

            # Cabeçalho: 7 colunas para MENSAL, 5 para Hoje/Semanal
            # MENSAL: colunas bem espaçadas (Vendedor/Cluster separados) e distribuídas na largura total
            y_start = H_TITULO
            if is_mensal:
                # Vendedor (24) e Cluster (350) bem separados para evitar sobreposição
                # Colunas distribuídas até a borda direita (1100)
                col_x = [24, 350, 500, 650, 800, 950, 1100]
                col_align = ["lm", "mm", "mm", "mm", "mm", "mm", "mm"]
                headers = ["Vendedor", "Cluster", "Total", "Instaladas", "Aprov", "Cartão", "% CC"]
            else:
                col_x = [24, 570, 900, 1150, 1320]
                col_align = ["lm", "mm", "mm", "mm", "mm"]
                headers = ["Vendedor", "Cluster", col_vendas_label, "Cartão", "% CC"]

            d.rectangle([(20, y_start), (W - 20, y_start + H_HEADER)], fill=cor_azul_header)
            for i, label in enumerate(headers):
                anchor = col_align[i]
                x = col_x[i]
                d.text((x, y_start + H_HEADER // 2), label, fill="white", anchor=anchor, font=f_bold)
            y = y_start + H_HEADER

            # Linha TOTAL (igual ao manual: logo após o header)
            d.rectangle([(20, y), (W - 20, y + H_LINHA)], fill=cor_azul_total)
            t_total = totais.get('total', 0)
            t_cc = totais.get('cc', 0)
            t_pct = totais.get('pct', '0%')
            d.text((col_x[0], y + H_LINHA // 2), "TOTAL", fill="white", anchor="lm", font=f_bold)
            d.text((col_x[1], y + H_LINHA // 2), "-", fill="white", anchor="mm", font=f_texto)
            d.text((col_x[2], y + H_LINHA // 2), str(t_total), fill="white", anchor="mm", font=f_bold)
            if is_mensal:
                t_inst = totais.get('instaladas', 0)
                t_aprov = totais.get('aprov', '0%')
                d.text((col_x[3], y + H_LINHA // 2), str(t_inst), fill="white", anchor="mm", font=f_texto)
                d.text((col_x[4], y + H_LINHA // 2), str(t_aprov), fill="white", anchor="mm", font=f_texto)
                d.text((col_x[5], y + H_LINHA // 2), str(t_cc), fill="white", anchor="mm", font=f_texto)
                d.text((col_x[6], y + H_LINHA // 2), str(t_pct), fill="white", anchor="mm", font=f_texto)
            else:
                d.text((col_x[3], y + H_LINHA // 2), str(t_cc), fill="white", anchor="mm", font=f_texto)
                d.text((col_x[4], y + H_LINHA // 2), str(t_pct), fill="white", anchor="mm", font=f_texto)
            y += H_LINHA

            # Linhas de dados: Hoje = faixa diária; Semanal = média/dia; Mensal = faixa comissão
            for i, item in enumerate(lista):
                ly_top = y
                ly_bot = y + H_LINHA
                bg, cor_nums = cor_linha_item_whatsapp(item, tipo, ctx_cores)
                d.rectangle([(20, ly_top), (W - 20, ly_bot)], fill=bg)
                d.line([(20, ly_bot), (W - 20, ly_bot)], fill=cor_borda)

                # MENSAL: nome limitado a 8 chars (coluna Vendedor até ~180px) para não invadir Cluster em 350
                nome_max = 8 if is_mensal else 18
                nome = str(item.get('nome', ''))[:nome_max]
                cluster = str(item.get('cluster', '-'))[:10]
                total = item.get('total', 0)
                cc = item.get('cc', 0)
                pct = item.get('pct', '0%')

                d.text((col_x[0], y + H_LINHA // 2), nome, fill=cor_texto, anchor="lm", font=f_bold)
                d.text((col_x[1], y + H_LINHA // 2), cluster, fill=cor_texto, anchor="mm", font=f_texto)
                d.text((col_x[2], y + H_LINHA // 2), str(total), fill=cor_nums, anchor="mm", font=f_bold)
                if is_mensal:
                    inst = item.get('instaladas', 0)
                    aprov = item.get('aprov', '0%')
                    d.text((col_x[3], y + H_LINHA // 2), str(inst), fill=cor_nums, anchor="mm", font=f_texto)
                    d.text((col_x[4], y + H_LINHA // 2), str(aprov), fill=cor_nums, anchor="mm", font=f_texto)
                    d.text((col_x[5], y + H_LINHA // 2), str(cc), fill=cor_nums, anchor="mm", font=f_texto)
                    d.text((col_x[6], y + H_LINHA // 2), str(pct), fill=cor_nums, anchor="mm", font=f_texto)
                else:
                    d.text((col_x[3], y + H_LINHA // 2), str(cc), fill=cor_nums, anchor="mm", font=f_texto)
                    d.text((col_x[4], y + H_LINHA // 2), str(pct), fill=cor_nums, anchor="mm", font=f_texto)
                y += H_LINHA

            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            print(f"Erro ao gerar imagem performance: {e}")
            return None