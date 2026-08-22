"""
Script para limpar tabela ImportacaoFPD e validar dados
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ImportacaoFPD, LogImportacaoFPD
from django.utils import timezone

def limpar_importacao_fpd():
    """Limpa completamente a tabela ImportacaoFPD"""
    
    print("🗑️  LIMPEZA DE IMPORTAÇÕES FPD")
    print("=" * 80)
    
    # Contar antes
    antes = ImportacaoFPD.objects.count()
    print(f"\n📊 Registros antes da limpeza: {antes}")
    
    if antes == 0:
        print("   └─ Tabela já está vazia! ✅")
        return
    
    # Confirmar
    print(f"\n⚠️  Você vai DELETAR {antes} registros da tabela ImportacaoFPD")
    resposta = input("   Continuar? (s/n): ").strip().lower()
    
    if resposta != 's':
        print("   └─ Operação cancelada ❌")
        return
    
    # Deletar
    print("\n   Deletando registros...")
    deletados, _ = ImportacaoFPD.objects.all().delete()
    
    print(f"   └─ ✅ {deletados} registros deletados")
    
    # Confirmar
    depois = ImportacaoFPD.objects.count()
    print(f"\n✅ Registros após limpeza: {depois}")
    
    if depois == 0:
        print("   └─ Tabela limpa com sucesso! ✅")
    else:
        print("   └─ ⚠️  Ainda há registros na tabela")


def listar_duplicatas():
    """Identifica possíveis duplicatas (mesmo O.S + fatura)"""
    
    print("\n\n🔍 VERIFICANDO DUPLICATAS")
    print("=" * 80)
    
    from django.db.models import Count
    
    # Agrupar por nr_ordem + nr_fatura e contar
    duplicatas = (
        ImportacaoFPD.objects.values('nr_ordem', 'nr_fatura')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )
    
    if not duplicatas.exists():
        print("\n✅ Nenhuma duplicata encontrada!")
        return
    
    print(f"\n⚠️  Encontradas {len(list(duplicatas))} duplicatas:\n")
    
    for dup in duplicatas:
        nr_ordem = dup['nr_ordem']
        nr_fatura = dup['nr_fatura']
        count = dup['count']
        
        registros = ImportacaoFPD.objects.filter(
            nr_ordem=nr_ordem,
            nr_fatura=nr_fatura
        ).order_by('importada_em')
        
        print(f"   O.S {nr_ordem} - Fatura {nr_fatura} ({count} vezes)")
        
        for i, reg in enumerate(registros, 1):
            contrato_str = f"M10: {reg.contrato_m10.id}" if reg.contrato_m10 else "Sem M10"
            print(f"      {i}. Valor: R$ {reg.vl_fatura} | {contrato_str} | Importada: {reg.importada_em.strftime('%d/%m/%Y %H:%M')}")
        
        print()


def remover_duplicatas():
    """Remove registros duplicados, mantendo o mais recente"""
    
    print("\n\n🧹 REMOVENDO DUPLICATAS")
    print("=" * 80)
    
    from django.db.models import Count
    
    # Agrupar por nr_ordem + nr_fatura e contar
    duplicatas = (
        ImportacaoFPD.objects.values('nr_ordem', 'nr_fatura')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )
    
    if not duplicatas.exists():
        print("\n✅ Nenhuma duplicata para remover!")
        return
    
    total_removidos = 0
    
    for dup in duplicatas:
        nr_ordem = dup['nr_ordem']
        nr_fatura = dup['nr_fatura']
        
        # Pega todos os registros duplicados
        registros = ImportacaoFPD.objects.filter(
            nr_ordem=nr_ordem,
            nr_fatura=nr_fatura
        ).order_by('-importada_em')  # Mais recente primeiro
        
        # Mantém o primeiro (mais recente) e deleta o resto
        manter = registros.first()
        remover = registros[1:]
        
        for reg in remover:
            print(f"   🗑️  Removendo: O.S {nr_ordem} - Fatura {nr_fatura} (ID: {reg.id})")
            reg.delete()
            total_removidos += 1
    
    print(f"\n✅ Total de registros duplicados removidos: {total_removidos}")


def validar_integridade():
    """Valida integridade dos dados importados"""
    
    print("\n\n✔️  VALIDAÇÃO DE INTEGRIDADE")
    print("=" * 80)
    
    total = ImportacaoFPD.objects.count()
    print(f"\n📊 Total de registros: {total}")
    
    if total == 0:
        print("   └─ Tabela vazia!")
        return
    
    # Verificar campos obrigatórios
    print("\n🔍 Verificando campos obrigatórios:")
    
    sem_os = ImportacaoFPD.objects.filter(nr_ordem__isnull=True).count()
    print(f"   Sem NR_ORDEM: {sem_os} ❌" if sem_os > 0 else "   Sem NR_ORDEM: 0 ✅")
    
    sem_fatura = ImportacaoFPD.objects.filter(nr_fatura__isnull=True).count()
    print(f"   Sem NR_FATURA: {sem_fatura} ❌" if sem_fatura > 0 else "   Sem NR_FATURA: 0 ✅")
    
    sem_valor = ImportacaoFPD.objects.filter(vl_fatura__isnull=True).count()
    print(f"   Sem VL_FATURA: {sem_valor} ❌" if sem_valor > 0 else "   Sem VL_FATURA: 0 ✅")
    
    sem_status = ImportacaoFPD.objects.filter(ds_status_fatura__isnull=True).count()
    print(f"   Sem STATUS: {sem_status} ❌" if sem_status > 0 else "   Sem STATUS: 0 ✅")
    
    # Verificar duplicatas
    from django.db.models import Count
    duplicatas = (
        ImportacaoFPD.objects.values('nr_ordem', 'nr_fatura')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
        .count()
    )
    print(f"   Duplicatas: {duplicatas} ❌" if duplicatas > 0 else "   Duplicatas: 0 ✅")
    
    # Verificar valores
    print("\n💰 Análise de valores:")
    valor_total = ImportacaoFPD.objects.aggregate(total=models.Sum('vl_fatura'))['total'] or 0
    valor_minimo = ImportacaoFPD.objects.aggregate(minimo=models.Min('vl_fatura'))['minimo'] or 0
    valor_maximo = ImportacaoFPD.objects.aggregate(maximo=models.Max('vl_fatura'))['maximo'] or 0
    
    print(f"   Valor total: R$ {valor_total:,.2f}".replace(',', '.'))
    print(f"   Valor mínimo: R$ {valor_minimo:,.2f}".replace(',', '.'))
    print(f"   Valor máximo: R$ {valor_maximo:,.2f}".replace(',', '.'))
    
    # Verificar vinculações
    print("\n🔗 Vinculações com ContratoM10:")
    com_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=False).count()
    sem_vinculo = ImportacaoFPD.objects.filter(contrato_m10__isnull=True).count()
    
    print(f"   Com vínculo: {com_vinculo}")
    print(f"   Sem vínculo: {sem_vinculo}")
    
    # Status
    print("\n📋 Distribuição por status:")
    from django.db.models import Count
    status_dist = (
        ImportacaoFPD.objects.values('ds_status_fatura')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    
    for status_info in status_dist:
        print(f"   {status_info['ds_status_fatura']}: {status_info['count']}")
    
    print("\n" + "=" * 80)
    print("✅ Validação concluída!")


if __name__ == '__main__':
    from django.db import models
    
    print("\n📚 UTILITÁRIOS DE LIMPEZA E VALIDAÇÃO - ImportacaoFPD")
    print("=" * 80)
    
    while True:
        print("\nOpções:")
        print("  1. Limpar toda a tabela ImportacaoFPD")
        print("  2. Listar duplicatas encontradas")
        print("  3. Remover registros duplicados")
        print("  4. Validar integridade dos dados")
        print("  5. Ver todas as estatísticas")
        print("  0. Sair")
        
        opcao = input("\nEscolha uma opção (0-5): ").strip()
        
        if opcao == '0':
            print("\n👋 Até logo!")
            break
        elif opcao == '1':
            limpar_importacao_fpd()
        elif opcao == '2':
            listar_duplicatas()
        elif opcao == '3':
            remover_duplicatas()
        elif opcao == '4':
            validar_integridade()
        elif opcao == '5':
            listar_duplicatas()
            validar_integridade()
        else:
            print("❌ Opção inválida!")
        
        print()
