/**
 * theme-toggle.js - Record PAP Dark/Light Mode v1.6
 * PersistÃªncia: localStorage['record-pap-theme'] = 'dark' | 'light'
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'record-pap-theme';
    var BG_LIGHT = '#F7F9FC';
    var BG_DARK = '#0F172A';

    function getPreferredTheme() {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            if (stored === 'dark' || stored === 'light') {
                return stored;
            }
        } catch (e) {
            /* localStorage indisponÃ­vel (modo privado restrito) */
        }
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    function persistTheme(theme) {
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch (e) {
            /* ignore */
        }
    }

    function updateToggleButton(theme) {
        var button = document.getElementById('theme-toggle');
        if (!button) {
            return;
        }
        var icon = button.querySelector('i');
        var isDark = theme === 'dark';
        if (icon) {
            icon.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
        }
        var label = isDark ? 'Ativar modo claro' : 'Ativar modo escuro';
        button.setAttribute('aria-label', label);
        button.setAttribute('title', label);
        button.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    }

    function applyTheme(theme) {
        var normalized = theme === 'dark' ? 'dark' : 'light';
        var root = document.documentElement;
        root.setAttribute('data-theme', normalized);
        root.setAttribute('data-bs-theme', normalized);
        root.style.colorScheme = normalized;
        root.style.backgroundColor = normalized === 'dark' ? BG_DARK : BG_LIGHT;
        if (document.body) {
            document.body.setAttribute('data-theme', normalized);
            document.body.setAttribute('data-bs-theme', normalized);
        }
        updateToggleButton(normalized);
    }

    function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme') || getPreferredTheme();
        var next = current === 'dark' ? 'light' : 'dark';
        persistTheme(next);
        applyTheme(next);
    }

    function bindThemeToggle() {
        var button = document.getElementById('theme-toggle');
        if (!button || button.dataset.themeBound === '1') {
            return;
        }
        button.dataset.themeBound = '1';
        button.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            toggleTheme();
        });
    }

    function initThemeToggle() {
        /* Restaura tema salvo imediatamente (anti-flicker do head jÃ¡ preencheu data-theme) */
        applyTheme(getPreferredTheme());
        bindThemeToggle();
    }

    initThemeToggle();

    document.addEventListener('DOMContentLoaded', function () {
        initThemeToggle();
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (event) {
            try {
                if (!localStorage.getItem(STORAGE_KEY)) {
                    applyTheme(event.matches ? 'dark' : 'light');
                }
            } catch (e) {
                applyTheme(event.matches ? 'dark' : 'light');
            }
        });
    });

    window.RecordPapTheme = {
        applyTheme: applyTheme,
        toggleTheme: toggleTheme,
        getPreferredTheme: getPreferredTheme,
        storageKey: STORAGE_KEY
    };
}());
