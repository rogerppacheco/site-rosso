// static/js/auth.js - VERSÃO CORRIGIDA E OTIMIZADA

const API_URL = '';

// --- HELPER CSRF ---
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// --- LOGOUT POR INATIVIDADE ---
let inactivityTimer;

function logoutOnInactivity() {
    // Só faz logout se não estiver no meio da troca de senha
    if(localStorage.getItem('trocaPendente') !== 'true') {
        alert('Sua sessão expirou por inatividade.');
        logout(); 
    }
}

function resetInactivityTimer() {
    clearTimeout(inactivityTimer);
    // 30 minutos de inatividade total para logout
    inactivityTimer = setTimeout(logoutOnInactivity, 30 * 60 * 1000); 
}

// --- AUTO REFRESH DO TOKEN (EVITA O ERRO AO CARREGAR VENDAS) ---
function iniciarAutoRefresh() {
    setInterval(async () => {
        const token = localStorage.getItem('accessToken');
        if (!token) return;

        const decoded = jwt_decode(token);
        if (!decoded || !decoded.exp) return;

        const now = Date.now() / 1000;
        const tempoRestante = decoded.exp - now;

        // Se faltar menos de 5 minutos para expirar e o usuário tiver token de refresh
        if (tempoRestante < 300 && tempoRestante > 0) {
            console.log("Token próximo de expirar. Renovando...");
            await refreshAccessToken();
        }
    }, 60 * 1000); // Verifica a cada 1 minuto
}

async function refreshAccessToken() {
    const refresh = localStorage.getItem('refreshToken');
    if (!refresh) {
        console.warn("Refresh token não encontrado");
        return false;
    }

    try {
        const response = await fetch(`${API_URL}/api/auth/token/refresh/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh: refresh })
        });

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('accessToken', data.access);
            console.log("Token renovado com sucesso.");
            return true;
        } else {
            // Token de refresh expirado ou inválido - fazer logout
            console.error("Refresh token expirado ou inválido (401). Fazendo logout...");
            if (response.status === 401) {
                // Limpar storage e redirecionar para login
                localStorage.removeItem('accessToken');
                localStorage.removeItem('refreshToken');
                localStorage.removeItem('userProfile');
                // Não redireciona aqui - deixa a página fazer
            }
            return false;
        }
    } catch (error) {
        console.error("Erro no refresh token:", error);
        return false;
    }
}

// Ativa os listeners de atividade
if (localStorage.getItem('accessToken')) {
    const events = ['load', 'mousemove', 'mousedown', 'keypress', 'touchmove', 'scroll'];
    events.forEach(event => document.addEventListener(event, resetInactivityTimer, true));
    resetInactivityTimer();
    iniciarAutoRefresh(); // Inicia o monitoramento do token
}

// --- CLIENTE API COMPLETO (GET, POST, PATCH, DELETE) ---
const apiClient = {
    get: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        if (!response.ok) {
            // Se der 401 (Não autorizado), pode ser token expirado no meio da ação
            if (response.status === 401) {
                console.warn("Erro 401 detectado. Tentando renovar token...");
                // Aqui poderia ter uma lógica de retry, mas o AutoRefresh deve prevenir isso.
            }
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    post: async function(url, data) {
        const token = localStorage.getItem('accessToken');
        const csrftoken = getCookie('csrftoken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            mode: 'same-origin',
            body: JSON.stringify(data),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    patch: async function(url, data) {
        const token = localStorage.getItem('accessToken');
        const csrftoken = getCookie('csrftoken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            mode: 'same-origin',
            body: JSON.stringify(data),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    delete: async function(url) {
        const token = localStorage.getItem('accessToken');
        const csrftoken = getCookie('csrftoken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'DELETE',
            headers: { 
                'Authorization': `Bearer ${token}`,
                'X-CSRFToken': csrftoken
            },
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        return { data: null };
    }
};

// --- FUNÇÃO PARA FORÇAR O MODAL DE TROCA ---
function forcarModalTrocaSenha() {
    const modal = document.getElementById('modalTrocaSenha');
    const loginOverlay = document.getElementById('loginModalOverlay');
    
    if(loginOverlay) loginOverlay.style.display = 'none'; 
    
    if (modal) {
        modal.style.display = 'flex';
        // Limpa campos
        const s1 = document.getElementById('novaSenhaInput');
        const s2 = document.getElementById('confirmaSenhaInput');
        if(s1) s1.value = '';
        if(s2) s2.value = '';
    } else {
        console.error("Modal de troca não encontrado. Bloqueando acesso.");
        // Se estiver em uma página interna sem o modal, redireciona para a home onde o modal existe
        if(window.location.pathname !== '/') {
            alert("Troca de senha obrigatória. Redirecionando para a tela inicial.");
            window.location.href = '/';
        }
    }
}

document.addEventListener('DOMContentLoaded', function() {
    
    // --- RESTAURAR EMAIL SALVO ---
    const savedEmail = localStorage.getItem('savedUserEmail');
    if (savedEmail) {
        const userInput = document.getElementById('username');
        if (userInput) userInput.value = savedEmail;
    }

    // --- VERIFICAÇÃO DE SEGURANÇA AO CARREGAR A PÁGINA ---
    if (localStorage.getItem('accessToken') && localStorage.getItem('trocaPendente') === 'true') {
        forcarModalTrocaSenha();
    }

    // --- ELEMENTOS DO DOM ---
    const loginModal = document.getElementById('loginModalOverlay');
    const areaInternaButton = document.querySelector('a.nav-button[href="/area-interna/"]');
    const btnOpenLogin = document.getElementById('btnOpenLogin');
    const loginForm = document.getElementById('loginForm');
    const cancelarLogin = document.getElementById('btnCancelLogin');

    // --- 1. MODAL ESQUECI A SENHA ---
    const linkEsqueci = document.getElementById('linkEsqueciSenha');
    if(linkEsqueci) {
        linkEsqueci.addEventListener('click', function(e) {
            e.preventDefault();
            if(loginModal) loginModal.style.display = 'none';
            const modalEsqueci = document.getElementById('modalEsqueciSenha');
            if(modalEsqueci) modalEsqueci.style.display = 'flex';
        });
    }

    const formEsqueci = document.getElementById('formEsqueciSenha');
    if(formEsqueci) {
        formEsqueci.addEventListener('submit', async function(e) {
            e.preventDefault();
            const btn = formEsqueci.querySelector('button[type="submit"]');
            const originalText = btn.innerText;
            btn.innerText = 'Enviando...'; btn.disabled = true;

            const cpf = document.getElementById('esqueciCpf').value;
            const zap = document.getElementById('esqueciZap').value;
            const csrftoken = getCookie('csrftoken');

            try {
                const resp = await fetch(`${API_URL}/api/usuarios/esqueci-senha/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
                    mode: 'same-origin',
                    body: JSON.stringify({ cpf: cpf, whatsapp: zap })
                });
                
                const data = await resp.json();
                if(resp.ok) {
                    alert('Sucesso! ' + data.detail);
                    document.getElementById('modalEsqueciSenha').style.display = 'none';
                    if(loginModal) loginModal.style.display = 'flex';
                } else {
                    alert('Erro: ' + (data.detail || 'Falha ao recuperar senha.'));
                }
            } catch (err) {
                alert('Erro de conexão ou servidor.');
            } finally {
                btn.innerText = originalText; btn.disabled = false;
            }
        });
    }

    // --- 2. MODAL TROCA DE SENHA ---
    const formTroca = document.getElementById('formTrocaSenha');
    if(formTroca) {
        formTroca.addEventListener('submit', async function(e) {
            e.preventDefault();
            const nova = document.getElementById('novaSenhaInput').value;
            const conf = document.getElementById('confirmaSenhaInput').value;

            if(nova !== conf) {
                alert('As senhas não conferem!'); return;
            }

            try {
                const res = await apiClient.post('/api/usuarios/definir-senha/', {
                    nova_senha: nova,
                    confirmacao_senha: conf
                });
                const data = res.data || res;
                
                // Atualiza token se o backend retornar (evita modal voltar)
                if (data.access) {
                    localStorage.setItem('accessToken', data.access);
                    if (data.refresh) localStorage.setItem('refreshToken', data.refresh);
                }
                localStorage.removeItem('trocaPendente');
                
                alert('Senha alterada com sucesso!');
                document.getElementById('modalTrocaSenha').style.display = 'none';
                window.location.href = '/area-interna/';
            } catch (err) {
                alert('Erro ao salvar senha: ' + err.message);
            }
        });
    }

    // --- 3. LOGIN ---
    if (loginModal && loginForm) {
        const openModal = function(event) {
            event.preventDefault();
            if (localStorage.getItem('accessToken')) {
                // SEGURANÇA: Verifica se tem troca pendente
                if (localStorage.getItem('trocaPendente') === 'true') {
                    forcarModalTrocaSenha();
                    return; 
                }
                window.location.href = '/area-interna/';
            } else {
                loginModal.style.display = 'flex';
                const userInput = document.getElementById('username');
                if(userInput) {
                    userInput.focus();
                    // Se já tiver email salvo, preenche
                    const saved = localStorage.getItem('savedUserEmail');
                    if(saved) userInput.value = saved;
                }
            }
        };

        if (areaInternaButton) areaInternaButton.addEventListener('click', openModal);
        if (btnOpenLogin) btnOpenLogin.addEventListener('click', openModal);
        if (cancelarLogin) cancelarLogin.addEventListener('click', () => loginModal.style.display = 'none');
        
        loginModal.addEventListener('click', (e) => {
            if(e.target === loginModal) loginModal.style.display = 'none';
        });

        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const submitBtn = loginForm.querySelector('button[type="submit"]');
            const originalText = submitBtn ? submitBtn.innerText : 'Entrar';
            if(submitBtn) { submitBtn.innerText = 'Entrando...'; submitBtn.disabled = true; }
            try {
                const u = document.getElementById('username').value;
                const p = document.getElementById('password').value;
                await login(u, p);
            } finally {
                if(submitBtn) { submitBtn.innerText = originalText; submitBtn.disabled = false; }
            }
        });
    }

    document.querySelectorAll('.logout-button').forEach(btn => {
        btn.addEventListener('click', (e) => { e.preventDefault(); logout(); });
    });
});

async function login(username, password) {
    const csrftoken = getCookie('csrftoken');
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);
    try {
        const response = await fetch(`${API_URL}/api/auth/login/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            mode: 'same-origin',
            body: JSON.stringify({ username, password }),
            credentials: 'include',
            signal: controller.signal,
        });

        if (!response.ok) {
            let msg = 'Usuário ou senha inválidos.';
            try {
                const errorData = await response.json();
                msg = errorData.detail || msg;
            } catch (_) { /* corpo não-JSON */ }
            alert('Falha na autenticação: ' + msg);
            throw new Error('Falha na autenticação');
        }

        const data = await response.json();
        const accessToken = data.access || data.token; 
        
        if (accessToken) {
            localStorage.setItem('accessToken', accessToken);
            if(data.refresh) localStorage.setItem('refreshToken', data.refresh);

            // --- SALVAR EMAIL (FIX) ---
            localStorage.setItem('savedUserEmail', username);

            const decodedToken = jwt_decode(accessToken);
            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
            }
            
            // --- TRAVA DE SEGURANÇA ---
            if (data.obriga_troca_senha === true) {
                localStorage.setItem('trocaPendente', 'true');
                const loginM = document.getElementById('loginModalOverlay');
                if(loginM) loginM.style.display = 'none';
                forcarModalTrocaSenha();
                return false; 
            } else {
                localStorage.removeItem('trocaPendente');
            }

            window.location.href = '/area-interna/';
            return true;
        } else {
            alert('Erro: O servidor não retornou um token válido.');
            return false;
        }
    } catch (error) {
        if (error && error.name === 'AbortError') {
            alert('O servidor demorou demais para responder. Tente novamente em alguns segundos ou avise o suporte.');
        } else {
            console.error('Erro geral durante o login:', error);
        }
        return false;
    } finally {
        clearTimeout(timeoutId);
    }
}

function logout() {
    // NÃO REMOVER 'savedUserEmail'
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('userProfile');
    localStorage.removeItem('trocaPendente');
    clearTimeout(inactivityTimer); 
    window.location.href = '/';
}

function jwt_decode(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}

// ===== MONITORAMENTO VISUAL DE TOKEN =====
let tokenMonitorInterval;

function iniciarMonitoramentoToken() {
    const indicator = document.getElementById('token-indicator');
    const timeDisplay = document.getElementById('token-time');
    
    if (!indicator || !timeDisplay) {
        console.warn('Indicador de token não encontrado na página');
        return;
    }
    
    const icon = indicator.querySelector('i');
    
    // Elementos do modal (se existir)
    const indicatorModal = document.getElementById('token-indicator-modal');
    const timeDisplayModal = document.getElementById('token-time-modal');
    const iconModal = indicatorModal ? indicatorModal.querySelector('i') : null;

    function atualizarDisplay() {
        const token = localStorage.getItem('accessToken');
        if (!token) {
            timeDisplay.textContent = 'Sem token';
            indicator.style.background = '#ffebee';
            icon.style.color = '#d32f2f';
            icon.className = 'bi bi-shield-x';
            if (indicatorModal) {
                timeDisplayModal.textContent = 'Sem token';
                indicatorModal.style.background = '#ffebee';
                iconModal.style.color = '#d32f2f';
                iconModal.className = 'bi bi-shield-x';
            }
            
            // Logout automático se não tiver token
            setTimeout(() => {
                alert('Sessão expirada. Faça login novamente.');
                logout();
            }, 2000);
            return;
        }

        try {
            const payload = jwt_decode(token);
            if (!payload || !payload.exp) {
                throw new Error('Token inválido');
            }
            
            const exp = payload.exp;
            const now = Math.floor(Date.now() / 1000);
            const tempoRestante = exp - now;

            if (tempoRestante <= 0) {
                timeDisplay.textContent = 'Expirado';
                indicator.style.background = '#ffebee';
                icon.style.color = '#d32f2f';
                icon.className = 'bi bi-shield-x';
                if (indicatorModal) {
                    timeDisplayModal.textContent = 'Expirado';
                    indicatorModal.style.background = '#ffebee';
                    iconModal.style.color = '#d32f2f';
                    iconModal.className = 'bi bi-shield-x';
                }
                
                // Logout automático quando expirar
                clearInterval(tokenMonitorInterval);
                alert('Sua sessão expirou. Você será redirecionado para o login.');
                logout();
                return;
            }

            const minutos = Math.floor(tempoRestante / 60);
            const segundos = tempoRestante % 60;
            const tempoFormatado = `${minutos}:${segundos.toString().padStart(2, '0')}`;
            timeDisplay.textContent = tempoFormatado;
            if (indicatorModal) timeDisplayModal.textContent = tempoFormatado;

            // Crítico quando faltar menos de 2 minutos
            if (tempoRestante < 120) {
                indicator.style.background = '#ffebee';
                icon.style.color = '#d32f2f';
                icon.className = 'bi bi-shield-exclamation';
                indicator.title = 'ATENÇÃO: Token expirando! Clique para renovar AGORA';
                if (indicatorModal) {
                    indicatorModal.style.background = '#ffebee';
                    iconModal.style.color = '#d32f2f';
                    iconModal.className = 'bi bi-shield-exclamation';
                    indicatorModal.title = 'ATENÇÃO: Token expirando! Clique para renovar AGORA';
                }
            } 
            // Alerta visual quando faltar menos de 5 minutos
            else if (tempoRestante < 300) {
                indicator.style.background = '#fff3e0';
                icon.style.color = '#f57c00';
                icon.className = 'bi bi-shield-exclamation';
                indicator.title = 'Token expirando em breve! Clique para renovar';
                if (indicatorModal) {
                    indicatorModal.style.background = '#fff3e0';
                    iconModal.style.color = '#f57c00';
                    iconModal.className = 'bi bi-shield-exclamation';
                    indicatorModal.title = 'Token expirando em breve! Clique para renovar';
                }
            } 
            else {
                indicator.style.background = '#e8f5e9';
                icon.style.color = '#4caf50';
                icon.className = 'bi bi-shield-check';
                indicator.title = 'Token válido. Clique para renovar manualmente';
                if (indicatorModal) {
                    indicatorModal.style.background = '#e8f5e9';
                    iconModal.style.color = '#4caf50';
                    iconModal.className = 'bi bi-shield-check';
                    indicatorModal.title = 'Token válido. Clique para renovar manualmente';
                }
            }

            // Auto-renovação quando faltar 3 minutos
            if (tempoRestante === 180) {
                console.log('Auto-renovando token (3 min restantes)...');
                renovarTokenAutomatico();
            }
        } catch (e) {
            console.error('Erro ao decodificar token:', e);
            timeDisplay.textContent = 'Erro';
            indicator.style.background = '#ffebee';
            icon.style.color = '#d32f2f';
            icon.className = 'bi bi-shield-x';
            if (indicatorModal) {
                timeDisplayModal.textContent = 'Erro';
                indicatorModal.style.background = '#ffebee';
                iconModal.style.color = '#d32f2f';
                iconModal.className = 'bi bi-shield-x';
            }
        }
    }

    atualizarDisplay();
    tokenMonitorInterval = setInterval(atualizarDisplay, 1000);
}

function isAccessTokenValid() {
    try {
        const token = localStorage.getItem('accessToken');
        if (!token) return false;
        const payload = jwt_decode(token);
        return payload && payload.exp && payload.exp > Math.floor(Date.now() / 1000);
    } catch {
        return false;
    }
}

async function renovarTokenManual() {
    const indicator = document.getElementById('token-indicator');
    const timeDisplay = document.getElementById('token-time');
    const indicatorModal = document.getElementById('token-indicator-modal');
    const timeDisplayModal = document.getElementById('token-time-modal');
    
    if (!indicator || !timeDisplay) return;
    
    // Atualizar ambos os indicadores para "Renovando..."
    timeDisplay.textContent = 'Renovando...';
    indicator.style.opacity = '0.6';
    if (indicatorModal && timeDisplayModal) {
        timeDisplayModal.textContent = 'Renovando...';
        indicatorModal.style.opacity = '0.6';
    }

    try {
        await renovarTokenAPI();
        timeDisplay.textContent = 'Renovado!';
        if (timeDisplayModal) timeDisplayModal.textContent = 'Renovado!';
        setTimeout(() => {
            indicator.style.opacity = '1';
            if (indicatorModal) indicatorModal.style.opacity = '1';
        }, 1000);
    } catch (e) {
        if (isAccessTokenValid()) {
            timeDisplay.textContent = 'Tente nov.';
            if (timeDisplayModal) timeDisplayModal.textContent = 'Tente nov.';
            if (window.showAlert) {
                window.showAlert('Não foi possível renovar. Tente novamente em instantes.', 'warning');
            } else {
                alert('Não foi possível renovar. Tente novamente em instantes.');
            }
        } else {
            timeDisplay.textContent = 'Sessão expirada';
            if (timeDisplayModal) timeDisplayModal.textContent = 'Sessão expirada';
            handleSessaoExpirada('Sua sessão expirou. Faça login novamente.');
        }
        setTimeout(() => {
            indicator.style.opacity = '1';
            if (indicatorModal) indicatorModal.style.opacity = '1';
        }, 2000);
    }
}

async function renovarTokenAutomatico() {
    try {
        await renovarTokenAPI();
        console.log('Token renovado automaticamente');
    } catch (e) {
        console.error('Erro na renovação automática:', e);
    }
}

// Evita duas renovações ao mesmo tempo (rotação de refresh token invalida o anterior).
let refreshPromise = null;

async function renovarTokenAPI() {
    if (refreshPromise) {
        return refreshPromise;
    }

    const doRefresh = async () => {
        const refresh = localStorage.getItem('refreshToken');
        if (!refresh) {
            handleSessaoExpirada('Sua sessão expirou. Faça login novamente.');
            throw new Error('Sem refresh token');
        }

        const response = await fetch('/api/auth/token/refresh/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ refresh: refresh })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const detail = errorData.detail || 'Falha ao renovar token';
            const err = new Error(detail);
            err.status = response.status;
            throw err;
        }

        const data = await response.json();
        localStorage.setItem('accessToken', data.access);
        if (data.refresh) localStorage.setItem('refreshToken', data.refresh);
    };

    refreshPromise = doRefresh();
    try {
        await refreshPromise;
    } finally {
        refreshPromise = null;
    }
}

function handleSessaoExpirada(message) {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('user_profile');
    localStorage.removeItem('user_permissions');
    localStorage.removeItem('last_login');
    
    if (window.showAlert) {
        window.showAlert(message, 'warning');
    }
    
    setTimeout(() => {
        window.location.href = '/';
    }, 1500);
}

// Parar monitoramento ao sair da página
window.addEventListener('beforeunload', () => {
    if (tokenMonitorInterval) clearInterval(tokenMonitorInterval);
});
// ===== FIM MONITORAMENTO TOKEN =====