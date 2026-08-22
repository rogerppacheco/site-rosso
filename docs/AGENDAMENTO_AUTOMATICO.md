# 📅 Agendamento Automático de Busca de Faturas

Sistema de agendamento automático que busca faturas no site da Nio **3 vezes por dia**.

---

## ⏰ **Horários de Execução**

### **Produção (DEBUG=False):**
- 🌅 **08:00** - Manhã
- 🌤️ **14:00** - Tarde  
- 🌙 **20:00** - Noite

### **Desenvolvimento (DEBUG=True):**
- 🌅 **09:00** - Apenas 1x por dia (evita sobrecarga)

---

## 🚀 **Como Funciona**

1. **Inicialização Automática:**
   - O scheduler inicia automaticamente quando o Django é iniciado
   - Configurado em `crm_app/apps.py` no método `ready()`

2. **Execução:**
   - Processa até **20 contratos** por execução
   - Total: **60 contratos/dia** em produção
   - Previne execuções simultâneas (`max_instances=1`)

3. **Logs:**
   - Todos os logs são registrados no sistema de logging do Django
   - Sucesso: `✅ Busca automática concluída`
   - Erro: `❌ Erro na busca automática`

---

## 📦 **Arquivos do Sistema**

### **1. `crm_app/scheduler.py`**
```python
# Configuração dos horários e jobs
- buscar_faturas_automatico() - Função executada
- start_scheduler() - Inicia o agendador
- init_scheduler() - Inicialização global
```

### **2. `crm_app/apps.py`**
```python
# Integração com Django
class CrmAppConfig(AppConfig):
    def ready(self):
        # Inicia scheduler na inicialização
```

### **3. `crm_app/management/commands/buscar_faturas_nio.py`**
```python
# Comando executado pelo scheduler
python manage.py buscar_faturas_nio --limite 20
```

---

## ⚙️ **Configuração**

### **Alterar Horários:**

Edite `crm_app/scheduler.py`:

```python
schedule = [
    ('0 8 * * *', 'Busca de faturas (08:00)'),   # 08:00
    ('0 14 * * *', 'Busca de faturas (14:00)'),  # 14:00
    ('0 20 * * *', 'Busca de faturas (20:00)'),  # 20:00
]
```

**Formato Cron:**
```
* * * * *
│ │ │ │ │
│ │ │ │ └─ Dia da semana (0-6, 0=Domingo)
│ │ │ └─── Mês (1-12)
│ │ └───── Dia do mês (1-31)
│ └─────── Hora (0-23)
└───────── Minuto (0-59)
```

**Exemplos:**
- `0 8 * * *` - Todo dia às 08:00
- `0 */4 * * *` - A cada 4 horas
- `0 9-17 * * 1-5` - Dias úteis das 9h às 17h
- `0 12 * * 0` - Domingos ao meio-dia

### **Alterar Quantidade de Contratos:**

Edite `crm_app/scheduler.py`:

```python
call_command('buscar_faturas_nio', '--limite', '50')  # 50 contratos
```

---

## 🔍 **Monitoramento**

### **Ver Status dos Jobs:**

```python
from crm_app.scheduler import scheduler

# Listar jobs agendados
jobs = scheduler.get_jobs()
for job in jobs:
    print(f"{job.name}: {job.next_run_time}")
```

### **Logs do Sistema:**

```bash
# Ver logs em tempo real
tail -f logs/django.log

# Buscar logs de busca de faturas
grep "busca automática" logs/django.log
```

### **Verificar Última Execução:**

```python
from crm_app.models import FaturaM10
from django.utils import timezone
from datetime import timedelta

# Faturas criadas/atualizadas nas últimas 24h
ultima_24h = timezone.now() - timedelta(hours=24)
faturas_recentes = FaturaM10.objects.filter(atualizado_em__gte=ultima_24h)
print(f"Faturas processadas (24h): {faturas_recentes.count()}")
```

---

## 🛠️ **Comandos Úteis**

### **Executar Manualmente:**
```bash
python manage.py buscar_faturas_nio --limite 20
```

### **Testar Scheduler:**
```python
# Django Shell
python manage.py shell

from crm_app.scheduler import buscar_faturas_automatico
buscar_faturas_automatico()  # Executa imediatamente
```

### **Reiniciar Scheduler:**
```bash
# Reinicie o servidor Django
python manage.py runserver
```

---

## 🚨 **Troubleshooting**

### **Scheduler não inicia:**

1. Verifique se APScheduler está instalado:
```bash
pip install APScheduler
```

2. Verifique logs de inicialização:
```
⚠️  Erro ao iniciar scheduler: ...
```

3. Confirme que `RUN_MAIN='true'`:
```python
import os
print(os.environ.get('RUN_MAIN'))  # Deve ser 'true'
```

### **Jobs não executam:**

1. Verifique se scheduler está rodando:
```python
from crm_app.scheduler import scheduler
print(scheduler.running)  # Deve ser True
```

2. Verifique próxima execução:
```python
jobs = scheduler.get_jobs()
for job in jobs:
    print(f"{job.name}: {job.next_run_time}")
```

3. Force execução manual:
```bash
python manage.py buscar_faturas_nio --limite 1
```

### **Execuções duplicadas:**

- O parâmetro `max_instances=1` previne isso
- Verifique se há múltiplas instâncias do Django rodando

---

## 🌐 **Deploy em Produção**

### **Railway:**

1. **Procfile** já está configurado (web + scheduler):
```
web: sh scripts/start_web.sh
scheduler: python manage.py run_scheduler
```

2. O serviço **scheduler** roda em processo próprio (1 réplica)

### **VPS/Servidor Dedicado:**

1. **Systemd Service** (recomendado):
```bash
# /etc/systemd/system/django-app.service
[Service]
ExecStart=/path/to/venv/bin/gunicorn gestao_equipes.wsgi
Restart=always
```

2. **Supervisor** (alternativa):
```ini
[program:django-app]
command=/path/to/venv/bin/gunicorn gestao_equipes.wsgi
autostart=true
autorestart=true
```

---

## 📊 **Estatísticas**

### **Capacidade Diária:**
- **3 execuções/dia** × **20 contratos** = **60 contratos/dia**
- **60 contratos/dia** × **30 dias** = **1.800 contratos/mês**

### **Tempo de Execução:**
- **~30 segundos/contrato** (com Selenium)
- **20 contratos** = **~10 minutos** por execução
- **3 execuções/dia** = **~30 minutos/dia** de processamento

---

## ✅ **Verificação de Funcionamento**

Execute este script para confirmar:

```python
# Django Shell
python manage.py shell

from crm_app.scheduler import scheduler
from crm_app.models import FaturaM10
from django.utils import timezone
from datetime import timedelta

# 1. Scheduler está rodando?
print(f"✅ Scheduler ativo: {scheduler.running}")

# 2. Jobs agendados
jobs = scheduler.get_jobs()
print(f"✅ {len(jobs)} job(s) agendado(s)")
for job in jobs:
    print(f"   - {job.name}: {job.next_run_time}")

# 3. Faturas processadas hoje
hoje = timezone.now().date()
faturas_hoje = FaturaM10.objects.filter(atualizado_em__date=hoje)
print(f"✅ {faturas_hoje.count()} faturas processadas hoje")

# 4. Contratos com CPF (elegíveis)
from crm_app.models import ContratoM10
com_cpf = ContratoM10.objects.exclude(cpf_cliente__isnull=True).exclude(cpf_cliente='')
print(f"✅ {com_cpf.count()} contratos elegíveis para busca automática")
```

---

## 📝 **Logs Importantes**

### **Inicialização:**
```
⚙️  Modo PRODUÇÃO: Agendador configurado para 3x/dia
✅ Agendador iniciado com sucesso!
📋 3 tarefa(s) agendada(s):
  - Busca de faturas (08:00): cron[hour='8', minute='0']
  - Busca de faturas (14:00): cron[hour='14', minute='0']
  - Busca de faturas (20:00): cron[hour='20', minute='0']
```

### **Execução:**
```
🤖 Iniciando busca automática de faturas...
[1/20] Processando: OS-12345 - João Silva
  💰 Valor: R$ 99.90
  ✅ Código PIX capturado
  ✅ PDF baixado
✅ Busca automática concluída com sucesso!
```

---

**Sistema configurado e pronto para rodar automaticamente! 🎉**
