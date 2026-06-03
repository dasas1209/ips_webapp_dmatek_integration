const cfg = window.RUNTIME_CONFIG || {};
const MAX_RASTO_PONTOS = cfg.map?.maxRastoPontos ?? 5000;
const TEMPO_OFFLINE_SEG = cfg.timing?.tempoOfflineSeg ?? 10;

const canvas = document.getElementById("mapaFabrica");
const ctx = canvas ? canvas.getContext("2d") : null;

const state = {
    imagemMapa: new Image(),
    loopAtualizacao: null,
    loopAtualizacaoKpis: null,
    modoRastoAtivo: false,
    historicoRasto: [],
    dadosFiltrados: [],
    dadosCompletos: [],
    tenant: "",
    ultimoToastPorTag: new Map(),
    alertasCriticos: [],
    totalAssetsSql: 0,
    mapasDisponiveis: [],
    mapaAtivo: null,
};

const els = {
    formLogin: document.getElementById("formLogin"),
    msgErro: document.getElementById("mensagem_erro"),
    login: document.getElementById("seccao_login"),
    dashboard: document.getElementById("seccao_dashboard"),
    topbarUser: document.getElementById("utilizadorAtivo"),
    tenantNameSidebar: document.getElementById("tenantNameSidebar"),
    tenantAvatar: document.getElementById("tenantAvatar"),
    estadoLigacao: document.getElementById("estadoLigacao"),
    filtroMapa: document.getElementById("filtroMapa"),
    metricaTotal: document.getElementById("metricaTotal"),
    metricaAtivos: document.getElementById("metricaAtivos"),
    metricaAlertas: document.getElementById("metricaAlertas"),
    badgeNotificacoes: document.getElementById("badgeNotificacoes"),
    corpoTabela: document.getElementById("corpoTabelaAssets"),
    tabelaResumo: document.getElementById("tabelaResumo"),
    assetDetailBody: document.getElementById("assetDetailBody"),
    sliderTempo: document.getElementById("sliderTempo"),
    labelMinutos: document.getElementById("labelMinutos"),
    checkRasto: document.getElementById("checkRasto"),
    mapOverlayState: document.getElementById("mapOverlayState"),
    wrapperMapa: document.getElementById("wrapperMapa"),
    toastContainer: document.getElementById("toastContainer"),
    metricasTopo: document.getElementById("metricasTopo"),
    btnNotificacoes: document.getElementById("btnNotificacoes"),
    dropdownNotificacoes: document.getElementById("dropdownNotificacoes"),
    notificacoesWrap: document.getElementById("notificacoesWrap"),
};

function setThemeTenant(tenant) {
    const tenantId = String(tenant || "").toLowerCase();
    const temas = cfg.tenantTheme?.byTenantId || {};
    const cor = temas[tenantId] || cfg.tenantTheme?.defaultPrimary || "#3b82f6";

    document.documentElement.style.setProperty("--tenant-primary", cor);
    document.documentElement.style.setProperty("--tenant-primary-soft", `${cor}22`);
}

async function fazerLogin(event) {
    event.preventDefault();
    const user = document.getElementById("username").value.trim();
    const pass = document.getElementById("password").value;

    const formData = new URLSearchParams();
    formData.append("username", user);
    formData.append("password", pass);

    try {
        const resposta = await fetch(cfg.api?.loginPath || "/login", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: formData.toString(),
        });

        if (!resposta.ok) {
            els.msgErro.textContent = "Credenciais inválidas. Verifique os dados e tente novamente.";
            return;
        }

        const dados = await resposta.json();
        localStorage.setItem("cracha_jwt", dados.access_token);
        localStorage.setItem("tenant_id", dados.tenant_id);
        localStorage.setItem("tenant_nome", dados.tenant_nome || dados.tenant_id);
        if (dados.logo_url) {
            localStorage.setItem("tenant_logo_url", dados.logo_url);
        } else {
            localStorage.removeItem("tenant_logo_url");
        }
        localStorage.setItem("is_admin", dados.is_admin ? "true" : "false");
        localStorage.setItem("role", dados.role || "user");
        localStorage.setItem("login_timestamp", new Date().toISOString());

        els.msgErro.textContent = "";

        if (dados.role === "superadmin" || dados.role === "admin") {
            window.location.href = "/admin.html";
            return;
        }

        await mudarParaDashboard();
    } catch {
        els.msgErro.textContent = "Não foi possível contactar o servidor.";
    }
}

async function mudarParaDashboard() {
    els.login.classList.add("escondido");
    els.dashboard.classList.remove("escondido");

    const tenant = obterTenantId();
    if (!tenant) {
        fazerLogout();
        return;
    }
    const utilizador = obterNomeUtilizador();
    els.topbarUser.textContent = `Utilizador: ${utilizador}`;

    await carregarBrandingTenant();
    setThemeTenant(tenant);

    await carregarMapasDoServidor();

    await obterPosicoes();
    await atualizarKpisDiretor();

    if (state.loopAtualizacao) clearInterval(state.loopAtualizacao);
    state.loopAtualizacao = setInterval(obterPosicoes, cfg.timing?.refreshPosicoesMs ?? 2000);

    if (state.loopAtualizacaoKpis) clearInterval(state.loopAtualizacaoKpis);
    state.loopAtualizacaoKpis = setInterval(atualizarKpisDiretor, cfg.timing?.refreshKpisMs ?? 60000);
}

function setTenantInfo(tenant, nomeOverride, logoOverride) {
    state.tenant = tenant;
    const tenantNome = nomeOverride || localStorage.getItem("tenant_nome") || tenant;
    const logoUrl = logoOverride !== undefined
        ? logoOverride
        : (localStorage.getItem("tenant_logo_url") || null);

    els.tenantNameSidebar.textContent = tenantNome;
    if (window.ASSET_PATHS?.aplicarAvatarElemento) {
        window.ASSET_PATHS.aplicarAvatarElemento(els.tenantAvatar, tenantNome, logoUrl);
    } else {
        els.tenantAvatar.textContent = tenantNome.slice(0, 2).toUpperCase();
    }
}

async function carregarBrandingTenant() {
    const token = obterToken();
    if (!token) return;
    try {
        const resp = await fetch("/api/tenant/branding", {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) return;
        const dados = await resp.json();
        localStorage.setItem("tenant_nome", dados.nome || dados.tenant_id);
        if (dados.logo_url) {
            localStorage.setItem("tenant_logo_url", dados.logo_url);
        } else {
            localStorage.removeItem("tenant_logo_url");
        }
        setTenantInfo(dados.tenant_id, dados.nome, dados.logo_url || null);
    } catch {
        /* mantem cache local */
    }
}

function fazerLogout() {
    const token = obterToken();
    if (token) {
        fetch('/logout', {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {});
    }

    clearInterval(state.loopAtualizacao);
    clearInterval(state.loopAtualizacaoKpis);
    state.loopAtualizacao = null;
    state.loopAtualizacaoKpis = null;

    localStorage.removeItem("cracha_jwt");
    localStorage.removeItem("tenant_id");
    localStorage.removeItem("tenant_nome");
    localStorage.removeItem("is_admin");
    localStorage.removeItem("role");
    localStorage.removeItem("tenant_logo_url");
    localStorage.removeItem("login_timestamp");

    els.dashboard.classList.add("escondido");
    els.login.classList.remove("escondido");
}

async function obterPosicoes() {
    const token = obterToken();
    if (!token) {
        fazerLogout();
        return;
    }

    try {
        const resposta = await fetch(cfg.api?.posicoesPath || "/posicoes", {
            headers: { Authorization: "Bearer " + token },
        });

        if (resposta.status === 401 || resposta.status === 403) {
            setOverlayState("Sessão inválida. Autentique-se novamente.");
            els.estadoLigacao.textContent = "Sessão expirada.";
            fazerLogout();
            return;
        }

        if (!resposta.ok) {
            setOverlayState("Sem ligação aos dados em tempo real.");
            els.estadoLigacao.textContent = "Ligação interrompida. A tentar novamente...";
            return;
        }

        const pacoteDados = await resposta.json();
        setOverlayState("");
        els.estadoLigacao.textContent = `Ligado. Última atualização: ${new Date().toLocaleTimeString("pt-PT")}`;

        if (pacoteDados.tenant_id && pacoteDados.tenant_id !== state.tenant) {
            setOverlayState("Tenant de sessão inconsistente.");
            els.estadoLigacao.textContent = "A terminar sessão por segurança.";
            fazerLogout();
            return;
        }

        if (pacoteDados.total_tags_sql !== undefined) {
            state.totalAssetsSql = pacoteDados.total_tags_sql;
        }

        const normalizados = normalizarAssets(pacoteDados.dados || []);
        state.dadosCompletos = filtrarDadosSessaoTempoReal(normalizados);
        state.dadosFiltrados = aplicarFiltros(state.dadosCompletos);

        state.alertasCriticos = state.dadosCompletos.filter((a) => a.critico);
        renderizarDropdownNotificacoes();

        renderizarTabela(state.dadosFiltrados);
        renderizarMetricas();
        desenharFabrica(state.dadosFiltrados);
        renderizarDetalhesSelecionados();
        gerarToastsCriticos(state.dadosCompletos);
    } catch {
        setOverlayState("Sem ligação ao servidor.");
        els.estadoLigacao.textContent = "Sem ligação ao servidor.";
    }
}

function normalizarAssets(dados) {
    return dados.map((tag) => {
        const mapaOriginal = tag.mapa || tag.zone || tag.zona || null;
        const nome = tag.nome || tag.name || tag.tag_id;
        const ts = new Date(tag.timestamp);
        const agora = new Date();
        const online = (agora - ts) / 1000 <= TEMPO_OFFLINE_SEG;

        return {
            ...tag,
            mapaOriginal,
            nome,
            online,
            critico: tag.status !== null && tag.status !== "Normal",
            bateria: tag.bateria ?? null,
        };
    });
}

function filtrarDadosSessaoTempoReal(dados) {
    // todos os assets sao mostrados independentemente da hora de login — offline ficam visiveis na tabela
    return dados;
}

async function carregarMapasDoServidor() {
    const token = obterToken();
    if (!token) return;
    try {
        const resp = await fetch("/api/mapas", { headers: { Authorization: "Bearer " + token } });
        if (!resp.ok) return;
        state.mapasDisponiveis = await resp.json();

        const opcoes = state.mapasDisponiveis.map(m => `<option value="${m.id}">${m.nome}</option>`);
        if (opcoes.length === 0) {
            els.filtroMapa.innerHTML = '<option value="">Sem Mapas</option>';
            state.mapaAtivo = null;
        } else {
            els.filtroMapa.innerHTML = opcoes.join("");
            state.mapaAtivo = state.mapasDisponiveis[0];
        }
        carregarImagemDoMapaAtivo();
    } catch (e) {
        console.error("Erro ao carregar mapas", e);
    }
}

function aplicarFiltros(dados) {
    if (!state.mapaAtivo) return dados;
    return dados.filter((asset) => !asset.mapaOriginal || asset.mapaOriginal === state.mapaAtivo.nome).map(asset => ({
        ...asset,
        mapa: asset.mapaOriginal || state.mapaAtivo.nome
    }));
}

async function atualizarKpisDiretor() {
    const token = obterToken();
    if (!token || els.dashboard.classList.contains("escondido")) return;

    try {
        const resposta = await fetch(cfg.api?.kpisPath || "/kpis", {
            headers: { Authorization: "Bearer " + token },
        });
        const dados = await resposta.json();
        if (!dados.sucesso) return;

        const ativosAgora = state.dadosCompletos.filter((a) => a.online).length;
        const alertas = state.dadosCompletos.filter((a) => a.critico).length;

        state.totalAssetsSql = dados.kpis?.total_assets ?? state.totalAssetsSql;

        els.metricaTotal.textContent = String(state.totalAssetsSql);
        els.metricaAtivos.textContent = String(ativosAgora);
        els.metricaAlertas.textContent = String(alertas);
        els.metricasTopo.classList.add("loaded");
    } catch {
        renderizarMetricas();
    }
}

function renderizarMetricas() {
    const ativos = state.dadosCompletos.filter((a) => a.online).length;
    const alertas = state.dadosCompletos.filter((a) => a.critico).length;

    els.metricaTotal.textContent = String(state.totalAssetsSql || state.dadosCompletos.length);
    els.metricaAtivos.textContent = String(ativos);
    els.metricaAlertas.textContent = String(alertas);
    els.badgeNotificacoes.textContent = String(alertas);

    els.metricasTopo.classList.add("loaded");
}

function setOverlayState(texto) {
    if (!texto) {
        els.mapOverlayState.classList.add("escondido");
        els.mapOverlayState.textContent = "";
        return;
    }
    els.mapOverlayState.classList.remove("escondido");
    els.mapOverlayState.textContent = texto;
}

function desenharFabrica(assets) {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!state.mapaAtivo) {
        setOverlayState("Nenhum mapa associado ao tenant. Configure um mapa no admin para ver a representação.");
        return;
    }

    if (state.imagemMapa.complete && state.imagemMapa.naturalWidth > 0) {
        ctx.drawImage(state.imagemMapa, 0, 0, canvas.width, canvas.height);
    }

    if (state.modoRastoAtivo) {
        ctx.fillStyle = "rgba(255, 0, 0, 0.15)";
        state.historicoRasto.forEach((p) => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    const minutosAtras = obterMinutosAtras();
    const isHistorico = minutosAtras > 0;
    const agora = new Date();
    if (isHistorico) agora.setMinutes(agora.getMinutes() - minutosAtras);

    const limiteX = Number(state.mapaAtivo.limite_x);
    const limiteY = Number(state.mapaAtivo.limite_y);
    if (!limiteX || !limiteY) {
        setOverlayState("Mapa configurado sem limites válidos.");
        return;
    }

    assets.forEach((tag) => {
        const px = (tag.x * canvas.width) / limiteX;
        const py = (tag.y * canvas.height) / limiteY;

        if (state.modoRastoAtivo) {
            state.historicoRasto.push({ x: px, y: py });
            if (state.historicoRasto.length > MAX_RASTO_PONTOS) {
                state.historicoRasto.splice(0, state.historicoRasto.length - MAX_RASTO_PONTOS);
            }
        }

        const ultimaLeitura = new Date(tag.timestamp);
        const tempoSemSinalSegundos = (agora - ultimaLeitura) / 1000;
        if (tempoSemSinalSegundos > TEMPO_OFFLINE_SEG) {
            const raioIncerteza = Math.min(
                (cfg.map?.baseRaioIncertezaPx ?? 10) + tempoSemSinalSegundos * (cfg.map?.crescimentoRaioIncertezaPx ?? 0.5),
                cfg.map?.maxRaioIncertezaPx ?? 50
            );
            ctx.beginPath();
            ctx.arc(px, py, raioIncerteza, 0, 2 * Math.PI);
            ctx.fillStyle = "rgba(255, 165, 0, 0.3)";
            ctx.fill();
        }

        let raioTag = 8;
        let corPreenchimento = "#007bff";
        let corBorda = "#ffffff";

        if (tag.critico) {
            raioTag = 12;
            corBorda = "#dc3545";
            const piscar = new Date().getMilliseconds() < 500;
            corPreenchimento = piscar ? "#dc3545" : "#ffffff";
        }

        ctx.beginPath();
        ctx.arc(px, py, raioTag, 0, Math.PI * 2);
        ctx.fillStyle = corPreenchimento;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = corBorda;
        ctx.stroke();

        ctx.fillStyle = "#0f172a";
        ctx.font = "600 12px Inter";
        ctx.fillText(tag.nome || tag.tag_id, px + 10, py + 4);
    });
}

function renderizarTabela(dados) {
    els.corpoTabela.innerHTML = "";

    if (dados.length === 0) {
        els.corpoTabela.innerHTML = '<tr><td colspan="6"><div class="state-card">Sem dados para os filtros selecionados.</div></td></tr>';
        els.tabelaResumo.textContent = "Sem dados para apresentar.";
        return;
    }

    const rows = dados.map((asset) => {
        const selected = state.selectedAssetId === asset.tag_id ? "selected-row" : "";
        const estadoTxt = asset.online ? "Online" : "Sem sinal";
        const dotClass = asset.online ? "live-dot" : "live-dot offline";
        const bateria = asset.bateria === null ? "-" : `${asset.bateria}%`;
        const ultima = new Date(asset.timestamp).toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

        return `
            <tr class="${selected}" data-asset-id="${asset.tag_id}">
                <td>${asset.tag_id}</td>
                <td>${asset.nome}</td>
                <td>${asset.mapa}</td>
                <td><span class="live-status"><span class="${dotClass}"></span>${estadoTxt}</span></td>
                <td>${bateria}</td>
                <td>${ultima}</td>
            </tr>
        `;
    });

    els.corpoTabela.innerHTML = rows.join("");
    els.tabelaResumo.textContent = `${dados.length} assets apresentados.`;
}

function selecionarAsset(tagId) {
    state.selectedAssetId = tagId;
    renderizarTabela(state.dadosFiltrados);
    renderizarDetalhesSelecionados();
    desenharFabrica(state.dadosFiltrados);
}

function renderizarDetalhesSelecionados() {
    const asset = state.dadosFiltrados.find((a) => a.tag_id === state.selectedAssetId);
    if (!asset) {
        els.assetDetailBody.className = "asset-detail-body empty-state-card";
        els.assetDetailBody.innerHTML = "<h3>Nenhum asset selecionado</h3><p>Selecione um ponto no mapa ou uma linha na tabela para abrir os detalhes operacionais.</p>";
        return;
    }

    els.assetDetailBody.className = "asset-detail-body";
    const bateria = asset.bateria === null ? "Sem leitura" : `${asset.bateria}%`;
    const estado = asset.critico ? "Alerta crítico" : asset.online ? "Operacional" : "Sem sinal";

    els.assetDetailBody.innerHTML = `
        <h3>${asset.tag_id}</h3>
        <p class="muted">Atualizado em ${new Date(asset.timestamp).toLocaleString("pt-PT")}</p>
        <div class="detail-grid">
            <div class="detail-item"><strong>Estado</strong><br>${estado}</div>
            <div class="detail-item"><strong>Bateria</strong><br>${bateria}</div>
            <div class="detail-item"><strong>Mapa</strong><br>${asset.mapa}</div>
            <div class="detail-item"><strong>Nome</strong><br>${asset.nome}</div>
            <div class="detail-item"><strong>Posição X</strong><br>${asset.x}</div>
            <div class="detail-item"><strong>Posição Y</strong><br>${asset.y}</div>
        </div>
    `;
}

function gerarToastsCriticos(dados) {
    const criticos = dados.filter((a) => a.critico);
    criticos.forEach((asset) => {
        const agora = Date.now();
        const ultimo = state.ultimoToastPorTag.get(asset.tag_id) || 0;
        if (agora - ultimo < (cfg.timing?.toastCooldownMs ?? 15000)) return;

        state.ultimoToastPorTag.set(asset.tag_id, agora);
        criarToast(`Alerta crítico em ${asset.tag_id}. Verifique o estado imediatamente.`, true);
    });
}

function criarToast(mensagem, critico = false) {
    const toast = document.createElement("div");
    toast.className = `toast${critico ? " critico" : ""}`;
    toast.textContent = mensagem;
    els.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-8px)";
        setTimeout(() => toast.remove(), cfg.timing?.toastFadeMs ?? 180);
    }, cfg.timing?.toastVisibleMs ?? 4200);
}

function renderizarDropdownNotificacoes() {
    if (state.alertasCriticos.length === 0) {
        els.dropdownNotificacoes.innerHTML = '<p class="notificacao-vazia">Nenhum alerta crítico ativo.</p>';
        return;
    }

    els.dropdownNotificacoes.innerHTML = state.alertasCriticos
        .map((asset) => `<button class="notificacao-item" data-alerta-tag="${asset.tag_id}">Tag ${asset.tag_id} acionou alarme.</button>`)
        .join("");
}

function toggleDropdownNotificacoes(forcarFechar = false) {
    if (forcarFechar) {
        els.dropdownNotificacoes.classList.add("escondido");
        els.btnNotificacoes.setAttribute("aria-expanded", "false");
        return;
    }

    const aberto = !els.dropdownNotificacoes.classList.contains("escondido");
    els.dropdownNotificacoes.classList.toggle("escondido", aberto);
    els.btnNotificacoes.setAttribute("aria-expanded", aberto ? "false" : "true");
}

function obterMinutosAtras() {
    return 480 - parseInt(els.sliderTempo.value, 10);
}

async function verPassado(minutos) {
    const token = obterToken();
    if (!token) return;
    const resp = await fetch(`${cfg.api?.historicoPath || "/historico"}?minutos_atras=${minutos}`, {
        headers: { Authorization: "Bearer " + token },
    });
    if (!resp.ok) return;

    const pacote = await resp.json();
    const dados = normalizarAssets(pacote.dados || []);
    state.dadosCompletos = dados;
    state.dadosFiltrados = aplicarFiltros(dados);
    state.alertasCriticos = state.dadosCompletos.filter((a) => a.critico);
    renderizarDropdownNotificacoes();
    renderizarTabela(state.dadosFiltrados);
    renderizarMetricas();
    desenharFabrica(state.dadosFiltrados);
}

function configurarEventos() {
    els.formLogin?.addEventListener("submit", fazerLogin);
    document.getElementById("btnLogout")?.addEventListener("click", fazerLogout);
    document.getElementById("btnAtualizar")?.addEventListener("click", obterPosicoes);

    document.getElementById("btnContaSettings")?.addEventListener("click", () => {
        const m = document.getElementById("modalContaSettings");
        if (!m) return;
        document.getElementById("settingsNewUsername").value = "";
        document.getElementById("settingsNewPassword").value = "";
        document.getElementById("settingsCurrentPassword").value = "";
        document.getElementById("settingsErro").textContent = "";
        m.style.display = "flex";
    });

    function fecharContaModal() {
        const m = document.getElementById("modalContaSettings");
        if (m) m.style.display = "none";
    }
    document.getElementById("btnFecharContaModal")?.addEventListener("click", fecharContaModal);
    document.getElementById("btnCancelarContaModal")?.addEventListener("click", fecharContaModal);
    document.getElementById("modalContaSettings")?.addEventListener("click", (e) => {
        if (e.target === e.currentTarget) fecharContaModal();
    });

    document.getElementById("formContaSettings")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const token = obterToken();
        const erroEl = document.getElementById("settingsErro");
        erroEl.textContent = "";

        const body = {
            current_password: document.getElementById("settingsCurrentPassword").value,
        };
        const newUser = document.getElementById("settingsNewUsername").value.trim();
        const newPass = document.getElementById("settingsNewPassword").value;
        if (newUser) body.new_username = newUser;
        if (newPass) body.new_password = newPass;

        if (!body.new_username && !body.new_password) {
            erroEl.textContent = "Indica pelo menos um campo a alterar.";
            return;
        }

        try {
            const resp = await fetch("/api/user/credentials", {
                method: "PUT",
                headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
                body: JSON.stringify(body)
            });
            const dados = await resp.json();
            if (!resp.ok) {
                erroEl.textContent = dados.detail || "Erro ao gravar.";
                return;
            }
            fecharContaModal();
            if (dados.username_changed) {
                alert("Username alterado. Serás redireccionado para o login.");
                fazerLogout();
            } else {
                criarToast("Password atualizada com sucesso!");
            }
        } catch {
            erroEl.textContent = "Não foi possível contactar o servidor.";
        }
    });

    els.filtroMapa?.addEventListener("change", () => {
        const mapId = parseInt(els.filtroMapa.value, 10);
        state.mapaAtivo = state.mapasDisponiveis.find(m => m.id === mapId) || null;
        carregarImagemDoMapaAtivo();
        state.dadosFiltrados = aplicarFiltros(state.dadosCompletos);
        renderizarTabela(state.dadosFiltrados);
        desenharFabrica(state.dadosFiltrados);
        renderizarDetalhesSelecionados();
    });

    els.corpoTabela?.addEventListener("click", (event) => {
        const row = event.target.closest("tr[data-asset-id]");
        if (!row) return;
        selecionarAsset(row.dataset.assetId);
    });

    els.btnNotificacoes?.addEventListener("click", (event) => {
        event.stopPropagation();
        toggleDropdownNotificacoes();
    });

    els.dropdownNotificacoes?.addEventListener("click", (event) => {
        const item = event.target.closest("[data-alerta-tag]");
        if (!item) return;
        selecionarAsset(item.dataset.alertaTag);
        toggleDropdownNotificacoes(true);
    });

    document.addEventListener("click", (event) => {
        if (!els.notificacoesWrap.contains(event.target)) {
            toggleDropdownNotificacoes(true);
        }
    });

    canvas?.addEventListener("click", (event) => {
        const rect = canvas.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
        const y = ((event.clientY - rect.top) / rect.height) * canvas.height;

        let candidato = null;
        let melhorDist = Number.POSITIVE_INFINITY;

        state.dadosFiltrados.forEach((asset) => {
            const px = (asset.x * canvas.width) / LIMITE_X_CM;
            const py = (asset.y * canvas.height) / LIMITE_Y_CM;
            const dist = Math.hypot(px - x, py - y);
            if (dist < melhorDist && dist < (cfg.map?.pickRadiusPx ?? 20)) {
                melhorDist = dist;
                candidato = asset;
            }
        });

        if (candidato) selecionarAsset(candidato.tag_id);
    });

    els.checkRasto?.addEventListener("change", (event) => {
        state.modoRastoAtivo = event.target.checked;
        if (!state.modoRastoAtivo) state.historicoRasto = [];
        desenharFabrica(state.dadosFiltrados);
    });

    els.sliderTempo?.addEventListener("input", async () => {
        const minutosAtras = obterMinutosAtras();
        if (minutosAtras === 0) {
            els.labelMinutos.textContent = "Tempo real";
            els.wrapperMapa.classList.remove("piscar-vermelho");
            if (!state.loopAtualizacao) state.loopAtualizacao = setInterval(obterPosicoes, cfg.timing?.refreshPosicoesMs ?? 2000);
            await obterPosicoes();
            return;
        }

        const ts = new Date();
        ts.setMinutes(ts.getMinutes() - minutosAtras);
        els.labelMinutos.textContent = `Visualização: ${ts.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })}`;
        els.wrapperMapa.classList.add("piscar-vermelho");

        if (state.loopAtualizacao) {
            clearInterval(state.loopAtualizacao);
            state.loopAtualizacao = null;
        }
        await verPassado(minutosAtras);
    });
}

function carregarImagemDoMapaAtivo() {
    if (!state.mapaAtivo || !state.mapaAtivo.path) {
        state.imagemMapa.src = "";
        desenharFabrica(state.dadosFiltrados);
        return;
    }

    let caminho = state.mapaAtivo.path;
    if (window.ASSET_PATHS) {
        caminho = window.ASSET_PATHS.normalizarCaminhoImagem(caminho);
    } else if (caminho.startsWith("frontend/")) {
        caminho = caminho.replace("frontend/", "/static/");
    } else if (!caminho.startsWith("/")) {
        caminho = "/" + caminho;
    }

    if (state.imagemMapa.src.includes(caminho)) return;

    state.imagemMapa.onload = () => desenharFabrica(state.dadosFiltrados);
    state.imagemMapa.onerror = () => console.error("Falha ao carregar a imagem do mapa:", caminho);
    state.imagemMapa.src = caminho;
}

window.addEventListener("load", async () => {
    configurarEventos();

    const token = obterToken();
    if (token) {
        const role = obterRole();
        if (role === "superadmin" || role === "admin") {
            window.location.href = "/admin.html";
            return;
        }
        await mudarParaDashboard();
    }
});
