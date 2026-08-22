# core/validators.py - Validadores de CPF e CNPJ

import re
from django.core.exceptions import ValidationError

def validar_cpf(cpf_str):
    """
    Valida um CPF seguindo o algoritmo oficial.
    Aceita: 000.000.000-00 ou 00000000000
    Retorna: CPF limpo (apenas dígitos) ou lança ValidationError
    """
    if not cpf_str:
        raise ValidationError("CPF é obrigatório.")
    
    # Remove caracteres não numéricos
    cpf = re.sub(r'\D', '', str(cpf_str))
    
    # Verifica comprimento
    if len(cpf) != 11:
        raise ValidationError("CPF deve ter 11 dígitos.")
    
    # Verifica se todos os dígitos são iguais (inválido)
    if cpf == cpf[0] * 11:
        raise ValidationError("CPF inválido (dígitos repetidos).")
    
    # Calcula primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digito1 = 11 - (soma % 11)
    digito1 = 0 if digito1 > 9 else digito1
    
    if int(cpf[9]) != digito1:
        raise ValidationError("CPF inválido (primeiro dígito verificador incorreto).")
    
    # Calcula segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digito2 = 11 - (soma % 11)
    digito2 = 0 if digito2 > 9 else digito2
    
    if int(cpf[10]) != digito2:
        raise ValidationError("CPF inválido (segundo dígito verificador incorreto).")
    
    return cpf


def validar_cnpj(cnpj_str):
    """
    Valida um CNPJ seguindo o algoritmo oficial.
    Aceita: 00.000.000/0000-00 ou 00000000000000
    Retorna: CNPJ limpo (apenas dígitos) ou lança ValidationError
    """
    if not cnpj_str:
        raise ValidationError("CNPJ é obrigatório.")
    
    # Remove caracteres não numéricos
    cnpj = re.sub(r'\D', '', str(cnpj_str))
    
    # Verifica comprimento
    if len(cnpj) != 14:
        raise ValidationError("CNPJ deve ter 14 dígitos.")
    
    # Verifica se todos os dígitos são iguais (inválido)
    if cnpj == cnpj[0] * 14:
        raise ValidationError("CNPJ inválido (dígitos repetidos).")
    
    # Calcula primeiro dígito verificador
    mult = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(cnpj[i]) * mult[i] for i in range(12))
    digito1 = 11 - (soma % 11)
    digito1 = 0 if digito1 > 9 else digito1
    
    if int(cnpj[12]) != digito1:
        raise ValidationError("CNPJ inválido (primeiro dígito verificador incorreto).")
    
    # Calcula segundo dígito verificador
    mult = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(cnpj[i]) * mult[i] for i in range(13))
    digito2 = 11 - (soma % 11)
    digito2 = 0 if digito2 > 9 else digito2
    
    if int(cnpj[13]) != digito2:
        raise ValidationError("CNPJ inválido (segundo dígito verificador incorreto).")
    
    return cnpj


def validar_cpf_ou_cnpj(doc_str):
    """
    Valida CPF ou CNPJ automaticamente detectando o tipo.
    Retorna: (doc_limpo, tipo) onde tipo é 'CPF' ou 'CNPJ', ou lança ValidationError
    """
    if not doc_str:
        raise ValidationError("CPF ou CNPJ é obrigatório.")
    
    doc = re.sub(r'\D', '', str(doc_str))
    
    if len(doc) == 11:
        return validar_cpf(doc), 'CPF'
    elif len(doc) == 14:
        return validar_cnpj(doc), 'CNPJ'
    else:
        raise ValidationError("Documento inválido. Deve ser CPF (11 dígitos) ou CNPJ (14 dígitos).")
