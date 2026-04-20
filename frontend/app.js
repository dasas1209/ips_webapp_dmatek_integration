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
        
        // Desenhar o ponto principal (A Tag)
        ctx.beginPath();
        ctx.arc(pixelX, pixelY, 8, 0, 2 * Math.PI); // Ponto de 8 pixels de raio
        ctx.fillStyle = "#007bff"; // Azul industrial
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();

        // Etiqueta com o nome da Tag
        ctx.fillStyle = "#000000";
        ctx.font = "12px Arial";
        ctx.fillText(tag.tag_id, pixelX + 12, pixelY + 4);
    });
}