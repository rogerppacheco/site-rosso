/**
 * MENU.JS v5.3 - Sistema de Navegação Padronizado Record PAP
 * Gerencia menu responsivo, autenticação e funcionalidades globais
 */

document.addEventListener('DOMContentLoaded', () => {
    const menuToggle = document.getElementById('menu-toggle');
    const mainNav = document.querySelector('.main-nav');
    const userDisplay = document.getElementById('welcome-user');
    const headerUserName = document.getElementById('header-user-name');
    const headerLogoutBtn = document.getElementById('header-logout-btn');
    const currentPath = window.location.pathname;
    const isLandingPage = currentPath === '/' || currentPath === '/login/';
    const isInternalHome = currentPath === '/area-interna/';
    const backLinkEl = document.getElementById('header-back-link');
    const hasAppShellBack = !!(backLinkEl && !backLinkEl.classList.contains('d-none'));

    function normalizeInternalBackButton() {
        if (!mainNav) return;

        const navList = mainNav.querySelector('ul');
        if (!navList) return;

        // App Shell já tem Voltar discreto — não injeta o botão grande antigo
        if (hasAppShellBack) {
            navList.querySelectorAll('a.nav-back-button, a[href="/area-interna/"].nav-button').forEach(link => {
                const li = link.closest('li');
                if (li && !link.classList.contains('btn-login-trigger')) {
                    // Remove apenas o "Voltar/Área Interna" legado; mantém links de ação do módulo
                    const txt = (link.textContent || '').trim().toLowerCase();
                    if (txt === 'voltar' || txt === 'voltar para área interna' || txt === 'área interna' || txt === 'area interna') {
                        li.remove();
                    }
                }
            });
            return;
        }

        const areaInternaLinks = Array.from(navList.querySelectorAll('a[href="/area-interna/"]'));

        if (isLandingPage || isInternalHome) {
            areaInternaLinks.forEach(link => {
                if (link.classList.contains('nav-back-button')) {
                    link.closest('li')?.remove();
                }
            });
            return;
        }

        areaInternaLinks.forEach(link => {
            link.textContent = 'Voltar para área interna';
            link.classList.add('nav-back-button');
        });

        const hasBackButton = areaInternaLinks.some(link => link.classList.contains('nav-back-button'));
        if (hasBackButton) return;

        const li = document.createElement('li');
        const backLink = document.createElement('a');
        backLink.href = '/area-interna/';
        backLink.className = 'nav-back-button';
        backLink.innerHTML = '<i class="bi bi-arrow-left-short"></i> Voltar para área interna';
        li.appendChild(backLink);
        navList.prepend(li);
    }

    normalizeInternalBackButton();

    // ===== LÓGICA DO BOTÃO HAMBÚRGUER =====
    if (menuToggle && mainNav) {
        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            mainNav.classList.toggle('active');
            
            // Adiciona classe para animação do ícone X
            menuToggle.classList.toggle('active');
            
            // Previne scroll do body quando menu está aberto
            if (mainNav.classList.contains('active')) {
                document.body.style.overflow = 'hidden';
            } else {
                document.body.style.overflow = '';
            }
        });

        // Fecha menu ao clicar fora
        document.addEventListener('click', (e) => {
            if (mainNav.classList.contains('active') && 
                !mainNav.contains(e.target) && 
                !menuToggle.contains(e.target)) {
                closeMenu();
            }
        });

        // Fecha menu ao pressionar ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && mainNav.classList.contains('active')) {
                closeMenu();
            }
        });

        // Fecha menu quando redimensiona para desktop
        window.addEventListener('resize', () => {
            if (window.innerWidth > 992) {
                closeMenu();
            }
        });
    }

    // ===== FUNÇÃO PARA FECHAR MENU =====
    function closeMenu() {
        mainNav.classList.remove('active');
        menuToggle.classList.remove('active');
        document.body.style.overflow = '';
    }

    // ===== LÓGICA PARA SUBMENUS NO MOBILE =====
    const submenus = document.querySelectorAll('.has-submenu > a');
    submenus.forEach(link => {
        link.addEventListener('click', (e) => {
            if (window.innerWidth <= 992) {
                e.preventDefault();
                const parent = link.parentElement;
                const submenu = parent.querySelector('.submenu');
                if (submenu) {
                    parent.classList.toggle('open');
                }
            }
        });
    });

    // ===== AUTENTICAÇÃO E USUÁRIO =====
    const token = localStorage.getItem('accessToken');
    
    // Verifica se token é válido
    function isTokenValid() {
        if (!token) return false;
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const now = Date.now() / 1000;
            return payload.exp > now;
        } catch (e) {
            return false;
        }
    }

    // Carrega nome do usuário (área interna + menu do shell)
    function nomeDoToken() {
        if (!token) return 'Conta';
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            return payload.first_name || payload.user_name || payload.username || 'Conta';
        } catch (e) {
            return 'Conta';
        }
    }
    const nomeUsuario = nomeDoToken();
    if (userDisplay) userDisplay.textContent = nomeUsuario;
    if (headerUserName && token) {
        headerUserName.textContent = String(nomeUsuario).split(' ')[0] || 'Conta';
    }
    if (headerLogoutBtn) {
        headerLogoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            logout();
        });
    }

    // Verifica token expirado em páginas internas
    if (!isLandingPage) {
        if (!isTokenValid()) {
            console.log('Token inválido ou expirado, redirecionando...');
            logout();
        }
    }

    // ===== INDICADOR DE TOKEN (compacto, ao lado do menu do usuário) =====
    const userMenu = document.querySelector('.header-user-menu');
    const sairButton = document.querySelector('.logout-button');
    const tokenAnchor = userMenu || sairButton;
    if (tokenAnchor && token && !isLandingPage) {
        if (!document.getElementById('token-indicator')) {
            const tokenIndicator = document.createElement('div');
            tokenIndicator.id = 'token-indicator';
            tokenIndicator.className = 'token-indicator token-ok';
            tokenIndicator.title = 'Token válido. Clique para renovar';
            tokenIndicator.onclick = () => {
                if (typeof renovarTokenManual === 'function') {
                    renovarTokenManual();
                }
            };
            tokenIndicator.innerHTML = `
                <i class="bi bi-shield-check" aria-hidden="true"></i>
                <span id="token-time">--:--</span>
            `;
            tokenAnchor.parentNode.insertBefore(tokenIndicator, tokenAnchor);
            if (typeof iniciarMonitoramentoToken === 'function') {
                iniciarMonitoramentoToken();
            }
        }
    }

    // ===== INDICADOR DE LOADING GLOBAL =====
    function showGlobalLoading(message = 'Carregando...') {
        const existing = document.getElementById('global-loading');
        if (existing) return;

        const loading = document.createElement('div');
        loading.id = 'global-loading';
        loading.innerHTML = `
            <div style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; 
                        background: rgba(255,255,255,0.9); z-index: 9999; 
                        display: flex; align-items: center; justify-content: center; flex-direction: column;">
                <div class="spinner-border text-primary" style="width: 3rem; height: 3rem;"></div>
                <p class="mt-3 fw-bold">${message}</p>
            </div>
        `;
        document.body.appendChild(loading);
    }

    function hideGlobalLoading() {
        const loading = document.getElementById('global-loading');
        if (loading) loading.remove();
    }

    // Expor funções globalmente
    window.showGlobalLoading = showGlobalLoading;
    window.hideGlobalLoading = hideGlobalLoading;
});

// ===== FUNÇÃO DE LOGOUT GLOBAL =====
function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('user_profile');
    
    // Limpa outros dados se existirem
    localStorage.removeItem('user_permissions');
    localStorage.removeItem('last_login');
    
    window.location.href = '/';
}

// ===== UTILITÁRIOS GLOBAIS =====
function showAlert(message, type = 'success') {
    // Remove alertas existentes
    const existing = document.querySelectorAll('.global-alert');
    existing.forEach(el => el.remove());

    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show global-alert`;
    alertDiv.style.cssText = `
        position: fixed; 
        top: 100px; 
        right: 20px; 
        z-index: 1050; 
        min-width: 300px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    `;
    
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
    `;
    
    document.body.appendChild(alertDiv);
    
    // Remove automaticamente após 5 segundos
    setTimeout(() => {
        if (alertDiv.parentElement) {
            alertDiv.remove();
        }
    }, 5000);
}

// ===== FORMATADORES UTILITÁRIOS =====
function formatarMoeda(valor) {
    return new Intl.NumberFormat('pt-BR', { 
        style: 'currency', 
        currency: 'BRL' 
    }).format(valor);
}

function formatarData(data, incluirHora = false) {
    const opcoes = {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    };
    
    if (incluirHora) {
        opcoes.hour = '2-digit';
        opcoes.minute = '2-digit';
    }
    
    return new Date(data).toLocaleDateString('pt-BR', opcoes);
}

function formatarTelefone(telefone) {
    const num = telefone.replace(/\D/g, '');
    if (num.length === 11) {
        return `(${num.substring(0,2)}) ${num.substring(2,7)}-${num.substring(7)}`;
    } else if (num.length === 10) {
        return `(${num.substring(0,2)}) ${num.substring(2,6)}-${num.substring(6)}`;
    }
    return telefone;
}

// ===== REQUISIÇÕES API PADRONIZADAS =====
async function apiRequest(url, options = {}) {
    const token = localStorage.getItem('accessToken');
    
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            ...(token && { 'Authorization': `Bearer ${token}` })
        }
    };
    
    const finalOptions = {
        ...defaultOptions,
        ...options,
        headers: { ...defaultOptions.headers, ...options.headers }
    };
    
    try {
        const response = await fetch(url, finalOptions);
        
        // Se token expirado, faz logout
        if (response.status === 401) {
            logout();
            return null;
        }
        
        return response;
    } catch (error) {
        console.error('Erro na requisição:', error);
        showAlert('Erro de conexão. Tente novamente.', 'danger');
        return null;
    }
}

// Expor utilidades globalmente
window.logout = logout;
window.showAlert = showAlert;
window.formatarMoeda = formatarMoeda;
window.formatarData = formatarData;
window.formatarTelefone = formatarTelefone;
window.apiRequest = apiRequest;