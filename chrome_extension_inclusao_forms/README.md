# Extensão Chrome — Inclusão / Viabilidade

Preenche o Google Forms de Inclusão a partir da aba **Auditoria → Inclusão**.

## Instalação

1. Abra `chrome://extensions`
2. Ative **Modo do desenvolvedor**
3. **Carregar sem compactação** → selecione esta pasta (`chrome_extension_inclusao_forms`)
4. Faça login no Record PAP e no Google (conta que abre o formulário)
5. Em Auditoria, aba **Inclusão**, clique em **Abrir no Forms**

## Fluxo

1. WhatsApp cria a demanda + sobe anexos no R2 (sem Playwright no Railway)
2. Auditor clica **Abrir no Forms**
3. Extensão marca a demanda como em andamento, abre o Forms e preenche/anexa
4. Ao confirmar o envio, marca a demanda como **ENVIADA**

## Observações

- O preenchimento automático pode falhar se o Google mudar o layout; nesse caso complete manualmente e use a lista para acompanhar.
- Recarregue a página da Auditoria após instalar/atualizar a extensão.
