// --- VARIÁVEIS ---
// Canvas inicializado de forma segura (só existe na página index)
const canvas = document.getElementById("mapaFabrica");
const ctx = canvas ? canvas.getContext("2d") : null;
let imagemMapa = new Image();
let loopAtualizacao;
let loopAtualizacaoKpis;

// Detect page
const isIndex = window.location.pathname.includes('index.html') || window.location.pathname === '/';
const isRelatorio = window.location.pathname.includes('relatorio.html');

// Obtém o tenant_id: primeiro do localStorage, senão descodifica o JWT (payload é base64 público)
function obterTenantId() {
    const cached = localStorage.getItem("tenant_id");
    if (cached) return cached;

    const token = localStorage.getItem("cracha_jwt");
    if (!token) return null;

    try {
        // JWT = header.payload.signature — o payload é base64url, não precisa de biblioteca
        const payloadB64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
        const payload = JSON.parse(atob(payloadB64));
        const tenant = payload.tenant_id || null;
        if (tenant) localStorage.setItem("tenant_id", tenant); // guardar para próximas chamadas
        return tenant;
    } catch (e) {
        return null;
    }
}

// Dimensões reais da fábrica em cm
const LIMITE_X_CM = 760;
const LIMITE_Y_CM = 500;

// 1. Login
async function fazerLogin() {
    const user = document.getElementById("username").value;
    const pass = document.getElementById("password").value;
    const erroTexto = document.getElementById("mensagem_erro");

    // O Swagger UI e o FastAPI OAuth2 exigem dados em formato "Form Data" e não JSON!
    const formData = new URLSearchParams();
    formData.append("username", user);
    formData.append("password", pass);

    try {
        const resposta = await fetch("/login", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded"
            },
            body: formData.toString()
        });

        if (resposta.ok) {
            const dados = await resposta.json();
            // Sucesso! token e tenant_id guardados
            localStorage.setItem("cracha_jwt", dados.access_token);
            localStorage.setItem("tenant_id", dados.tenant_id);
            // Guarda o timestamp do login para filtrar markers antigos no mapa
            localStorage.setItem("login_timestamp", new Date().toISOString());
            erroTexto.innerText = "";
            mudarParaDashboard();
        } else {
            erroTexto.innerText = "Credenciais inválidas. Acesso Negado.";
        }
    } catch (erro) {
        erroTexto.innerText = "Erro ao contactar o servidor.";
    }
}

// 2. Transições Visuais - Single Page Application
async function mudarParaDashboard() {
    document.getElementById("seccao_login").classList.add("escondido");
    document.getElementById("seccao_dashboard").classList.remove("escondido");
    const painelDiretor = document.getElementById("painel_diretor");
    painelDiretor.style.display = "flex";
    painelDiretor.classList.remove("escondido");

    await obterPosicoes(); // Puxa logo a 1ª vez
    atualizarPainelDiretor();

    // Começa a pedir dados à API a cada 2 segundos (2000 ms)
    loopAtualizacao = setInterval(obterPosicoes, 2000);
    if (!loopAtualizacaoKpis) {
        loopAtualizacaoKpis = setInterval(atualizarPainelDiretor, 60000);
    }
}

function fazerLogout() {
    clearInterval(loopAtualizacao);
    if (loopAtualizacaoKpis) {
        clearInterval(loopAtualizacaoKpis);
        loopAtualizacaoKpis = null;
    }
    localStorage.removeItem("cracha_jwt");       // Destrói o crachá
    localStorage.removeItem("tenant_id");        // Limpa o contexto do cliente
    localStorage.removeItem("login_timestamp");  // Limpa o filtro de recência
    document.getElementById("seccao_dashboard").classList.add("escondido");
    document.getElementById("painel_diretor").style.display = "none";
    document.getElementById("painel_diretor").classList.add("escondido");
    document.getElementById("seccao_login").classList.remove("escondido");
}

// 3. Verificação de Segurança ao dar refresh
// user verificado faz refresh nao precisa de login de novo
window.onload = function() {
    if (isRelatorio) {
        atualizarPainelDiretor();
    } else if (localStorage.getItem("cracha_jwt")) {
        mudarParaDashboard();
    }
}

// 4. busca os dados
async function obterPosicoes() {
    const token = localStorage.getItem("cracha_jwt");
    const consola = document.getElementById("consola_dados");
    
    if (!token) {
        fazerLogout();
        return;
    }

    try {
        // pedido GET com crachá no Header de Autorização
        const resposta = await fetch("/posicoes", {
            method: "GET",
            headers: {
                "Authorization": "Bearer " + token
            }
        });
        if (resposta.ok) {
            const pacoteDados = await resposta.json();
            document.getElementById("nome_cliente").innerText = pacoteDados.cliente;

            //Alimenta o painel de baterias e de alertas a cada ciclo
            atualizarPainelBaterias(pacoteDados.dados);
            atualizarPainelAlertas(pacoteDados.dados);

            // Define o caminho que queremos
            const caminhoCorreto = `/static/assets/mapa_${pacoteDados.cliente}.png`;

            // Se o mapa ainda não é o correto, pedimos ao browser para o carregar
            if (!imagemMapa.src.includes(caminhoCorreto)) {
                imagemMapa.src = caminhoCorreto;
                
                // POKA-YOKE: Só arrancamos o motor gráfico QUANDO o download terminar
                imagemMapa.onload = function() {
                    desenharFabrica(pacoteDados);
                };
            } else {
                // Se a imagem já foi descarregada em ciclos anteriores, desenha direto
                desenharFabrica(pacoteDados);
            }
        } else {
            // token expirou ou inválido
            consola.innerText = "Erro de Autenticação. Por favor, saia e entre novamente.";
            fazerLogout();
        }
    } catch (erro) {
        console.error("Erro ao comunicar com a Base de Dados (InfluxDB).", erro);
    }
}

// Mapa de instâncias Chart.js: canvasId → instância Chart
// Usar Map permite gerir N gráficos sem repetir variáveis globais
const instanciasGraficos = new Map();

/**
 * Cria ou atualiza um gráfico Chart.js de barras.
 * @param {string} canvasId   - id do elemento <canvas>
 * @param {string} wrapperId  - id do div.chart-wrapper (para calcular largura)
 * @param {string[]} labels   - etiquetas do eixo X (tag_ids)
 * @param {number[]} valores  - valores do eixo Y
 * @param {string} labelY     - título do eixo Y (inclui unidade)
 * @param {string} cor        - cor de preenchimento das barras (hex)
 */
function criarOuAtualizarGrafico(canvasId, wrapperId, labels, valores, labelY, cor) {
    const canvasEl  = document.getElementById(canvasId);
    const wrapperEl = document.getElementById(wrapperId);
    if (!canvasEl || !wrapperEl) return;

    // Com poucas tags: o canvas preenche o container (wrapper) — barras proporcional ao ecrã
    // Com muitas tags: cresce além do wrapper a 80px/tag → scroll horizontal ativa-se
    const LARGURA_POR_TAG = 80;
    const larguraCanvas = Math.max(labels.length * LARGURA_POR_TAG, wrapperEl.clientWidth);

    // Define tanto o atributo (resolução interna do canvas) como o CSS (tamanho visual)
    canvasEl.width          = larguraCanvas;
    canvasEl.style.width    = larguraCanvas + 'px';
    canvasEl.style.minWidth = larguraCanvas + 'px';

    if (instanciasGraficos.has(canvasId)) {
        // Gráfico já existe: atualiza só os dados (evita recriar o DOM)
        const grafico = instanciasGraficos.get(canvasId);
        grafico.data.labels = labels;
        grafico.data.datasets[0].data = valores;
        grafico.update();
        return;
    }

    // Primeira renderização: configura o gráfico completo
    const ctx = canvasEl.getContext('2d');
    const novoGrafico = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: labelY,
                data: valores,
                backgroundColor: cor,
                borderRadius: 4,
                barPercentage: 0.35,      // Barras finas — legíveis com qualquer nº de tags
                categoryPercentage: 0.8
            }]
        },
        options: {
            responsive: true,             // Chart.js gere o canvas dentro do container
            maintainAspectRatio: false,   // Altura bloqueada pelo CSS (350px)
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Identificação da Tag',
                        font: { size: 12 }
                    }
                },
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: labelY,
                        font: { size: 12 }
                    }
                }
            }
        }
    });

    instanciasGraficos.set(canvasId, novoGrafico);
}

async function atualizarPainelDiretor() {
    try {
        if (isIndex) {
            const secaoDashboard = document.getElementById('seccao_dashboard');
            const tenantDinamico = document.getElementById('nome_cliente').innerText.trim();

            if (secaoDashboard.classList.contains('escondido') || !tenantDinamico) {
                return;
            }

            const resposta = await fetch(`/kpis/${encodeURIComponent(tenantDinamico)}`);
            const dados = await resposta.json();

            if (dados.sucesso) {
                // 1. Atualizar os Cartões KPI
                document.getElementById('kpi-distancia').innerText = dados.kpis.distancia_percorrida_metros + ' m';
                document.getElementById('kpi-utilizacao').innerText = dados.kpis.taxa_utilizacao_perc + ' %';
                document.getElementById('kpi-bateria').innerText = dados.kpis.bateria_media_frota_perc + ' %';
            }
        } else if (isRelatorio) {
            // Obtém o tenant — do cache ou descodificando o JWT (compatível com sessões antigas)
            const tenantAtual = obterTenantId();

            if (!tenantAtual) {
                // Sem sessão ativa nem token válido: redireciona para o login
                window.location.href = '/';
                return;
            }

            const resposta = await fetch(`/kpis/${encodeURIComponent(tenantAtual)}`);
            const dados = await resposta.json();

            if (dados.sucesso) {
                // Tags ordenadas alfabeticamente para eixo X consistente entre gráficos
                const etiquetasTags = Object.keys(dados.grafico_distancias).sort();

                /**
                 * Config declarativa: cada entrada define um gráfico.
                 * Para adicionar um novo KPI basta acrescentar uma linha aqui.
                 */
                const configGraficos = [
                    {
                        canvasId:  'graficoDistancias',
                        wrapperId: 'wrapperDistancias',
                        dataMap:   dados.grafico_distancias,
                        labelY:    'Distância (m)',
                        cor:       '#0d6efd'
                    },
                    {
                        canvasId:  'graficoUtilizacao',
                        wrapperId: 'wrapperUtilizacao',
                        dataMap:   dados.grafico_utilizacao,
                        labelY:    'Taxa de Utilização (%)',
                        cor:       '#28a745'
                    },
                    {
                        canvasId:  'graficoBateria',
                        wrapperId: 'wrapperBateria',
                        dataMap:   dados.grafico_bateria,
                        labelY:    'Bateria (%)',
                        cor:       '#fd7e14'
                    }
                ];

                // Loop único que renderiza todos os gráficos sem repetição de código
                configGraficos.forEach(({ canvasId, wrapperId, dataMap, labelY, cor }) => {
                    // Garante que os valores seguem a mesma ordem das etiquetas
                    const valores = etiquetasTags.map(tag => dataMap[tag] ?? 0);
                    criarOuAtualizarGrafico(canvasId, wrapperId, etiquetasTags, valores, labelY, cor);
                });
            }
        }
    } catch (erro) {
        console.error("Erro ao carregar o Painel do Diretor:", erro);
    }
}

// 5. Motor Gráfico
function desenharFabrica(pacoteDados) {
    // 1. Limpar a tela anterior (para as tags não deixarem rasto ao mover)
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 2. Desenhar a planta do cliente no fundo
    if (imagemMapa.complete && imagemMapa.naturalWidth !== 0) {
        ctx.drawImage(imagemMapa, 0, 0, canvas.width, canvas.height);
    }

    // 3. FILTRO DE RECÊNCIA: remove markers de sessões anteriores ao login atual
    const agora = new Date();
    const loginTimestamp = localStorage.getItem("login_timestamp");
    const loginTs = loginTimestamp ? new Date(loginTimestamp) : null;

    const tagsAtivas = pacoteDados.dados.filter(tag => {
        const ultimaLeitura = new Date(tag.timestamp);
        // Descarta apenas se a leitura é anterior ao login desta sessão
        if (loginTs && ultimaLeitura < loginTs) return false;
        return true;
    });

    // 4. Desenhar cada Tag ativa
    tagsAtivas.forEach(tag => {
        // Regra de três simples para converter Realidade -> Ecrã
        const pixelX = (tag.x * canvas.width) / LIMITE_X_CM;
        const pixelY = (tag.y * canvas.height) / LIMITE_Y_CM;

        // --- CÁLCULO DE INCERTEZA ---
        const ultimaLeitura = new Date(tag.timestamp);
        const tempoSemSinalSegundos = (agora - ultimaLeitura) / 1000;

        // Se passaram mais de 10 segundos sem sinal, ativamos a incerteza
        if (tempoSemSinalSegundos > 10) {
            // O círculo cresce com o tempo, até um limite máximo (ex: 50 pixels)
            let raioIncerteza = Math.min(10 + (tempoSemSinalSegundos * 0.5), 50);

            ctx.beginPath();
            ctx.arc(pixelX, pixelY, raioIncerteza, 0, 2 * Math.PI);
            ctx.fillStyle = "rgba(255, 165, 0, 0.3)"; // Cor Laranja Translúcida (Alerta de Incerteza)
            ctx.fill();
        }
        
        // --- SISTEMA ANDON ---
        let raioTag = 8;
        let corPreenchimento = "#007bff"; // Azul industrial (Normal)
        let corBorda = "#ffffff";

        // Se o estado não for "Normal", entramos em modo de EMERGÊNCIA
        if (tag.status !== null && tag.status !== "Normal") {
            raioTag = 12; // Aumentamos o tamanho da Tag para destacar no mapa
            corBorda = "#dc3545"; // Borda a vermelho forte
            
            // Lógica do Piscar (Strobe): Se a 1ª metade do segundo, vermelho. Se a 2ª metade, branco.
            const piscar = new Date().getMilliseconds() < 500;
            corPreenchimento = piscar ? "#dc3545" : "#ffffff"; 
        }
        
        // Desenhar a Tag efetivamente com as regras aplicadas
        ctx.beginPath();
        ctx.arc(pixelX, pixelY, raioTag, 0, 2 * Math.PI);
        ctx.fillStyle = corPreenchimento;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = corBorda;
        ctx.stroke();

        // Etiqueta com o nome da Tag
        ctx.fillStyle = "#000000";
        ctx.font = "12px Arial";
        ctx.fillText(tag.tag_id, pixelX + 12, pixelY + 4);
    });
}

// 6. Painel de Baterias (Manutenção Preventiva)
function atualizarPainelBaterias(dadosTags) {
    const listaBaterias = document.getElementById("lista_baterias");

    // 1. FILTRAGEM: ignorar nulls e ordenar por bateria (crescente - mais críticas primeiro)
    let todasAsTags = dadosTags.filter(tag => tag.bateria !== null);

    // 2. ORDENAÇÃO Crescente (mais críticas primeiro)
    todasAsTags.sort((a, b) => a.bateria - b.bateria);

    // 3. LIMPEZA do painel antes de escrever os novos dados
    listaBaterias.innerHTML = "";

    // 4. POKA-YOKE: Se não há tags, mostramos que está tudo bem
    if (todasAsTags.length === 0) {
        listaBaterias.innerHTML = '<li class="placeholder">Nenhuma tag online.</li>';
        return; // Pára a função aqui
    }

    // 5. Para cada tag, criar uma linha no painel com cor dinâmica
    todasAsTags.forEach(tag => {
        const itemLista = document.createElement("li");
        
        // Regra de cores por nível de bateria:
        // ≤ 5% → Vermelho (crítico)
        // 6-20% → Laranja (alerta)
        // > 20% → Verde (operacional)
        let corBateria;
        if (tag.bateria <= 5) {
            corBateria = "red"; // Crítico
        } else if (tag.bateria <= 20) {
            corBateria = "#fd7e14"; // Alerta (laranja)
        } else {
            corBateria = "#28a745"; // Normal (verde)
        }
        
        // Aplicar bold apenas em alertas e críticos
        let fontWeight = tag.bateria <= 20 ? "bold" : "normal";
        
        itemLista.innerHTML = `Tag <strong>${tag.tag_id}</strong>: <span style="color: ${corBateria}; font-weight: ${fontWeight};">${tag.bateria}%</span>`;
        listaBaterias.appendChild(itemLista);
    });
}

// 7. Painel de Alertas Críticos (Sistema Andon)
function atualizarPainelAlertas(dadosTags) {
    const listaAlertas = document.getElementById("lista_alertas");
    
    // 1. FILTRAGEM: apenas status seja diferente de "Normal", ignorar os nulls
    let tagsEmPanico = dadosTags.filter(tag => tag.status !== null && tag.status !== "Normal");

    // 2. LIMPEZA do painel
    listaAlertas.innerHTML = "";

    // 3. ESTADO NORMAL: lista vazia -> placeholder de segurança
    if (tagsEmPanico.length === 0) {
        listaAlertas.innerHTML = '<li class="placeholder">Nenhum alerta ativo. Sistema normal.</li>';
        return;
    }

    // 4. INJEÇÃO VISUAL:alerta vermelho e vibrante
    tagsEmPanico.forEach(tag => {
        const itemLista = document.createElement("li");
        
        // Formatação Vermelho, Negrito para chamar a atenção do operador
        itemLista.innerHTML = `🚨 <strong>EMERGÊNCIA:</strong> Tag <span style="color: #dc3545; font-weight: bold;">${tag.tag_id}</span> acionou o alarme!`;
        listaAlertas.appendChild(itemLista);
    });
}