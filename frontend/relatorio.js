/**
 * relatorio.js
 * logica exclusiva da pagina relatorio.html com kpis por tag
 * depende de auth.js
 */

// mapa de instancias chartjs
const instanciasGraficos = new Map();

/**
 * cria ou actualiza grafico de barras
 */
function criarOuAtualizarGrafico(canvasId, wrapperId, labels, valores, labelY, cor) {
    const canvasEl = document.getElementById(canvasId);
    const wrapperEl = document.getElementById(wrapperId);
    if (!canvasEl || !wrapperEl) return;

    const LARGURA_POR_TAG = 80;
    const larguraCanvas = Math.max(labels.length * LARGURA_POR_TAG, wrapperEl.clientWidth);

    canvasEl.width = larguraCanvas;
    canvasEl.style.width = larguraCanvas + "px";
    canvasEl.style.minWidth = larguraCanvas + "px";

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
            plugins: { legend: { display: false } },
            scales: {
                x: { title: { display: true, text: "Identificação da Tag", font: { size: 12 } } },
                y: { beginAtZero: true, title: { display: true, text: labelY, font: { size: 12 } } },
            },
        },
    });

    instanciasGraficos.set(canvasId, novoGrafico);
}

/**
 * carrega kpis do tenant autenticado e desenha graficos
 */
async function atualizarPainelDiretor() {
    const tenant = obterTenantId();
    const token = obterToken();

    if (!tenant || !token) {
        window.location.href = "/";
        return;
    }

    try {
        const resposta = await fetch(`/kpis/${encodeURIComponent(tenant)}`, {
            headers: { "Authorization": "Bearer " + token },
        });
        const dados = await resposta.json();

        if (!dados.sucesso) {
            console.error("Erro ao carregar KPIs:", dados.erro);
            return;
        }

        const etiquetasTags = Object.keys(dados.grafico_distancias).sort();

        const configGraficos = [
            { canvasId: "graficoDistancias", wrapperId: "wrapperDistancias", dataMap: dados.grafico_distancias, labelY: "Distância (m)", cor: "#0d6efd" },
            { canvasId: "graficoUtilizacao", wrapperId: "wrapperUtilizacao", dataMap: dados.grafico_utilizacao, labelY: "Taxa de Utilização (%)", cor: "#28a745" },
            { canvasId: "graficoBateria", wrapperId: "wrapperBateria", dataMap: dados.grafico_bateria, labelY: "Bateria (%)", cor: "#fd7e14" },
        ];

        configGraficos.forEach(({ canvasId, wrapperId, dataMap, labelY, cor }) => {
            const valores = etiquetasTags.map(tag => dataMap[tag] ?? 0);
            criarOuAtualizarGrafico(canvasId, wrapperId, etiquetasTags, valores, labelY, cor);
        });

    } catch (erro) {
        console.error("Erro ao carregar o Painel do Diretor:", erro);
    }
}

// inicializacao
window.onload = function () {
    redirecionarSeNaoAutenticado();
    atualizarPainelDiretor();
};
