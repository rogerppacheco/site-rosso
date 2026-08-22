# Como inspecionar a página do boleto Nio no DevTools

O botão **"Download"** no site da Nio **não baixa um arquivo** — ele chama `populateInvoice(data)` (preenche a área de impressão) e em seguida **window.print()** (diálogo "Salvar como PDF").

## Estrutura descoberta (HTML do site)

- **Botões:** `#barCodeCopyButton` (Copiar Código), `#downloadInvoice` (Download, `href="javascript:void(0)"`). Na página podem existir vários `#downloadInvoice` (Pix vs Boleto); preferir o do contexto Boleto: `#scheduled-payment__details #downloadInvoice`.
- **Área de impressão:** div `#invoice-area` com classe `download-contas` — fica com `display: none` na tela e só aparece em `@media print`. Contém:
  - `#amount-due`, `#payment-due-date`, `#digitable-line`, `#barcode-canvas`
- **Comportamento do clique em Download:** o listener chama `populateInvoice(data)` (preenche os elementos acima) e depois `window.print()`. Ou seja: **o conteúdo que vai para o PDF só é preenchido no clique**. Se gerarmos o PDF sem clicar antes, a área pode estar vazia → PDF "zerado".
- **Não é iframe:** está na página principal.

## 1. Inspecionar no DevTools

1. Abra o site da 2ª via, faça o fluxo até o modal do boleto (Copiar Código / Download visíveis).
2. DevTools (F12) → aba **Elements**. Ctrl+F:
   - `download-contas` ou `invoice-area` → div oculta que vira o conteúdo do PDF em `@media print`.
   - `downloadInvoice` → botão que dispara populateInvoice + window.print.
3. **Rendering** (Ctrl+Shift+P → "Rendering"): em **Emulate CSS media** escolha **print** e confira se `#invoice-area` aparece com valor, vencimento e código de barras (só depois de ter clicado em Download uma vez na sessão).

## 2. Resumo para o código

- **Ordem correta:** (1) garantir modal do boleto visível, (2) **clicar no Download do Boleto** (`#scheduled-payment__details #downloadInvoice`, fallback `#downloadInvoice`) para preencher `#invoice-area`, (3) opcionalmente neutralizar `window.print` para não abrir diálogo, (4) **esperar `#barcode-canvas` ter width/height > 0** (evita PDF corrompido), (5) `page.emulate_media(media="print")` + `page.pdf(..., prefer_css_page_size=True)`.
- Sem o clique, `#invoice-area` pode estar vazia e o PDF sai zerado.
- Se o PDF abrir com erro no Chrome ("Não é possível abrir este arquivo"): costuma ser timing — capturar antes do canvas do código de barras ser desenhado gera PDF inválido. Solução: aguardar o canvas e usar `prefer_css_page_size=True`.
