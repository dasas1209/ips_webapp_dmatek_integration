// --- VARIÁVEIS ---
const canvas = document.getElementById("mapaFabrica");
const ctx = canvas.getContext("2d");
let imagemMapa = new Image();
let loopAtualizacao;

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
            // Sucesso! token guardado
            localStorage.setItem("cracha_jwt", dados.access_token);
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
function mudarParaDashboard() {
    document.getElementById("seccao_login").classList.add("escondido");
    document.getElementById("seccao_dashboard").classList.remove("escondido");

    obterPosicoes(); // Puxa logo a 1ª vez
    // Começa a pedir dados à API a cada 2 segundos (2000 ms)
    loopAtualizacao = setInterval(obterPosicoes, 2000);
}

function fazerLogout() {
    clearInterval(loopAtualizacao);
    localStorage.removeItem("cracha_jwt"); // Destrói o cracha
    document.getElementById("seccao_dashboard").classList.add("escondido");
    document.getElementById("seccao_login").classList.remove("escondido");
    document.getElementById("consola_dados").innerText = "A aguardar dados da fábrica...";
}

// 3. Verificação de Segurança ao dar refresh
// user verificado faz refresh nao precisa de login de novo
window.onload = function() {
    if (localStorage.getItem("cracha_jwt")) {
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
        consola.innerText = "Erro ao comunicar com a Base de Dados (InfluxDB).";
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

    // 3. Desenhar cada Tag
    pacoteDados.dados.forEach(tag => {
        // Regra de três simples para converter Realidade -> Ecrã
        const pixelX = (tag.x * canvas.width) / LIMITE_X_CM;
        const pixelY = (tag.y * canvas.height) / LIMITE_Y_CM;

        // --- CÁLCULO DE INCERTEZA ---
        const agora = new Date();
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