/**
 * runtime config shared by frontend modules
 */
(function () {
    const globalConfig = window.RUNTIME_CONFIG || {};

    const merged = {
        map: {
            maxRaioIncertezaPx: 50,
            baseRaioIncertezaPx: 10,
            crescimentoRaioIncertezaPx: 0.5,
            pickRadiusPx: 20,
            ...((globalConfig.map) || {}),
        },
        timing: {
            tempoOfflineSeg: 10,
            refreshPosicoesMs: 2000,
            refreshKpisMs: 60000,
            toastCooldownMs: 15000,
            toastVisibleMs: 4200,
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
            defaultPrimary: "#3b82f6",
            byTenantId: {},
            ...((globalConfig.tenantTheme) || {}),
        },
        chart: {
            distancias: "#0d6efd",
            utilizacao: "#28a745",
            bateria: "#fd7e14",
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
