# 🗄️ Estrutura SQL: Cruzamento FPD com BONUS M10

## Tabelas Afetadas

### 1. FaturaM10 (Alterada)

```sql
CREATE TABLE crm_app_faturam10 (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    contrato_id BIGINT NOT NULL,
    numero_fatura INT NOT NULL,
    numero_fatura_operadora VARCHAR(100),
    valor DECIMAL(10,2),
    data_vencimento DATE NOT NULL,
    data_pagamento DATE,
    dias_atraso INT DEFAULT 0,
    status VARCHAR(20),
    
    -- NOVOS CAMPOS FPD
    id_contrato_fpd VARCHAR(100),              -- ID_CONTRATO da planilha
    dt_pagamento_fpd DATE,                     -- DT_PAGAMENTO da planilha
    ds_status_fatura_fpd VARCHAR(50),          -- DS_STATUS_FATURA da planilha
    data_importacao_fpd DATETIME,              -- Timestamp importação FPD
    
    -- Campos existentes
    codigo_pix TEXT,
    codigo_barras VARCHAR(100),
    arquivo_pdf VARCHAR(255),
    observacao TEXT,
    criado_em DATETIME AUTO_TIMESTAMP,
    atualizado_em DATETIME AUTO_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (contrato_id) REFERENCES crm_app_contratom10(id),
    UNIQUE KEY unique_contrato_fatura (contrato_id, numero_fatura)
);
```

### 2. ImportacaoFPD (Nova)

```sql
CREATE TABLE crm_app_importacaofpd (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    
    -- Identificadores
    nr_ordem VARCHAR(100) NOT NULL,                -- O.S para cruzamento
    id_contrato VARCHAR(100) NOT NULL,            -- ID_CONTRATO
    nr_fatura VARCHAR(100) NOT NULL,              -- NR_FATURA
    
    -- Datas
    dt_venc_orig DATE NOT NULL,                   -- Data vencimento original
    dt_pagamento DATE,                            -- Data pagamento
    nr_dias_atraso INT DEFAULT 0,                 -- Dias em atraso
    
    -- Status e Valores
    ds_status_fatura VARCHAR(50) NOT NULL,        -- PAGO, ABERTO, VENCIDO, etc
    vl_fatura DECIMAL(10,2) DEFAULT 0,            -- Valor fatura
    
    -- Relacionamento
    contrato_m10_id BIGINT,                       -- FK ContratoM10
    
    -- Controle
    importada_em DATETIME AUTO_TIMESTAMP,
    atualizada_em DATETIME AUTO_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Índices
    INDEX idx_nr_ordem (nr_ordem),
    INDEX idx_id_contrato (id_contrato),
    INDEX idx_ds_status_fatura (ds_status_fatura),
    INDEX idx_dt_venc_orig (dt_venc_orig),
    UNIQUE KEY unique_nr_ordem_nr_fatura (nr_ordem, nr_fatura),
    FOREIGN KEY (contrato_m10_id) REFERENCES crm_app_contratom10(id)
);
```

---

## Relacionamentos

```
ContratoM10 (1) ──────── (N) FaturaM10
    ↓
    └─────────────────(N) ImportacaoFPD
    
    
ContratoM10
├── id (PK)
├── numero_contrato
├── ordem_servico (unique) ← Chave para cruzamento
├── cliente_nome
└── ...

    ↓ (1-N)

FaturaM10
├── id (PK)
├── contrato_id (FK) ← referencia ContratoM10
├── numero_fatura (1-10)
├── status
├── valor
├── data_vencimento
├── data_pagamento
├── ... (campos originais)
├── id_contrato_fpd ← ID_CONTRATO (novo)
├── dt_pagamento_fpd ← DT_PAGAMENTO (novo)
├── ds_status_fatura_fpd ← DS_STATUS_FATURA (novo)
└── data_importacao_fpd ← Timestamp (novo)

    ↓ (1-N)

ImportacaoFPD (Histórico)
├── id (PK)
├── nr_ordem ← O.S (chave busca)
├── id_contrato ← ID_CONTRATO
├── nr_fatura ← NR_FATURA
├── dt_venc_orig
├── dt_pagamento
├── ds_status_fatura
├── vl_fatura
├── nr_dias_atraso
├── contrato_m10_id (FK) ← referencia ContratoM10
├── importada_em
└── atualizada_em
```

---

## Fluxo de Dados na Importação

```
Arquivo FPD (Excel/CSV)
├── NR_ORDEM = "OS-00123"
├── ID_CONTRATO = "ID-789"
├── NR_FATURA = "FT-001"
├── DT_VENC_ORIG = "2025-01-20"
├── DT_PAGAMENTO = "2025-01-15"
├── DS_STATUS_FATURA = "PAGO"
└── VL_FATURA = "150.00"
    
    ▼ [Busca ContratoM10]
    
ContratoM10.objects.get(ordem_servico="OS-00123")
    ✓ Encontrado: ID=1, numero_contrato="CONT-123456"
    
    ▼ [Atualiza/Cria FaturaM10]
    
FaturaM10 (numero_fatura=1)
├── id_contrato_fpd = "ID-789"
├── dt_pagamento_fpd = "2025-01-15"
├── ds_status_fatura_fpd = "PAGO"
├── data_importacao_fpd = "2025-12-31 10:30:00"
└── ... (outros campos)
    
    ▼ [Cria/Atualiza ImportacaoFPD]
    
ImportacaoFPD
├── nr_ordem = "OS-00123"
├── id_contrato = "ID-789"
├── nr_fatura = "FT-001"
├── dt_venc_orig = "2025-01-20"
├── dt_pagamento = "2025-01-15"
├── ds_status_fatura = "PAGO"
├── vl_fatura = "150.00"
├── contrato_m10_id = 1
└── importada_em = "2025-12-31 10:30:00"
```

---

## Queries Úteis

### 1. Buscar todos os dados FPD de uma O.S

```sql
SELECT 
    f.numero_fatura,
    f.id_contrato_fpd,
    f.dt_pagamento_fpd,
    f.ds_status_fatura_fpd,
    f.status,
    f.valor,
    f.data_vencimento,
    f.data_importacao_fpd,
    i.nr_fatura as nr_fatura_fpd,
    i.vl_fatura as vl_fatura_fpd,
    i.nr_dias_atraso,
    i.importada_em
FROM crm_app_faturam10 f
LEFT JOIN crm_app_importacaofpd i ON f.contrato_id = i.contrato_m10_id
WHERE f.contrato_id = (
    SELECT id FROM crm_app_contratom10 
    WHERE ordem_servico = 'OS-00123'
)
ORDER BY f.numero_fatura;
```

### 2. Estatísticas por Status FPD

```sql
SELECT 
    ds_status_fatura,
    COUNT(*) as total_faturas,
    SUM(vl_fatura) as valor_total,
    AVG(nr_dias_atraso) as media_dias_atraso
FROM crm_app_importacaofpd
GROUP BY ds_status_fatura
ORDER BY total_faturas DESC;
```

### 3. Faturas Pagas vs Não Pagas

```sql
SELECT 
    DATE(dt_venc_orig) as data_vencimento,
    SUM(CASE WHEN ds_status_fatura = 'PAGO' THEN vl_fatura ELSE 0 END) as valor_pago,
    SUM(CASE WHEN ds_status_fatura != 'PAGO' THEN vl_fatura ELSE 0 END) as valor_nao_pago,
    COUNT(CASE WHEN ds_status_fatura = 'PAGO' THEN 1 END) as qtd_pagas,
    COUNT(CASE WHEN ds_status_fatura != 'PAGO' THEN 1 END) as qtd_nao_pagas,
    ROUND(COUNT(CASE WHEN ds_status_fatura = 'PAGO' THEN 1 END) * 100.0 / COUNT(*), 2) as percentual_pago
FROM crm_app_importacaofpd
GROUP BY DATE(dt_venc_orig)
ORDER BY data_vencimento DESC;
```

### 4. Contratos com dados FPD duplicados

```sql
SELECT 
    nr_ordem,
    nr_fatura,
    COUNT(*) as repeticoes,
    GROUP_CONCAT(id) as ids
FROM crm_app_importacaofpd
GROUP BY nr_ordem, nr_fatura
HAVING COUNT(*) > 1
ORDER BY repeticoes DESC;
```

### 5. Faturas em atraso

```sql
SELECT 
    i.nr_ordem,
    c.numero_contrato,
    c.cliente_nome,
    i.nr_fatura,
    i.dt_venc_orig,
    i.nr_dias_atraso,
    i.vl_fatura,
    i.ds_status_fatura
FROM crm_app_importacaofpd i
JOIN crm_app_contratom10 c ON i.contrato_m10_id = c.id
WHERE i.nr_dias_atraso > 0
ORDER BY i.nr_dias_atraso DESC;
```

### 6. Importações mais recentes

```sql
SELECT 
    nr_ordem,
    id_contrato,
    nr_fatura,
    ds_status_fatura,
    vl_fatura,
    importada_em
FROM crm_app_importacaofpd
ORDER BY importada_em DESC
LIMIT 100;
```

### 7. Resumo mensal de FPD

```sql
SELECT 
    DATE_TRUNC('month', dt_venc_orig) as mes_vencimento,
    COUNT(*) as total_faturas,
    SUM(vl_fatura) as valor_total,
    SUM(CASE WHEN ds_status_fatura = 'PAGO' THEN vl_fatura ELSE 0 END) as valor_pago,
    COUNT(CASE WHEN ds_status_fatura = 'PAGO' THEN 1 END) as qtd_pagas,
    ROUND(COUNT(CASE WHEN ds_status_fatura = 'PAGO' THEN 1 END) * 100.0 / COUNT(*), 2) as taxa_fpd
FROM crm_app_importacaofpd
GROUP BY DATE_TRUNC('month', dt_venc_orig)
ORDER BY mes_vencimento DESC;
```

### 8. Contratos que ainda não têm dados FPD

```sql
SELECT 
    c.id,
    c.numero_contrato,
    c.cliente_nome,
    c.ordem_servico,
    c.data_instalacao
FROM crm_app_contratom10 c
LEFT JOIN crm_app_importacaofpd i ON i.contrato_m10_id = c.id
WHERE i.id IS NULL
ORDER BY c.data_instalacao DESC;
```

### 9. Discrepâncias entre FaturaM10 e ImportacaoFPD

```sql
SELECT 
    f.id as fatura_id,
    f.numero_fatura,
    f.id_contrato_fpd,
    f.dt_pagamento_fpd,
    f.ds_status_fatura_fpd,
    i.id_contrato,
    i.dt_pagamento,
    i.ds_status_fatura
FROM crm_app_faturam10 f
LEFT JOIN crm_app_importacaofpd i ON (
    f.id_contrato_fpd = i.id_contrato AND
    f.numero_fatura = 1
)
WHERE f.id_contrato_fpd IS NOT NULL
  AND (f.id_contrato_fpd != i.id_contrato 
       OR f.dt_pagamento_fpd != i.dt_pagamento
       OR f.ds_status_fatura_fpd != i.ds_status_fatura);
```

### 10. Taxa FPD por Safra

```sql
SELECT 
    s.mes_referencia,
    COUNT(DISTINCT i.nr_ordem) as total_contratos,
    SUM(CASE WHEN i.ds_status_fatura = 'PAGO' THEN 1 ELSE 0 END) as pagas,
    ROUND(SUM(CASE WHEN i.ds_status_fatura = 'PAGO' THEN 1 ELSE 0 END) * 100.0 / COUNT(DISTINCT i.nr_ordem), 2) as taxa_fpd_percentual,
    SUM(i.vl_fatura) as valor_total,
    SUM(CASE WHEN i.ds_status_fatura = 'PAGO' THEN i.vl_fatura ELSE 0 END) as valor_pago
FROM crm_app_safram10 s
LEFT JOIN crm_app_contratom10 c ON c.safra_id = s.id
LEFT JOIN crm_app_importacaofpd i ON i.contrato_m10_id = c.id
GROUP BY s.mes_referencia
ORDER BY s.mes_referencia DESC;
```

---

## Indices para Performance

### Índices Criados Automaticamente

```sql
-- Tabela ImportacaoFPD
CREATE INDEX idx_nr_ordem ON crm_app_importacaofpd(nr_ordem);
CREATE INDEX idx_id_contrato ON crm_app_importacaofpd(id_contrato);
CREATE INDEX idx_ds_status_fatura ON crm_app_importacaofpd(ds_status_fatura);
CREATE INDEX idx_dt_venc_orig ON crm_app_importacaofpd(dt_venc_orig);
CREATE UNIQUE INDEX unique_nr_ordem_nr_fatura ON crm_app_importacaofpd(nr_ordem, nr_fatura);
```

### Índices Recomendados Adicionais

```sql
-- Para buscas rápidas por O.S
CREATE INDEX idx_contratom10_ordem_servico ON crm_app_contratom10(ordem_servico);

-- Para filtros de data
CREATE INDEX idx_importacaofpd_importada_em ON crm_app_importacaofpd(importada_em);

-- Para buscas de contrato + fatura
CREATE INDEX idx_faturam10_contrato_numero ON crm_app_faturam10(contrato_id, numero_fatura);

-- Para buscas por status FPD na tabela FaturaM10
CREATE INDEX idx_faturam10_ds_status_fpd ON crm_app_faturam10(ds_status_fatura_fpd);
```

---

## Integridade de Dados

### Constraint: Chaves Estrangeiras

```sql
-- FaturaM10 → ContratoM10
ALTER TABLE crm_app_faturam10
ADD CONSTRAINT fk_faturam10_contrato
FOREIGN KEY (contrato_id) REFERENCES crm_app_contratom10(id)
ON DELETE CASCADE;

-- ImportacaoFPD → ContratoM10
ALTER TABLE crm_app_importacaofpd
ADD CONSTRAINT fk_importacaofpd_contrato
FOREIGN KEY (contrato_m10_id) REFERENCES crm_app_contratom10(id)
ON DELETE SET NULL;
```

### Check Constraints (Recomendado)

```sql
-- Validar que DT_PAGAMENTO >= DT_VENC_ORIG
ALTER TABLE crm_app_importacaofpd
ADD CONSTRAINT chk_datas_consistentes
CHECK (dt_pagamento IS NULL OR dt_pagamento >= dt_venc_orig);

-- Validar status válidos
ALTER TABLE crm_app_importacaofpd
ADD CONSTRAINT chk_status_valido
CHECK (ds_status_fatura IN ('PAGO', 'ABERTO', 'VENCIDO', 'AGUARDANDO', 'CANCELADO'));
```

---

## Tamanho das Tabelas

### Estimativa de Armazenamento

```sql
-- Verificar tamanho das tabelas
SELECT 
    table_name,
    ROUND(((data_length + index_length) / 1024 / 1024), 2) as size_mb
FROM information_schema.TABLES
WHERE table_schema = 'seu_banco'
AND table_name IN ('crm_app_faturam10', 'crm_app_importacaofpd', 'crm_app_contratom10')
ORDER BY size_mb DESC;
```

### Contagem de Registros

```sql
SELECT 
    'crm_app_faturam10' as tabela,
    COUNT(*) as registros
FROM crm_app_faturam10
UNION ALL
SELECT 
    'crm_app_importacaofpd' as tabela,
    COUNT(*) as registros
FROM crm_app_importacaofpd
UNION ALL
SELECT 
    'crm_app_contratom10' as tabela,
    COUNT(*) as registros
FROM crm_app_contratom10;
```

---

## Backup e Recuperação

### Backup de ImportacaoFPD

```bash
# MySQL
mysqldump -u user -p database crm_app_importacaofpd > backup_importacao_fpd.sql

# PostgreSQL
pg_dump -U user -d database -t crm_app_importacaofpd > backup_importacao_fpd.sql
```

### Restaurar Dados

```bash
# MySQL
mysql -u user -p database < backup_importacao_fpd.sql

# PostgreSQL
psql -U user -d database < backup_importacao_fpd.sql
```

---

## Monitoramento

### Queries Lentas

```sql
-- Listar queries que levam mais de X segundos
SELECT * FROM mysql.slow_log
WHERE query_time > 1
ORDER BY start_time DESC
LIMIT 10;
```

### Verificar Locks

```sql
-- MySQL
SHOW OPEN TABLES WHERE In_use > 0;

-- PostgreSQL
SELECT * FROM pg_locks WHERE NOT granted;
```

---

## Manutenção

### Desfragmentação (MySQL)

```sql
OPTIMIZE TABLE crm_app_importacaofpd;
OPTIMIZE TABLE crm_app_faturam10;
```

### Análise de Tabelas (PostgreSQL)

```sql
ANALYZE crm_app_importacaofpd;
ANALYZE crm_app_faturam10;
```

### Remover Duplicatas

```sql
-- Encontrar duplicatas
SELECT nr_ordem, nr_fatura, COUNT(*) 
FROM crm_app_importacaofpd
GROUP BY nr_ordem, nr_fatura
HAVING COUNT(*) > 1;

-- Manter apenas a importação mais recente
DELETE FROM crm_app_importacaofpd i1
WHERE i1.id NOT IN (
    SELECT MAX(i2.id)
    FROM crm_app_importacaofpd i2
    GROUP BY i2.nr_ordem, i2.nr_fatura
);
```
