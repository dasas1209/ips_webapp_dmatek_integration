// configuracao injectada no browser para todos os modulos frontend — substituir definindo window.RUNTIME_CONFIG
(function () {
    const globalConfig = window.RUNTIME_CONFIG || {};

    const merged = {
        map: {
            // raio maximo do circulo de incerteza de posicao (px)
            maxRaioIncertezaPx: 50,
            // raio base quando a tag acabou de reportar posicao (px)
            baseRaioIncertezaPx: 10,
            // crescimento do raio por segundo sem actualizacao (px/s)
            crescimentoRaioIncertezaPx: 0.5,
            // raio de clique para seleccionar uma tag no canvas (px)
            pickRadiusPx: 20,
            ...((globalConfig.map) || {}),
        },
        timing: {
            // segundos sem actualizacao para considerar tag offline no frontend
            tempoOfflineSeg: 10,
            // intervalo de polling de posicoes em ms (deve corresponder a JANELA_KPI_HORAS no backend)
            refreshPosicoesMs: 2000,
            // intervalo de actualizacao dos KPIs no dashboard (ms)
            refreshKpisMs: 60000,
            // tempo minimo entre toasts do mesmo tipo para a mesma tag (ms)
            toastCooldownMs: 15000,
            // duracao de visibilidade do toast antes de comecar o fade (ms)
            toastVisibleMs: 4200,
            // duracao da animacao de fade-out do toast (ms)
            toastFadeMs: 180,
            ...((globalConfig.timing) || {}),
        },
        api: {
            posicoesPath: "/posicoes",
            kpisPath: "/kpis",
            historicoPath: "/historico",
            loginPath: "/login",
            ...((globalConfig.api) || {}),
        },
        tenantTheme: {
            // cor primaria por defeito quando o tenant nao tem tema definido
            defaultPrimary: "#3b82f6",
            // mapa de tenant_id -> cor primaria (ex: { "cliente_a": "#e63946" })
            byTenantId: {},
            ...((globalConfig.tenantTheme) || {}),
        },
        chart: {
            // cores dos graficos de KPI no relatorio
            distancias: "#0d6efd",
            utilizacao: "#28a745",
            bateria: "#fd7e14",
            // paleta ciclica de cores para distinguir tags no esparguete e historico
            tagPalette: [
                "#e63946", "#457b9d", "#2a9d8f", "#e9c46a", "#f4a261",
                "#264653", "#8338ec", "#fb5607", "#3a86ff", "#06d6a0",
                "#ffbe0b", "#f72585", "#4cc9f0", "#7209b7", "#b5179e",
                "#480ca8", "#3f37c9", "#4361ee", "#4895ef", "#4cc9f0",
            ],
            ...((globalConfig.chart) || {}),
        },
    };

    window.RUNTIME_CONFIG = merged;
})();
