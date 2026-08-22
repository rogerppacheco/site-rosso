# Guia: Presença com confirmação por selfie e OneDrive

Este documento descreve a melhoria da ferramenta de presença: o supervisor/líder continua marcando presença da equipe e, para **confirmar** todas as marcações do dia, precisa tirar uma **selfie com o time** (câmera ao vivo, sem upload de arquivo). A foto deve exibir **data** e **local (GPS)** e ser salva no **OneDrive** organizada por data.

---

## 1. Fluxo de negócio

1. **Supervisor** abre a tela de Presença (aba "Minha Equipe"), escolhe a data e marca Presente/Ausência de cada membro.
2. Quando terminar de marcar (ou quando quiser fechar o dia), ele clica em **"Confirmar presença do dia"**.
3. Abre um **modal** que:
   - Solicita permissão da **câmera** (não permite escolher arquivo do dispositivo).
   - Mostra a **preview ao vivo** da câmera.
   - Botão **"Tirar foto"** captura o frame atual.
4. Na foto capturada o sistema **insere automaticamente** (desenho na imagem):
   - **Data** (ex.: 10/02/2025 14:35)
   - **Local** (coordenadas ou endereço obtido via GPS).
5. O supervisor confirma e a foto é enviada ao backend, que:
   - Salva o registro de “confirmação do dia” (data, supervisor, link da foto, lat/lng).
   - Faz upload da imagem para o **OneDrive** em pasta organizada por data (ex.: `Presenca_Selfies/2025-02-10/`).

---

## 2. Requisitos técnicos resumidos

| Requisito | Solução |
|-----------|--------|
| Câmera ao vivo, sem upload de arquivo | `navigator.mediaDevices.getUserMedia({ video: true })` + `<video>` + captura do frame em `<canvas>`. Não exibir `<input type="file">`. |
| Data e local na foto | Obter data no front; obter GPS com `navigator.geolocation.getCurrentPosition`; desenhar textos no canvas antes de exportar o blob. |
| Salvar no OneDrive por data | Backend usa `OneDriveUploader` existente (`crm_app.onedrive_service`) com pasta `Presenca_Selfies/YYYY-MM-DD/` e nome de arquivo único. |
| Registrar quem confirmou e quando | Novo modelo no app `presenca` (ex.: `ConfirmacaoPresencaDia`) com data, supervisor, URL da foto, lat, lng. |

---

## 3. Backend

### 3.1 Modelo de dados (presenca)

Foi adicionado o modelo **`ConfirmacaoPresencaDia`** (veja `presenca/models.py`):

- `data` (Date): dia da presença confirmado.
- `supervisor` (FK Usuario): quem confirmou (líder).
- `foto_url` (URL no OneDrive): link da selfie.
- `latitude` / `longitude` (opcional): coordenadas no momento da foto.
- `criado_em` (DateTime): quando a confirmação foi feita.

Isso permite:
- Saber se aquele dia já foi “fechado” com selfie.
- Exibir na tela um indicador “Dia confirmado com selfie” e, se desejado, link para ver a foto.

### 3.2 API

- **GET** ` /api/presenca/confirmacao-dia/?data=YYYY-MM-DD`  
  - Retorna a confirmação do dia (se existir) para a data e para o supervisor/equipe (conforme regras de negócio).
- **POST** ` /api/presenca/confirmacao-dia/`  
  - Corpo: `multipart/form-data` com:
    - `foto`: arquivo da imagem (já com data e local desenhados pelo front).
    - `data`: `YYYY-MM-DD`.
    - `latitude`, `longitude`: opcionais.
  - Backend:
    1. Valida que o usuário é supervisor (ou que tem permissão para confirmar aquele dia).
    2. Gera nome de arquivo único (ex.: `equipe_{username}_{data}_{hora}.jpg`).
    3. Usa `OneDriveUploader` para subir em `Presenca_Selfies/YYYY-MM-DD/` (ou constante em settings).
    4. Cria/atualiza registro `ConfirmacaoPresencaDia` com `foto_url` (retornado pelo OneDrive) e salva no banco.
    5. Retorna o objeto da confirmação (incluindo `foto_url`).

O OneDrive já está configurado no projeto (`MS_CLIENT_ID`, `MS_REFRESH_TOKEN`, `MS_DRIVE_FOLDER_ROOT`). A pasta base pode ser `Presenca_Selfies` dentro do mesmo root, com subpastas por data.

---

## 4. Frontend (presenca.html)

### 4.1 Botão “Confirmar presença do dia”

- Visível apenas para quem pode marcar presença (supervisor da equipe / gestores), na aba “Minha Equipe”.
- Pode ficar no topo da página ou acima do grid de cards (ex.: “Confirmar presença do dia com selfie”).

### 4.2 Modal da selfie

- **Não** incluir `<input type="file" accept="image/*">` (evita enviar foto já tirada).
- Conteúdo do modal:
  - `<video id="camera-preview" autoplay playsinline muted>` para a câmera ao vivo.
  - Botão “Tirar foto”: ao clicar, desenha o frame do vídeo em um `<canvas>` (oculto), adiciona os textos (data e local) no canvas, exporta como blob (ex.: `canvas.toBlob('image/jpeg')`) e mostra preview (outro `<img>` ou o próprio canvas).
  - Botão “Confirmar e enviar”: envia o blob + `data` + `latitude` + `longitude` para `POST /api/presenca/confirmacao-dia/` em `FormData`.
  - Botão “Cancelar”: fecha o modal e para as tracks da câmera (`stream.getTracks().forEach(t => t.stop())`).

### 4.3 Obter data e local

- **Data/hora:** `new Date()` no momento do clique em “Tirar foto” (ou no envio), formatada (ex.: `DD/MM/YYYY HH:mm`).
- **GPS:** `navigator.geolocation.getCurrentPosition()` ao abrir o modal (ou ao clicar em “Tirar foto”). Use `enableHighAccuracy` e um timeout razoável. Em caso de falha (sem permissão ou sem GPS), pode desenhar “Local indisponível” ou apenas a data.

### 4.4 Desenhar na imagem (canvas)

- Desenhar a imagem do vídeo no canvas (mesmo tamanho do frame).
- Desenhar um retângulo semitransparente na parte inferior (ou onde fizer sentido) e, em cima, texto com:
  - Linha 1: `Data: 10/02/2025 14:35`
  - Linha 2: `Local: -23.5505, -46.6333` ou endereço se fizer geocoding reverso (opcional).
- Fonte legível (ex.: 18–24px), cor branca com sombra para contraste.
- Ao final, usar `canvas.toBlob('image/jpeg', 0.9, blob => { ... })` e enviar esse `blob` no `FormData` como `foto`.

### 4.5 Indicador “Dia confirmado”

- Ao carregar a página (ou após enviar a confirmação), chamar `GET /api/presenca/confirmacao-dia/?data=YYYY-MM-DD`.
- Se existir confirmação para a data e equipe, exibir um aviso/badge: “Dia confirmado com selfie” e, se a API retornar `foto_url`, um link “Ver foto” que abre a selfie no OneDrive.

---

## 5. OneDrive – organização por data

- **Pasta base:** por exemplo `Presenca_Selfies` (pode ser constante em `settings` ou variável de ambiente).
- **Subpasta por data:** `YYYY-MM-DD` (ex.: `2025-02-10`).
- **Nome do arquivo:** único por confirmação, ex.: `equipe_{username}_{YYYY-MM-DD}_{HH-mm}.jpg`.
- Caminho final no drive (considerando `MS_DRIVE_FOLDER_ROOT`):  
  `{MS_DRIVE_FOLDER_ROOT}/Presenca_Selfies/2025-02-10/equipe_joao_2025-02-10_14-30.jpg`

O projeto já possui `OneDriveUploader` em `crm_app/onedrive_service.py` com `upload_file(file_obj, folder_name, filename)`. O backend da presença pode usar esse serviço com `folder_name = f"Presenca_Selfies/{data}"` e `filename` único.

---

## 6. Ordem sugerida de implementação

1. **Backend**
   - Criar modelo `ConfirmacaoPresencaDia` e migração.
   - Criar endpoint GET e POST de confirmação (validação de permissão, upload OneDrive, persistência).
   - Testar upload manual (Postman/curl) com uma imagem e conferir no OneDrive.

2. **Frontend – modal e câmera**
   - Adicionar botão “Confirmar presença do dia” e modal.
   - Implementar abertura da câmera com `getUserMedia`, exibição no `<video>` e parada das tracks ao fechar.
   - Botão “Tirar foto”: captura do vídeo para canvas, desenho de data e local, preview e envio do blob via `FormData` para o POST.

3. **Frontend – GPS e UX**
   - Solicitar GPS ao abrir o modal; tratar permissão negada e timeout.
   - Exibir “Dia confirmado” quando GET retornar confirmação para a data.

4. **Ajustes finais**
   - Política de “só uma confirmação por dia por supervisor” (ou por equipe), se desejado.
   - Ajustes de layout e textos conforme padrão do sistema.

---

## 7. Segurança e privacidade

- **HTTPS:** obrigatório para `getUserMedia` e Geolocation em produção.
- **Permissão de câmera e local:** o navegador pede ao usuário; falhas devem ser tratadas com mensagem clara.
- **Token JWT:** o POST de confirmação deve exigir autenticação (já padrão nas APIs do projeto) e validar que o usuário é supervisor da equipe daquela data.
- **OneDrive:** usar as mesmas credenciais já configuradas (conta da empresa); pasta restrita ao uso interno.

---

## 8. Referências no código atual

- **Presença (lista, marcação):** `presenca/views.py` (`PresencaViewSet`), `presenca/models.py` (`Presenca`), `frontend/public/presenca.html`.
- **OneDrive:** `crm_app/onedrive_service.py` (`OneDriveUploader.upload_file`), `gestao_equipes/settings.py` (variáveis `MS_*`, `MS_DRIVE_FOLDER_ROOT`).
- **Quem é supervisor:** `Usuario.liderados` (related_name do FK `supervisor`) e filtro em `MinhaEquipeListView` (só retorna liderados do usuário).

Com esse guia e a estrutura de modelo/API descritos, a melhoria pode ser implementada de forma consistente com o restante do sistema.

---

## 9. Checklist rápido – Frontend (presenca.html)

- [ ] Botão **"Confirmar presença do dia"** (visível só para supervisor/gestor na aba Minha Equipe).
- [ ] Modal com **apenas** `<video>` + captura ao vivo (sem `<input type="file">`).
- [ ] Ao abrir o modal: pedir permissão de câmera (`getUserMedia`) e de localização (`getCurrentPosition`).
- [ ] Botão **"Tirar foto"**: copiar frame do vídeo para `<canvas>`, desenhar texto com data e coordenadas/endereço, gerar blob com `canvas.toBlob('image/jpeg')`.
- [ ] Botão **"Confirmar e enviar"**: `FormData` com `foto` (blob), `data` (YYYY-MM-DD), `latitude`, `longitude` → `POST /api/presenca/confirmacao-dia/`.
- [ ] Ao fechar o modal: parar as tracks do stream (`getTracks().forEach(t => t.stop())`).
- [ ] Após carregar a página (e após envio): `GET /api/presenca/confirmacao-dia/?data=YYYY-MM-DD`; se `confirmado === true`, exibir "Dia confirmado com selfie" e link "Ver foto" (`detalhe.foto_url`).
