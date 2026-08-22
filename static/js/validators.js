// static/js/validators.js - Validadores de CPF e CNPJ

/**
 * Valida um CPF seguindo o algoritmo oficial.
 * @param {string} cpf - CPF com ou sem formatação
 * @returns {object} { valido: boolean, limpo: string, erro: string }
 */
function validarCPF(cpf) {
    // Remove caracteres não numéricos
    if (!cpf) {
        return { valido: false, limpo: '', erro: 'CPF vazio ou indefinido.' };
    }
    const cpfLimpo = cpf.replace(/\D/g, '');
    
    // Verifica comprimento
    if (cpfLimpo.length !== 11) {
        return { valido: false, limpo: '', erro: 'CPF deve ter 11 dígitos.' };
    }
    
    // Verifica se todos os dígitos são iguais
    if (/^(\d)\1{10}$/.test(cpfLimpo)) {
        return { valido: false, limpo: '', erro: 'CPF inválido (dígitos repetidos).' };
    }
    
    // Calcula primeiro dígito verificador
    let soma = 0;
    for (let i = 0; i < 9; i++) {
        soma += parseInt(cpfLimpo[i]) * (10 - i);
    }
    let digito1 = 11 - (soma % 11);
    digito1 = digito1 > 9 ? 0 : digito1;
    
    if (parseInt(cpfLimpo[9]) !== digito1) {
        return { valido: false, limpo: '', erro: 'CPF inválido (primeiro dígito verificador incorreto).' };
    }
    
    // Calcula segundo dígito verificador
    soma = 0;
    for (let i = 0; i < 10; i++) {
        soma += parseInt(cpfLimpo[i]) * (11 - i);
    }
    let digito2 = 11 - (soma % 11);
    digito2 = digito2 > 9 ? 0 : digito2;
    
    if (parseInt(cpfLimpo[10]) !== digito2) {
        return { valido: false, limpo: '', erro: 'CPF inválido (segundo dígito verificador incorreto).' };
    }
    
    return { valido: true, limpo: cpfLimpo, erro: '' };
}

/**
 * Valida um CNPJ seguindo o algoritmo oficial.
 * @param {string} cnpj - CNPJ com ou sem formatação
 * @returns {object} { valido: boolean, limpo: string, erro: string }
 */
function validarCNPJ(cnpj) {
    // Remove caracteres não numéricos
    if (!cnpj) {
        return { valido: false, limpo: '', erro: 'CNPJ vazio ou indefinido.' };
    }
    const cnpjLimpo = cnpj.replace(/\D/g, '');
    
    // Verifica comprimento
    if (cnpjLimpo.length !== 14) {
        return { valido: false, limpo: '', erro: 'CNPJ deve ter 14 dígitos.' };
    }
    
    // Verifica se todos os dígitos são iguais
    if (/^(\d)\1{13}$/.test(cnpjLimpo)) {
        return { valido: false, limpo: '', erro: 'CNPJ inválido (dígitos repetidos).' };
    }
    
    // Calcula primeiro dígito verificador
    const mult1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    let soma = 0;
    for (let i = 0; i < 12; i++) {
        soma += parseInt(cnpjLimpo[i]) * mult1[i];
    }
    let digito1 = 11 - (soma % 11);
    digito1 = digito1 > 9 ? 0 : digito1;
    
    if (parseInt(cnpjLimpo[12]) !== digito1) {
        return { valido: false, limpo: '', erro: 'CNPJ inválido (primeiro dígito verificador incorreto).' };
    }
    
    // Calcula segundo dígito verificador
    const mult2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    soma = 0;
    for (let i = 0; i < 13; i++) {
        soma += parseInt(cnpjLimpo[i]) * mult2[i];
    }
    let digito2 = 11 - (soma % 11);
    digito2 = digito2 > 9 ? 0 : digito2;
    
    if (parseInt(cnpjLimpo[13]) !== digito2) {
        return { valido: false, limpo: '', erro: 'CNPJ inválido (segundo dígito verificador incorreto).' };
    }
    
    return { valido: true, limpo: cnpjLimpo, erro: '' };
}

/**
 * Valida CPF ou CNPJ automaticamente detectando o tipo.
 * @param {string} documento - CPF ou CNPJ com ou sem formatação
 * @returns {object} { valido: boolean, limpo: string, tipo: string, erro: string }
 */
function validarCPFouCNPJ(documento) {
    if (!documento) {
        return {
            valido: false,
            limpo: '',
            tipo: '',
            erro: 'Documento vazio ou indefinido.'
        };
    }
    const doc = documento.replace(/\D/g, '');
    
    if (doc.length === 11) {
        const resultado = validarCPF(doc);
        return { ...resultado, tipo: 'CPF' };
    } else if (doc.length === 14) {
        const resultado = validarCNPJ(doc);
        return { ...resultado, tipo: 'CNPJ' };
    } else {
        return { 
            valido: false, 
            limpo: '', 
            tipo: '', 
            erro: 'Documento inválido. Deve ser CPF (11 dígitos) ou CNPJ (14 dígitos).' 
        };
    }
}

/**
 * Formata CPF: 000.000.000-00
 */
function formatarCPF(cpf) {
    if (!cpf) return '';
    const limpo = cpf.replace(/\D/g, '');
    if (limpo.length !== 11) return cpf;
    return limpo.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4');
}

/**
 * Formata CNPJ: 00.000.000/0000-00
 */
function formatarCNPJ(cnpj) {
    if (!cnpj) return '';
    const limpo = cnpj.replace(/\D/g, '');
    if (limpo.length !== 14) return cnpj;
    return limpo.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
}

/**
 * Aplica validação em tempo real ao input de CPF
 */
function aplicarValidadorCPFEmTempo(selectorInput, selectorFeedback) {
    const input = document.querySelector(selectorInput);
    const feedback = document.querySelector(selectorFeedback);
    
    if (!input) return;
    
    input.addEventListener('blur', function() {
        const valor = typeof this.value === 'string' ? this.value : '';
        const resultado = validarCPF(valor);
        
        if (!valor) {
            input.classList.remove('is-valid', 'is-invalid');
            feedback?.classList.remove('text-success', 'text-danger');
            feedback && (feedback.textContent = '');
        } else if (resultado.valido) {
            input.classList.add('is-valid');
            input.classList.remove('is-invalid');
            feedback?.classList.add('text-success');
            feedback?.classList.remove('text-danger');
            feedback && (feedback.textContent = 'CPF válido ✓');
        } else {
            input.classList.add('is-invalid');
            input.classList.remove('is-valid');
            feedback?.classList.add('text-danger');
            feedback?.classList.remove('text-success');
            feedback && (feedback.textContent = resultado.erro);
        }
    });
}

/**
 * Aplica validação em tempo real ao input de CNPJ
 */
function aplicarValidadorCNPJEmTempo(selectorInput, selectorFeedback) {
    const input = document.querySelector(selectorInput);
    const feedback = document.querySelector(selectorFeedback);
    
    if (!input) return;
    
    input.addEventListener('blur', function() {
        const valor = typeof this.value === 'string' ? this.value : '';
        const resultado = validarCNPJ(valor);
        
        if (!valor) {
            input.classList.remove('is-valid', 'is-invalid');
            feedback?.classList.remove('text-success', 'text-danger');
            feedback && (feedback.textContent = '');
        } else if (resultado.valido) {
            input.classList.add('is-valid');
            input.classList.remove('is-invalid');
            feedback?.classList.add('text-success');
            feedback?.classList.remove('text-danger');
            feedback && (feedback.textContent = 'CNPJ válido ✓');
        } else {
            input.classList.add('is-invalid');
            input.classList.remove('is-valid');
            feedback?.classList.add('text-danger');
            feedback?.classList.remove('text-success');
            feedback && (feedback.textContent = resultado.erro);
        }
    });
}
