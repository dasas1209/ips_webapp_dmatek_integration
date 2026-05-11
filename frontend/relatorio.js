const instanciasGraficos = new Map();

function criarOuAtualizarGrafico(canvasId, wrapperId, labels, valores, labelY, cor) {
    const canvasEl = document.getElementById(canvasId);
    const wrapperEl = document.getElementById(wrapperId);
    if (!canvasEl || !wrapperEl) return;

    const LARGURA_POR_TAG = 80;
    const larguraCanvas = Math.max(labels.length * LARGURA_POR_TAG, wrapperEl.clientWidth);

    canvasEl.width = larguraCanvas;
    canvasEl.style.width = `${larguraCanvas}px`;
    canvasEl.style.minWidth = `${larguraCanvas}px`;

    if (instanciasGraficos.has(canvasId)) {
        const grafico = instanciasGraficos.get(canvasId);
        grafico.data.labels = labels;
        grafico.data.datasets[0].data = valores;
        grafico.update();
        return;
    }

    const novoGrafico = new Chart(canvasEl.getContext("2d"), {
        type: "bar",
        data: {
            labels,
            datasets: [{
                label: labelY,
                data: valores,
                backgroundColor: cor,
                borderRadius: 4,
                barPercentage: 0.35,
                categoryPercentage: 0.8,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 180 },
            plugins: { legend: { display: false } },
            scales: {
                x: { title: { display: true, text: "Identificação da Tag", font: { size: 12 } } },
                y: { beginAtZero: true, title: { display: true, text: labelY, font: { size: 12 } } },
            },
        },
    });

    instanciasGraficos.set(canvasId, novoGrafico);
}

async function obterClienteDePosicoes() {
    const token = obterToken();
    if (!token) return null;

    try {
        const respostaPosicoes = await fetch("/posicoes", {
            headers: { Authorization: "Bearer " + token },
        });
        if (!respostaPosicoes.ok) return null;
        const pacote = await respostaPosicoes.json();
        return pacote.cliente || null;
    } catch {
        return null;
    }
}

async function atualizarPainelDiretor() {
    const tenantStorage = obterTenantId();
    const tenantPosicoes = await obterClienteDePosicoes();
    const token = obterToken();
    const candidatos = [...new Set([tenantStorage, tenantPosicoes].filter(Boolean))];

    if (candidatos.length === 0 || !token) {
        window.location.href = "/";
        return;
    }

    try {
        let dados = null;
        for (const tenant of candidatos) {
            const resposta = await fetch(`/kpis/${encodeURIComponent(tenant)}`, {
                headers: { Authorization: "Bearer " + token },
            });
            if (!resposta.ok) continue;
            const tentativa = await resposta.json();
            if (tentativa?.sucesso) {
                dados = tentativa;
                break;
            }
        }
        if (!dados) return;

        document.getElementById("kpi-distancia").innerText = `${dados.kpis.distancia_percorrida_metros} m`;
        document.getElementById("kpi-utilizacao").innerText = `${dados.kpis.taxa_utilizacao_perc} %`;
        document.getElementById("kpi-bateria").innerText = `${dados.kpis.bateria_media_frota_perc} %`;

        const etiquetasTags = Object.keys(dados.grafico_distancias).sort();

        const configGraficos = [
            { canvasId: "graficoDistancias", wrapperId: "wrapperDistancias", dataMap: dados.grafico_distancias, labelY: "Distância (m)", cor: "#0d6efd" },
            { canvasId: "graficoUtilizacao", wrapperId: "wrapperUtilizacao", dataMap: dados.grafico_utilizacao, labelY: "Taxa de Utilização (%)", cor: "#28a745" },
            { canvasId: "graficoBateria", wrapperId: "wrapperBateria", dataMap: dados.grafico_bateria, labelY: "Bateria (%)", cor: "#fd7e14" },
        ];

        configGraficos.forEach(({ canvasId, wrapperId, dataMap, labelY, cor }) => {
            const valores = etiquetasTags.map((tag) => dataMap[tag] ?? 0);
            criarOuAtualizarGrafico(canvasId, wrapperId, etiquetasTags, valores, labelY, cor);
        });
    } catch (erro) {
        console.error("Erro ao carregar o painel de diretor:", erro);
    }
}

window.onload = function () {
    redirecionarSeNaoAutenticado();
    atualizarPainelDiretor();
};

