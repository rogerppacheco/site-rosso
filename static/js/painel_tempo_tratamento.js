/**
 * Painel visual de tempo de tratamento (auditoria / esteira).
 *
 * Uso:
 *   PainelTempoTratamento.init({
 *     modulo: 'AUDITORIA' | 'ESTEIRA',
 *     fetchJson: async (path) => data,   // path relativo tipo '/tratamento/relatorio/?...'
 *     postJson: async (path, body) => data,
 *     canSendZap: boolean,
 *   });
 *   PainelTempoTratamento.carregar();
 */
(function (global) {
    'use strict';

    let cfg = null;
    let chartQtd = null;
    let chartMedia = null;
    let chartJsPromise = null;

    function $(id) {
        return document.getElementById(id);
    }

    function fmtDuracao(segundos) {
        const total = Math.max(0, Math.round(Number(segundos) || 0));
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        if (h) return h + 'h' + String(m).padStart(2, '0') + 'm';
        if (m) return m + 'm' + String(s).padStart(2, '0') + 's';
        return s + 's';
    }

    function hojeISO() {
        const d = new Date();
        return (
            d.getFullYear() +
            '-' +
            String(d.getMonth() + 1).padStart(2, '0') +
            '-' +
            String(d.getDate()).padStart(2, '0')
        );
    }

    function garantirChartJs() {
        if (global.Chart) return Promise.resolve();
        if (chartJsPromise) return chartJsPromise;
        chartJsPromise = new Promise(function (resolve, reject) {
            const s = document.createElement('script');
            s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
            s.onload = function () { resolve(); };
            s.onerror = function () { reject(new Error('Falha ao carregar Chart.js')); };
            document.head.appendChild(s);
        });
        return chartJsPromise;
    }

    function destruirCharts() {
        if (chartQtd) { chartQtd.destroy(); chartQtd = null; }
        if (chartMedia) { chartMedia.destroy(); chartMedia = null; }
    }

    function corBarra(idx) {
        const cores = [
            'rgba(13, 110, 253, 0.75)',
            'rgba(25, 135, 84, 0.75)',
            'rgba(255, 193, 7, 0.8)',
            'rgba(220, 53, 69, 0.75)',
            'rgba(111, 66, 193, 0.75)',
            'rgba(13, 202, 240, 0.75)',
            'rgba(253, 126, 20, 0.75)',
        ];
        return cores[idx % cores.length];
    }

    function renderKpis(dados) {
        const set = function (id, val) {
            const el = $(id);
            if (el) el.textContent = val;
        };
        set('tt-kpi-qtd', dados.qtd != null ? dados.qtd : '—');
        set('tt-kpi-media', dados.qtd ? fmtDuracao(dados.media) : '—');
        set('tt-kpi-mediana', dados.qtd ? fmtDuracao(dados.mediana) : '—');
        set('tt-kpi-outliers', dados.outliers != null ? dados.outliers : '—');
    }

    function renderTabela(linhas) {
        const tbody = $('tt-tbody');
        if (!tbody) return;
        if (!linhas || !linhas.length) {
            tbody.innerHTML =
                '<tr><td colspan="7" class="text-center text-muted py-3">Nenhum tratamento com decisão neste dia.</td></tr>';
            return;
        }
        tbody.innerHTML = linhas
            .map(function (item, i) {
                return (
                    '<tr>' +
                    '<td class="fw-semibold">' +
                    (i + 1) +
                    '</td>' +
                    '<td>' +
                    (item.nome || '—') +
                    '</td>' +
                    '<td class="text-center">' +
                    item.qtd +
                    '</td>' +
                    '<td class="text-center">' +
                    fmtDuracao(item.media) +
                    '</td>' +
                    '<td class="text-center">' +
                    fmtDuracao(item.mediana) +
                    '</td>' +
                    '<td class="text-center">' +
                    fmtDuracao(item.maximo) +
                    '</td>' +
                    '<td class="text-center">' +
                    (item.outliers
                        ? '<span class="badge text-bg-warning">' + item.outliers + '</span>'
                        : '0') +
                    '</td>' +
                    '</tr>'
                );
            })
            .join('');
    }

    function renderCharts(linhas) {
        const canvasQtd = $('tt-chart-qtd');
        const canvasMedia = $('tt-chart-media');
        if (!canvasQtd || !canvasMedia || !global.Chart) return;

        destruirCharts();
        const labels = (linhas || []).map(function (l) {
            const n = String(l.nome || '').trim();
            const partes = n.split(/\s+/);
            return partes[0] || n || '—';
        });
        const qtds = (linhas || []).map(function (l) { return l.qtd || 0; });
        const mediasMin = (linhas || []).map(function (l) {
            return Math.round(((l.media || 0) / 60) * 10) / 10;
        });
        const cores = labels.map(function (_, i) { return corBarra(i); });

        chartQtd = new global.Chart(canvasQtd, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Tratadas',
                    data: qtds,
                    backgroundColor: cores,
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Quantidade tratada por pessoa' },
                },
                scales: {
                    y: { beginAtZero: true, ticks: { precision: 0 } },
                },
            },
        });

        chartMedia = new global.Chart(canvasMedia, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Média (min)',
                    data: mediasMin,
                    backgroundColor: cores.map(function (c) {
                        return c.replace('0.75', '0.55').replace('0.8', '0.55');
                    }),
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: 'Tempo médio (minutos)' },
                },
                scales: {
                    y: { beginAtZero: true },
                },
            },
        });
    }

    function setStatus(msg, isError) {
        const el = $('tt-status');
        if (!el) return;
        el.textContent = msg || '';
        el.className = 'small ' + (isError ? 'text-danger' : 'text-muted');
    }

    function atualizarBotaoZap(pode) {
        const btn = $('tt-btn-enviar-zap');
        if (!btn) return;
        const liberado = !!(pode || (cfg && cfg.canSendZap));
        btn.style.display = liberado ? '' : 'none';
        btn.disabled = !liberado;
    }

    async function carregar() {
        if (!cfg) return;
        const input = $('tt-data');
        const data = (input && input.value) || hojeISO();
        if (input && !input.value) input.value = data;

        setStatus('Carregando…');
        const loading = $('tt-loading');
        if (loading) loading.style.display = '';

        try {
            await garantirChartJs();
            const qs =
                '/tratamento/relatorio/?data=' +
                encodeURIComponent(data) +
                '&modulo=' +
                encodeURIComponent(cfg.modulo);
            const resp = await cfg.fetchJson(qs);
            const metricas = (resp && resp.metricas) || {};
            const modulos = metricas.modulos || {};
            const dados = modulos[cfg.modulo] || {
                linhas: [],
                qtd: 0,
                media: 0,
                mediana: 0,
                outliers: 0,
            };

            renderKpis(dados);
            renderTabela(dados.linhas || []);
            renderCharts(dados.linhas || []);
            atualizarBotaoZap(resp && resp.pode_enviar_whatsapp);

            const labelModulo = cfg.modulo === 'ESTEIRA' ? 'Esteira' : 'Auditoria';
            setStatus(
                labelModulo +
                    ' · ' +
                    data.split('-').reverse().join('/') +
                    ' · apenas sessões com decisão'
            );
        } catch (e) {
            renderKpis({ qtd: 0, media: 0, mediana: 0, outliers: 0 });
            renderTabela([]);
            destruirCharts();
            setStatus((e && e.message) || 'Erro ao carregar métricas.', true);
        } finally {
            if (loading) loading.style.display = 'none';
        }
    }

    async function enviarZap() {
        if (!cfg) return;
        const input = $('tt-data');
        const data = (input && input.value) || hojeISO();
        if (!confirm('Enviar o relatório de tempo de tratamento de ' + data + ' via WhatsApp?')) {
            return;
        }
        const btn = $('tt-btn-enviar-zap');
        if (btn) btn.disabled = true;
        setStatus('Enviando WhatsApp…');
        try {
            const resp = await cfg.postJson('/tratamento/enviar-relatorio/', { data: data });
            if (resp && resp.success) {
                setStatus('Relatório enviado com sucesso.');
                alert(resp.detail || 'Enviado.');
            } else {
                throw new Error((resp && resp.detail) || 'Falha no envio.');
            }
        } catch (e) {
            setStatus((e && e.message) || 'Erro ao enviar.', true);
            alert('Erro ao enviar: ' + ((e && e.message) || e));
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function init(config) {
        cfg = config || {};
        const input = $('tt-data');
        if (input && !input.value) input.value = hojeISO();
        atualizarBotaoZap(!!cfg.canSendZap);
        const btnAtualizar = $('tt-btn-atualizar');
        if (btnAtualizar) {
            btnAtualizar.onclick = function () { carregar(); };
        }
        const btnZap = $('tt-btn-enviar-zap');
        if (btnZap) {
            btnZap.onclick = function () { enviarZap(); };
        }
        if (input) {
            input.onchange = function () { carregar(); };
        }
    }

    global.PainelTempoTratamento = {
        init: init,
        carregar: carregar,
        enviarZap: enviarZap,
        fmtDuracao: fmtDuracao,
    };
})(window);
