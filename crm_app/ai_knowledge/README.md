# Base de conhecimento da IA do bot WhatsApp

O conteúdo desta pasta é carregado e enviado à IA (Groq/Gemini) para que o bot responda com base em **telecom**, **Nio** e **dados da sua empresa**.

## Arquivos

- **conhecimento.md** – Edite este arquivo com:
  - Informações sobre a empresa e a Nio
  - Resumo dos planos (nome, velocidade, valor, benefícios) – pode colar texto extraído dos PDFs
  - Regras de negócio, prazos, processos
  - Qualquer texto que ajude a IA a responder dúvidas dos vendedores

- **schema_tabelas.md** – (opcional) Descrição das tabelas do banco. Pode ser gerado automaticamente pelo projeto; você pode completar com explicações.

## Como usar

1. Edite **conhecimento.md** em qualquer editor de texto.
2. Use as seções sugeridas (Empresa/Nio, Planos, Processos) ou crie as suas.
3. Para conteúdo de PDF: copie e cole o texto dos planos/tabelas para dentro do `conhecimento.md`. Se o PDF for só imagem, use um conversor PDF → texto antes.
4. Salve o arquivo. Na próxima mensagem no WhatsApp que for respondida pela IA, o novo conteúdo já será considerado (não precisa reiniciar o servidor se o arquivo for lido a cada requisição).

## Dicas

- Seja objetivo: listas e tópicos curtos funcionam melhor do que parágrafos longos.
- Inclua nomes exatos de planos, valores e prazos que a IA deve citar.
- Não coloque dados sensíveis (senhas, chaves) aqui; o arquivo pode ir para o repositório.

## Treinar a IA / Groq tem painel para isso?

O **Groq** (e a API do Gemini que usamos) **não oferece “treino” ou base de conhecimento no painel**. Eles são só APIs de inferência: você manda o texto e recebe a resposta. O “treino” do nosso bot é feito assim:

1. **conhecimento.md** – sempre enviado no contexto; o ideal é ter aqui os **planos da Nio** e o essencial (assim a IA sempre tem a informação, mesmo em modo reduzido).
2. **Documentos** (PDF/Excel/PPT) na página “Conhecimento IA” – texto extraído é incluído no contexto.
3. **Sites** na mesma página – conteúdo das URLs é incluído no contexto.

Para perguntas como “Quais são os planos da Nio?”, o mais garantido é **preencher a seção “Planos” do conhecimento.md** com a lista real. Documentos e sites complementam, mas em caso de limite de tamanho (erro 413) o sistema pode enviar só o conhecimento.md; por isso o essencial deve estar nele.
