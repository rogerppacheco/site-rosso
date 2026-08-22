// ui.js - Lógica de Interação da Interface (Modais e Navegação)

document.addEventListener('DOMContentLoaded', function() {

    // --- MELHORIA: Lógica para destacar o link ativo da página atual ---
    try {
        // Remove a barra inicial e final para uma correspondência mais flexível
        const path = window.location.pathname.replace(/\/$/, '');
        const currentPage = path.split('/').pop(); // Pega a última parte da URL, ex: "governanca"

        if (currentPage) {
            // Constrói o href esperado, ex: "governanca.html" ou apenas "governanca"
            const expectedHref = currentPage.endsWith('.html') ? currentPage : `${currentPage}.html`;

            // Procura por um link de navegação no menu principal
            const activeMainMenuLink = document.querySelector(`.main-nav a[href$="${expectedHref}"]`);
            if (activeMainMenuLink) {
                activeMainMenuLink.classList.add('active-link');
            }

            // Procura por um link de navegação no submenu
            const activeSubMenuLink = document.querySelector(`.submenu a[href$="${expectedHref}"]`);
            if (activeSubMenuLink) {
                activeSubMenuLink.classList.add('active'); // Submenu usa a classe 'active'
            }
        } else {
             // Caso especial para a página inicial (raiz do site)
             const homeLink = document.querySelector('.main-nav a[href="/"]');
             if(homeLink){
                homeLink.classList.add('active-link');
             }
        }
    } catch (error) {
        console.error("Erro ao tentar destacar o link ativo:", error);
    }


    // --- Lógica para o Modal de Login (EXISTENTE E MANTIDA) ---
    const areaInternaBtn = document.getElementById('areaInternaButton');
    const loginModalOverlay = document.getElementById('loginModalOverlay');
    const cancelarLoginBtn = document.getElementById('cancelarLogin');
    const errorMessageDiv = document.getElementById('error-message');

    // Se os elementos essenciais do modal não estiverem na página, interrompe a execução da lógica do modal.
    if (areaInternaBtn && loginModalOverlay && cancelarLoginBtn) {
        // Função para mostrar o modal
        function showModal() {
            loginModalOverlay.style.display = 'flex'; // Torna o modal visível
            setTimeout(() => {
                loginModalOverlay.classList.add('active');
            }, 10);
            if(errorMessageDiv) {
                errorMessageDiv.style.display = 'none';
                errorMessageDiv.textContent = '';
            }
        }

        // Função para fechar o modal
        function closeModal() {
            loginModalOverlay.classList.remove('active');
            setTimeout(() => {
                loginModalOverlay.style.display = 'none';
            }, 300);
        }

        // Eventos para abrir e fechar o modal
        areaInternaBtn.addEventListener('click', function(e) {
            e.preventDefault();

            if (localStorage.getItem('accessToken')) {
                // CORREÇÃO: Aponta para a URL correta do Django
                window.location.href = '/area-interna/';
            } else {
                showModal();
            }
        });

        cancelarLoginBtn.addEventListener('click', closeModal);

        loginModalOverlay.addEventListener('click', function(e) {
            if (e.target === loginModalOverlay) {
                closeModal();
            }
        });
    }

    // A lógica de submissão do formulário de login continua no arquivo `auth.js`.
});