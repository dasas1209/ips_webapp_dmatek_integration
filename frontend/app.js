/**
 * app.js
 * logica exclusiva do dashboard em tempo real
 * depende de auth.js
 */

// constantes de layout
// Espelham config.py:LIMITE_X_CM / LIMITE_Y_CM.
// Se as dimensões físicas mudarem, alterar também em config.py.
const LIMITE_X_CM = 760;
const LIMITE_Y_CM = 500;
const MAX_RASTO_PONTOS = 5000;   // I-05: cap do heatmap

// estado do modulo
const canvas = document.getElementById("mapaFabrica");
const ctx = canvas ? canvas.getContext("2d") : null;

let imagemMapa = new Image();
let loopAtualizacao = null;
let loopAtualizacaoKpis = null;
let modoRastoAtivo = false;
let historicoRasto = [];

// autenticacao e login

async function fazerLogin() {
    const user = document.getElementById("username").value;
    const pass = document.getElementById("password").value;
    const erroTexto = document.getElementById("mensagem_erro");

    const formData = new URLSearchParams();
    formData.append("username", user);
    formData.append("password", pass);

    try {
        const resposta = await fetch("/login", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: formData.toString(),
        });

        if (resposta.ok) {
            const dados = await resposta.json();
            localStorage.setItem("cracha_jwt", dados.access_token);
            localStorage.setItem("tenant_id", dados.tenant_id);
            localStorage.setItem("login_timestamp", new Date().toISOString());
            erroTexto.innerText = "";
            mudarParaDashboard();
        } else {
            erroTexto.innerText = "Credenciais inválidas. Acesso negado.";
        }
    } catch {
        erroTexto.innerText = "Erro ao contactar o servidor.";
    }
}

async function mudarParaDashboard() {
    document.getElementById("seccao_login").classList.add("escondido");
    document.getElementById("seccao_dashboard").classList.remove("escondido");

    const painelDiretor = document.getElementById("painel_diretor");
    painelDiretor.style.display = "flex";
    painelDiretor.classList.remove("escondido");

    await obterPosicoes();
    atualizarKpisDiretor();

    loopAtualizacao = setInterval(obterPosicoes, 2000);
    if (!loopAtualizacaoKpis) {
        loopAtualizacaoKpis = setInterval(atualizarKpisDiretor, 60000);
    }
}

function fazerLogout() {
    clearInterval(loopAtualizacao);
    if (loopAtualizacaoKpis) {
        clearInterval(loopAtualizacaoKpis);
        loopAtualizacaoKpis = null;
    }
    localStorage.removeItem("cracha_jwt");
    localStorage.removeItem("tenant_id");
    localStorage.removeItem("login_timestamp");

    document.getElementById("seccao_dashboard").classList.add("escondido");
    document.getElementById("painel_diretor").style.display = "none";
    document.getElementById("painel_diretor").classList.add("escondido");
    document.getElementById("seccao_login").classList.remove("escondido");
}

// restaura sessao apos refresh
window.onload = function () {
    if (obterToken()) mudarParaDashboard();
};

// dados em tempo real

async function obterPosicoes() {
    const token = obterToken();
    if (!token) { fazerLogout(); return; }

    try {
        const resposta = await fetch("/posicoes", {
            headers: { "Authorization": "Bearer " + token },
        });

        if (resposta.ok) {
            const pacoteDados = await resposta.json();
            document.getElementById("nome_cliente").innerText = pacoteDados.cliente;
            atualizarPainelBaterias(pacoteDados.dados);
            atualizarPainelAlertas(pacoteDados.dados);

            const caminhoCorreto = `/static/assets/mapa_${pacoteDados.cliente}.png`;
            if (!imagemMapa.src.includes(caminhoCorreto)) {
                imagemMapa.src = caminhoCorreto;
                imagemMapa.onload = () => desenharFabrica(pacoteDados);
            } else {
                desenharFabrica(pacoteDados);
            }
        } else {
            // Q-08: null-guard — #consola_dados não existe no HTML actual
            const consola = document.getElementById("consola_dados");
            if (consola) consola.innerText = "Erro de autenticação. Por favor, saia e entre de novo.";
            fazerLogout();
        }
    } catch (erro) {
        console.error("Erro ao comunicar com o servidor:", erro);
    }
}

// kpis do painel do diretor

async function atualizarKpisDiretor() {
    const tenant = document.getElementById("nome_cliente")?.innerText?.trim();
    const token = obterToken();
    if (!tenant || !token) return;

    const secao = document.getElementById("seccao_dashboard");
    if (secao?.classList.contains("escondido")) return;

    try {
        const resposta = await fetch(`/kpis/${encodeURIComponent(tenant)}`, {
            headers: { "Authorization": "Bearer " + token },
        });
        const dados = await resposta.json();

        if (dados.sucesso) {
            document.getElementById("kpi-distancia").innerText = dados.kpis.distancia_percorrida_metros + " m";
            document.getElementById("kpi-utilizacao").innerText = dados.kpis.taxa_utilizacao_perc + " %";
            document.getElementById("kpi-bateria").innerText = dados.kpis.bateria_media_frota_perc + " %";
        }
    } catch (erro) {
        console.error("Erro ao carregar KPIs do painel:", erro);
    }
}

// motor grafico

function desenharFabrica(pacoteDados) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (imagemMapa.complete && imagemMapa.naturalWidth !== 0) {
        ctx.drawImage(imagemMapa, 0, 0, canvas.width, canvas.height);
    }

    // modo rasto
    if (modoRastoAtivo) {
        ctx.fillStyle = "rgba(255, 0, 0, 0.15)";
        historicoRasto.forEach(p => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    // filtro temporal para historico e tempo real
    const sliderEl = document.getElementById("sliderTempo");
    const sliderValor = sliderEl ? parseInt(sliderEl.value) : 480;
    const minutosAtras = 480 - sliderValor;
    const isHistorico = minutosAtras > 0;

    const agora = new Date();
    if (isHistorico) agora.setMinutes(agora.getMinutes() - minutosAtras);

    const loginTs = localStorage.getItem("login_timestamp")
        ? new Date(localStorage.getItem("login_timestamp"))
        : null;

    const tagsAtivas = pacoteDados.dados.filter(tag => {
        if (isHistorico) return true;
        const ultimaLeitura = new Date(tag.timestamp);
        return !(loginTs && ultimaLeitura < loginTs);
    });

    // desenha cada tag no canvas
    tagsAtivas.forEach(tag => {
        const pixelX = (tag.x * canvas.width) / LIMITE_X_CM;
        const pixelY = (tag.y * canvas.height) / LIMITE_Y_CM;

        // limita o array de rasto para nao degradar performance
        if (modoRastoAtivo) {
            historicoRasto.push({ x: pixelX, y: pixelY });
            if (historicoRasto.length > MAX_RASTO_PONTOS) {
                historicoRasto.splice(0, historicoRasto.length - MAX_RASTO_PONTOS);
            }
        }

        // desenha circulo de incerteza para sinal perdido
        const ultimaLeitura = new Date(tag.timestamp);
        const tempoSemSinalSegundos = (agora - ultimaLeitura) / 1000;

        if (tempoSemSinalSegundos > 10) {
            const raioIncerteza = Math.min(10 + tempoSemSinalSegundos * 0.5, 50);
            ctx.beginPath();
            ctx.arc(pixelX, pixelY, raioIncerteza, 0, 2 * Math.PI);
            ctx.fillStyle = "rgba(255, 165, 0, 0.3)";
            ctx.fill();
        }

        // configura cor e tamanho mediante estado da tag
        let raioTag = 8;
        let corPreenchimento = "#007bff";
        let corBorda = "#ffffff";

        if (tag.status !== null && tag.status !== "Normal") {
            raioTag = 12;
            corBorda = "#dc3545";
            const piscar = new Date().getMilliseconds() < 500;
            corPreenchimento = piscar ? "#dc3545" : "#ffffff";
        }

        ctx.beginPath();
        ctx.arc(pixelX, pixelY, raioTag, 0, 2 * Math.PI);
        ctx.fillStyle = corPreenchimento;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = corBorda;
        ctx.stroke();

        ctx.fillStyle = "#000000";
        ctx.font = "12px Arial";
        ctx.fillText(tag.tag_id, pixelX + 12, pixelY + 4);
    });
}

// paineis laterais

function atualizarPainelBaterias(dadosTags) {
    const lista = document.getElementById("lista_baterias");
    const tags = dadosTags.filter(t => t.bateria !== null)
        .sort((a, b) => a.bateria - b.bateria);

    lista.innerHTML = "";
    if (tags.length === 0) {
        lista.innerHTML = '<li class="placeholder">Nenhuma tag online.</li>';
        return;
    }

    tags.forEach(tag => {
        const cor = tag.bateria <= 5 ? "red"
            : tag.bateria <= 20 ? "#fd7e14"
                : "#28a745";
        const peso = tag.bateria <= 20 ? "bold" : "normal";
        const li = document.createElement("li");
        li.innerHTML = `Tag <strong>${tag.tag_id}</strong>: <span style="color:${cor};font-weight:${peso};">${tag.bateria}%</span>`;
        lista.appendChild(li);
    });
}

function atualizarPainelAlertas(dadosTags) {
    const lista = document.getElementById("lista_alertas");
    const emPanico = dadosTags.filter(t => t.status !== null && t.status !== "Normal");

    lista.innerHTML = "";
    if (emPanico.length === 0) {
        lista.innerHTML = '<li class="placeholder">Nenhum alerta ativo. Sistema normal.</li>';
        return;
    }

    emPanico.forEach(tag => {
        const li = document.createElement("li");
        li.innerHTML = `🚨 <strong>EMERGÊNCIA:</strong> Tag <span style="color:#dc3545;font-weight:bold;">${tag.tag_id}</span> acionou o alarme!`;
        lista.appendChild(li);
    });
}

// modo rasto e heatmap

const checkRastoEl = document.getElementById("checkRasto");
if (checkRastoEl) {
    checkRastoEl.addEventListener("change", function () {
        modoRastoAtivo = this.checked;
        if (!modoRastoAtivo) {
            historicoRasto = [];
            if (imagemMapa.complete && imagemMapa.naturalWidth !== 0) {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(imagemMapa, 0, 0, canvas.width, canvas.height);
            }
        }
    });
}

// viagem no tempo digital twin

const sliderTempo = document.getElementById("sliderTempo");
const labelMinutos = document.getElementById("labelMinutos");

if (sliderTempo) {
    sliderTempo.addEventListener("input", function () {
        const valorSlider = parseInt(this.value);
        const minutosAtras = 480 - valorSlider;
        const divMapa = document.getElementById("wrapperMapa");

        if (minutosAtras === 0) {
            if (labelMinutos) {
                labelMinutos.innerText = "Tempo Real";
                labelMinutos.style.color = "#0d6efd";
            }
            divMapa?.classList.remove("piscar-vermelho");

            if (!loopAtualizacao) {
                obterPosicoes();
                loopAtualizacao = setInterval(obterPosicoes, 2000);
            }
        } else {
            const horaHistorico = new Date();
            horaHistorico.setMinutes(horaHistorico.getMinutes() - minutosAtras);
            const horaFormatada = horaHistorico.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" });

            if (labelMinutos) {
                labelMinutos.innerText = `Visualizando: ${horaFormatada}`;
                labelMinutos.style.color = "#dc3545";
            }
            divMapa?.classList.add("piscar-vermelho");

            if (loopAtualizacao) {
                clearInterval(loopAtualizacao);
                loopAtualizacao = null;
            }
            verPassado(minutosAtras);
        }
    });
}

async function verPassado(minutos) {
    const token = obterToken();
    if (!token) { fazerLogout(); return; }

    try {
        const resposta = await fetch(`/historico?minutos_atras=${minutos}`, {
            headers: { "Authorization": "Bearer " + token },
        });
        if (resposta.ok) {
            desenharFabrica(await resposta.json());
        } else {
            console.error("Erro ao obter dados do histórico.");
        }
    } catch (erro) {
        console.error("Erro na comunicação para histórico:", erro);
    }
}