# 📋 Implementação: Registro Manual de 10 Faturas - Bônus M-10 & FPD

## ✅ O que foi implementado (Backend)

### 1. **Modelo de Dados Atualizado**
Adicionamos 3 novos campos ao modelo `FaturaM10`:

```python
# crm_app/models.py - Classe FaturaM10
codigo_pix = models.TextField(blank=True, null=True, help_text="Código PIX Copia e Cola")
codigo_barras = models.CharField(max_length=100, blank=True, null=True, help_text="Código de barras da fatura")
arquivo_pdf = models.FileField(upload_to='faturas_m10/%Y/%m/', blank=True, null=True, help_text="PDF da fatura")
```

**Estrutura da tabela agora:**
- ✅ `valor` (já existia)
- ✅ `data_vencimento` (já existia)
- ✅ `codigo_pix` (NOVO - texto longo para PIX Copia e Cola)
- ✅ `codigo_barras` (NOVO - código de barras)
- ✅ `arquivo_pdf` (NOVO - upload do PDF)

### 2. **API Backend Criada**

#### **Serializer** (`crm_app/serializers.py`)
```python
class FaturaM10Serializer(serializers.ModelSerializer):
    arquivo_pdf_url = serializers.SerializerMethodField()  # Retorna URL do PDF
```

#### **Views/Endpoints** (`crm_app/views.py`)
Criadas 2 novas views:

1. **`FaturaM10ListView`** - Lista faturas de um contrato
   - **URL:** `GET /api/bonus-m10/faturas/?contrato_id=123`
   - **Retorno:** Lista com todas as faturas do contrato

2. **`FaturaM10DetailView`** - Detalhes e atualização de uma fatura
   - **URL:** `GET/PATCH /api/bonus-m10/faturas/<id>/`
   - **Suporta:** Upload de arquivos (multipart/form-data)
   - **Retorno:** Dados completos da fatura + URL do PDF

### 3. **Rotas Configuradas** (`gestao_equipes/urls.py`)
```python
path('api/bonus-m10/faturas/', FaturaM10ListView.as_view(), name='api-faturas-m10-list'),
path('api/bonus-m10/faturas/<int:pk>/', FaturaM10DetailView.as_view(), name='api-faturas-m10-detail'),
```

### 4. **Configuração de Mídia** (`gestao_equipes/settings.py`)
```python
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

Os PDFs serão salvos em: `media/faturas_m10/2025/12/arquivo.pdf`

### 5. **Migration Criada**
```
crm_app\migrations\0048_faturam10_arquivo_pdf_faturam10_codigo_barras_and_more.py
```

---

## 🚀 Próximos Passos - O que você precisa fazer

### **Passo 1: Aplicar a Migration no Banco de Dados**
```bash
cd C:\site-record
python manage.py migrate
```

### **Passo 2: Criar o Frontend (Interface de Registro)**

Você precisa criar uma página HTML para permitir o registro manual das 10 faturas. Aqui está uma sugestão de estrutura:

#### **Estrutura da Página:**
```html
<!-- frontend/public/registrar_faturas.html -->

<div class="container">
    <h1>Registrar 10 Faturas - Contrato: <span id="numero-contrato"></span></h1>
    
    <!-- Navegação por Faturas (Abas ou Acordeão) -->
    <ul class="nav nav-tabs">
        <li class="nav-item"><a class="nav-link active" href="#" onclick="mostrarFatura(1)">Fatura 1</a></li>
        <li class="nav-item"><a class="nav-link" href="#" onclick="mostrarFatura(2)">Fatura 2</a></li>
        <!-- ... até fatura 10 -->
    </ul>
    
    <!-- Formulário de Fatura -->
    <form id="form-fatura">
        <input type="hidden" id="fatura-id" />
        <input type="hidden" id="contrato-id" />
        
        <div class="mb-3">
            <label>Valor da Fatura (R$)</label>
            <input type="number" id="fatura-valor" class="form-control" step="0.01" required />
        </div>
        
        <div class="mb-3">
            <label>Data de Vencimento</label>
            <input type="date" id="fatura-vencimento" class="form-control" required />
        </div>
        
        <div class="mb-3">
            <label>Código PIX (Copia e Cola)</label>
            <textarea id="fatura-pix" class="form-control" rows="3"></textarea>
        </div>
        
        <div class="mb-3">
            <label>Código de Barras</label>
            <input type="text" id="fatura-barras" class="form-control" />
        </div>
        
        <div class="mb-3">
            <label>Upload da Fatura (PDF)</label>
            <input type="file" id="fatura-pdf" class="form-control" accept="application/pdf" />
            <small id="pdf-atual"></small>
        </div>
        
        <div class="mb-3">
            <label>Status</label>
            <select id="fatura-status" class="form-select">
                <option value="NAO_PAGO">Não Pago</option>
                <option value="PAGO">Pago</option>
                <option value="AGUARDANDO">Aguardando Arrecadação</option>
                <option value="ATRASADO">Atrasado</option>
            </select>
        </div>
        
        <button type="button" onclick="salvarFatura()" class="btn btn-primary">Salvar Fatura</button>
    </form>
</div>
```

#### **JavaScript para Gerenciar Faturas:**
```javascript
let faturaAtual = 1;
let contratoId = null;
let faturas = {}; // Cache das 10 faturas

async function carregarContrato(id) {
    contratoId = id;
    const res = await fetch(`/api/bonus-m10/contratos/${id}/`);
    const contrato = await res.json();
    document.getElementById('numero-contrato').textContent = contrato.numero_contrato;
    
    // Carregar faturas existentes
    await carregarFaturas();
}

async function carregarFaturas() {
    const res = await fetch(`/api/bonus-m10/faturas/?contrato_id=${contratoId}`);
    const lista = await res.json();
    
    // Criar 10 faturas se não existirem
    for (let i = 1; i <= 10; i++) {
        const fatura = lista.find(f => f.numero_fatura === i);
        if (fatura) {
            faturas[i] = fatura;
        } else {
            // Criar fatura vazia
            faturas[i] = {
                numero_fatura: i,
                contrato: contratoId,
                valor: 0,
                data_vencimento: '',
                status: 'NAO_PAGO',
                codigo_pix: '',
                codigo_barras: '',
            };
        }
    }
    
    mostrarFatura(1);
}

function mostrarFatura(numero) {
    faturaAtual = numero;
    const fatura = faturas[numero];
    
    document.getElementById('fatura-id').value = fatura.id || '';
    document.getElementById('fatura-valor').value = fatura.valor;
    document.getElementById('fatura-vencimento').value = fatura.data_vencimento;
    document.getElementById('fatura-pix').value = fatura.codigo_pix || '';
    document.getElementById('fatura-barras').value = fatura.codigo_barras || '';
    document.getElementById('fatura-status').value = fatura.status;
    
    // Mostrar PDF atual se existir
    if (fatura.arquivo_pdf_url) {
        document.getElementById('pdf-atual').innerHTML = 
            `<a href="${fatura.arquivo_pdf_url}" target="_blank">📄 Ver PDF Atual</a>`;
    } else {
        document.getElementById('pdf-atual').innerHTML = '';
    }
}

async function salvarFatura() {
    const faturaId = document.getElementById('fatura-id').value;
    const formData = new FormData();
    
    formData.append('contrato', contratoId);
    formData.append('numero_fatura', faturaAtual);
    formData.append('valor', document.getElementById('fatura-valor').value);
    formData.append('data_vencimento', document.getElementById('fatura-vencimento').value);
    formData.append('status', document.getElementById('fatura-status').value);
    formData.append('codigo_pix', document.getElementById('fatura-pix').value);
    formData.append('codigo_barras', document.getElementById('fatura-barras').value);
    
    const pdfFile = document.getElementById('fatura-pdf').files[0];
    if (pdfFile) {
        formData.append('arquivo_pdf', pdfFile);
    }
    
    try {
        let url, method;
        if (faturaId) {
            // Atualizar fatura existente
            url = `/api/bonus-m10/faturas/${faturaId}/`;
            method = 'PATCH';
        } else {
            // Criar nova fatura (você precisa adicionar endpoint POST)
            url = `/api/bonus-m10/faturas/`;
            method = 'POST';
        }
        
        const response = await fetch(url, {
            method: method,
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('accessToken')}`
            },
            body: formData
        });
        
        if (response.ok) {
            alert('Fatura salva com sucesso!');
            await carregarFaturas();
        } else {
            alert('Erro ao salvar fatura');
        }
    } catch (error) {
        console.error('Erro:', error);
        alert('Erro ao salvar fatura');
    }
}
```

### **Passo 3: Adicionar Endpoint de Criação (POST)**

Atualmente só temos GET e PATCH. Para criar novas faturas, você precisa adicionar um endpoint POST. 

**Opção 1: Modificar a view existente**
```python
# Em crm_app/views.py
class FaturaM10ListView(generics.ListCreateAPIView):  # Mudou de ListAPIView para ListCreateAPIView
    serializer_class = FaturaM10Serializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    
    def get_queryset(self):
        contrato_id = self.request.query_params.get('contrato_id')
        if contrato_id:
            return FaturaM10.objects.filter(contrato_id=contrato_id).order_by('numero_fatura')
        return FaturaM10.objects.none()
```

### **Passo 4: Testar Localmente**
```bash
# Rodar servidor
python manage.py runserver

# Acessar:
http://localhost:8000/registrar-faturas.html?contrato_id=1
```

### **Passo 5: Deploy para Railway**
```bash
git add .
git commit -m "Add registro manual de 10 faturas M-10"
git push origin main
```

---

## 📝 Exemplo de Uso da API

### **1. Listar faturas de um contrato**
```bash
GET /api/bonus-m10/faturas/?contrato_id=123
Authorization: Bearer <token>
```

**Resposta:**
```json
[
    {
        "id": 1,
        "contrato": 123,
        "numero_fatura": 1,
        "valor": "89.90",
        "data_vencimento": "2025-01-15",
        "codigo_pix": "00020126360014br.gov.bcb.pix...",
        "codigo_barras": "12345678901234567890123456789012345678901234567890",
        "arquivo_pdf": "/media/faturas_m10/2025/01/fatura_1.pdf",
        "arquivo_pdf_url": "http://localhost:8000/media/faturas_m10/2025/01/fatura_1.pdf",
        "status": "NAO_PAGO"
    },
    ...
]
```

### **2. Criar nova fatura**
```bash
POST /api/bonus-m10/faturas/
Authorization: Bearer <token>
Content-Type: multipart/form-data

contrato=123
numero_fatura=1
valor=89.90
data_vencimento=2025-01-15
codigo_pix=00020126360014br.gov.bcb.pix...
codigo_barras=1234567890...
arquivo_pdf=<binary_file_data>
status=NAO_PAGO
```

### **3. Atualizar fatura existente**
```bash
PATCH /api/bonus-m10/faturas/1/
Authorization: Bearer <token>
Content-Type: multipart/form-data

valor=99.90
arquivo_pdf=<novo_pdf>
```

---

## 🎯 Checklist de Implementação

### Backend ✅
- [x] Adicionar campos ao modelo FaturaM10
- [x] Criar serializer FaturaM10Serializer
- [x] Criar views (List e Detail)
- [x] Configurar rotas
- [x] Configurar MEDIA_URL e MEDIA_ROOT
- [x] Criar migration
- [ ] Aplicar migration (`python manage.py migrate`)
- [ ] Adicionar método POST na FaturaM10ListView

### Frontend ⏳
- [ ] Criar página HTML registrar_faturas.html
- [ ] Implementar navegação por abas (10 faturas)
- [ ] Criar formulário de entrada
- [ ] Implementar upload de PDF
- [ ] Conectar com API backend
- [ ] Adicionar validações de formulário
- [ ] Implementar feedback visual (loading, sucesso, erro)
- [ ] Adicionar link no menu do Bônus M-10

### Testes 🧪
- [ ] Testar criação de fatura
- [ ] Testar atualização de fatura
- [ ] Testar upload de PDF
- [ ] Testar carregamento de PDF existente
- [ ] Testar validações (campos obrigatórios)
- [ ] Testar navegação entre as 10 faturas

---

## 💡 Melhorias Futuras

1. **Busca Automática de Faturas:**
   - Integração com site da operadora (TIM, Claro, Vivo, etc.)
   - Web scraping ou API oficial
   - Preenchimento automático dos campos

2. **Validações Avançadas:**
   - Validar formato de código de barras (47 dígitos)
   - Validar código PIX
   - Validar tamanho máximo de arquivo PDF (ex: 5MB)

3. **Notificações:**
   - WhatsApp quando todas as 10 faturas forem registradas
   - Alertas de vencimento próximo

4. **Relatórios:**
   - Dashboard visual do status das faturas
   - Relatório de faturas pendentes de upload

---

## 📞 Suporte

Se encontrar algum problema:
1. Verifique os logs: `railway logs`
2. Teste localmente primeiro
3. Verifique se a migration foi aplicada
4. Confirme se as configurações de MEDIA estão corretas

---

**Desenvolvido em:** 31 de Dezembro de 2025
**Próxima etapa:** Implementar frontend de registro manual
