// audit_log.js — log global de acoes (superadmin)

const ACOES_LABEL = {
    // sessao
    login: "Início de sessão",
    logout: "Fim de sessão",
    credentials_updated: "Credenciais alteradas",
    // clientes (tenants)
    tenant_created: "Cliente criado",
    tenant_updated: "Cliente atualizado",
    tenant_deleted: "Cliente eliminado",
    // perfil e branding
    tenant_profile_updated: "Perfil da empresa atualizado",
    tenant_avatar_uploaded: "Avatar da empresa atualizado",
    tenant_avatar_removed: "Avatar da empresa removido",
    // utilizadores
    user_created: "Utilizador criado",
    user_updated: "Utilizador atualizado",
    user_deleted: "Utilizador eliminado",
    // mapas
    map_created: "Mapa criado",
    map_updated: "Mapa atualizado",
    map_deleted: "Mapa eliminado",
    // tags
    tag_created: "Tag criada",
    tag_deleted: "Tag eliminada",
    tag_aliases_updated: "Nomes de tags atualizados",
    // dados e relatorios
    audit_report_viewed: "Relatório de auditoria consultado",
};

const PERIODOS_MS = {
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
};

const state = {
    page: 1,
    pageSize: 50,
    total: 0,
    loading: false,
    tenants: [],
};

const els = {};

function cacheElements() {
    els.body = document.getElementById("auditLogBody");
    els.paginacaoInfo = document.getElementById("paginacaoInfo");
    els.btnAnterior = document.getElementById("btnAnterior");
    els.btnProximo = document.getElementById("btnProximo");
    els.filtroTenant = document.getElementById("filtroTenant");
    els.filtroUsername = document.getElementById("filtroUsername");
    els.filtroAcao = document.getElementById("filtroAcao");
    els.filtroDetalhes = document.getElementById("filtroDetalhes");
    els.filtroPeriodo = document.getElementById("filtroPeriodo");
    els.filtroDatasPersonalizadas = document.getElementById("filtroDatasPersonalizadas");
    els.filtroTsInicio = document.getElementById("filtroTsInicio");
    els.filtroTsFim = document.getElementById("filtroTsFim");
}

function verificarAcessoSuperadmin() {
    if (!obterToken()) {
        window.location.href = "/";
        return false;
    }
    const role = obterRole();
    if (role === "admin") {
        window.location.href = "/admin.html";
        return false;
    }
    if (role !== "superadmin") {
        window.location.href = "/app";
        return false;
    }
    return true;
}

function atualizarVisibilidadeDatasPersonalizadas() {
    const custom = els.filtroPeriodo.value === "custom";
    els.filtroDatasPersonalizadas.classList.toggle("escondido", !custom);
    els.filtroDatasPersonalizadas.setAttribute("aria-hidden", custom ? "false" : "true");
}

function datetimeLocalParaIso(val) {
    if (!val) return null;
    const dt = new Date(val);
    if (Number.isNaN(dt.getTime())) return null;
    return dt.toISOString();
}

function obterFiltrosTemporais() {
    const periodo = els.filtroPeriodo.value;

    if (periodo === "custom") {
        return {
            tsInicio: datetimeLocalParaIso(els.filtroTsInicio.value),
            tsFim: datetimeLocalParaIso(els.filtroTsFim.value),
        };
    }

    if (!periodo || !PERIODOS_MS[periodo]) {
        return { tsInicio: null, tsFim: null };
    }

    return {
        tsInicio: new Date(Date.now() - PERIODOS_MS[periodo]).toISOString(),
        tsFim: null,
    };
}

function construirQueryParams() {
    const params = new URLSearchParams();
    params.set("page", String(state.page));
    params.set("page_size", String(state.pageSize));

    const tenant = els.filtroTenant.value.trim();
    const username = els.filtroUsername.value.trim();
    const acao = els.filtroAcao.value.trim();
    const detalhes = els.filtroDetalhes.value.trim();
    const { tsInicio, tsFim } = obterFiltrosTemporais();

    if (tenant) params.set("tenant_id", tenant);
    if (username) params.set("username", username);
    if (acao) params.set("acao", acao);
    if (detalhes) params.set("detalhes", detalhes);
    if (tsInicio) params.set("ts_inicio", tsInicio);
    if (tsFim) params.set("ts_fim", tsFim);

    return params;
}

function formatarTimestamp(iso) {
    try {
        return new Date(iso).toLocaleString("pt-PT", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
    } catch {
        return iso || "—";
    }
}

function labelAcao(codigo) {
    return ACOES_LABEL[codigo] || codigo || "—";
}

function labelTenant(tenantId) {
    const t = state.tenants.find((c) => c.id === tenantId);
    if (t && t.nome && t.nome !== tenantId) {
        return `${t.nome} (${tenantId})`;
    }
    return tenantId || "—";
}

function escapeHtml(texto) {
    const div = document.createElement("div");
    div.textContent = texto ?? "";
    return div.innerHTML;
}

function mostrarEstadoLoading() {
    els.body.innerHTML = '<tr class="loading-row"><td colspan="5">A carregar registos…</td></tr>';
}

function renderizarTabela(resultados) {
    if (!resultados || resultados.length === 0) {
        els.body.innerHTML =
            '<tr><td colspan="5" class="muted" style="text-align:center;padding:28px;">Nenhum registo encontrado para os filtros aplicados.</td></tr>';
        return;
    }

    els.body.innerHTML = resultados
        .map(
            (r) => `
        <tr>
            <td>${formatarTimestamp(r.timestamp)}</td>
            <td title="${escapeHtml(r.tenant_id)}">${escapeHtml(labelTenant(r.tenant_id))}</td>
            <td>${escapeHtml(r.username)}</td>
            <td><span class="acao-badge" title="${escapeHtml(r.acao)}">${escapeHtml(labelAcao(r.acao))}</span></td>
            <td class="detalhes-cell">${escapeHtml(r.detalhes)}</td>
        </tr>`
        )
        .join("");
}

function atualizarPaginacao() {
    const totalPaginas = Math.max(1, Math.ceil(state.total / state.pageSize));
    els.paginacaoInfo.textContent = `Página ${state.page} de ${totalPaginas} (${state.total} resultados)`;
    els.btnAnterior.disabled = state.page <= 1 || state.loading;
    els.btnProximo.disabled = state.page >= totalPaginas || state.total === 0 || state.loading;
}

async function apiFetchAutenticado(url) {
    const token = obterToken();
    if (!token) return null;
    const resposta = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
    });
    if (resposta.status === 401) {
        window.location.href = "/";
        return null;
    }
    if (resposta.status === 403) {
        const role = obterRole();
        window.location.href = role === "admin" ? "/admin.html" : "/app";
        return null;
    }
    return resposta;
}

async function carregarTenants() {
    try {
        const resposta = await apiFetchAutenticado("/api/admin/tenants");
        if (!resposta?.ok) return;

        const lista = await resposta.json();
        state.tenants = Array.isArray(lista) ? lista : [];

        const opts = ['<option value="">Todos os clientes</option>'];
        state.tenants
            .slice()
            .sort((a, b) => (a.nome || a.id).localeCompare(b.nome || b.id, "pt"))
            .forEach((c) => {
                const nome = escapeHtml(c.nome || c.id);
                const id = escapeHtml(c.id);
                opts.push(`<option value="${id}">${nome} — ${id}</option>`);
            });
        els.filtroTenant.innerHTML = opts.join("");
    } catch {
        /* mantem opcao todos */
    }
}

async function carregarAuditLog() {
    state.loading = true;
    mostrarEstadoLoading();
    atualizarPaginacao();

    const token = obterToken();
    if (!token) {
        state.loading = false;
        window.location.href = "/";
        return;
    }

    let resultados = [];

    try {
        const params = construirQueryParams();
        const resposta = await fetch(`/admin/audit-log?${params.toString()}`, {
            headers: { Authorization: `Bearer ${token}` },
        });

        if (resposta.status === 401) {
            window.location.href = "/";
            return;
        }
        if (resposta.status === 403) {
            const role = obterRole();
            window.location.href = role === "admin" ? "/admin.html" : "/app";
            return;
        }

        const dados = resposta.ok
            ? await resposta.json()
            : { total: 0, page: state.page, page_size: state.pageSize, resultados: [] };

        state.total = dados.total ?? 0;
        state.page = dados.page ?? state.page;
        state.pageSize = dados.page_size ?? state.pageSize;
        resultados = dados.resultados || [];
    } catch {
        state.total = 0;
        resultados = [];
    } finally {
        state.loading = false;
        renderizarTabela(resultados);
        atualizarPaginacao();
    }
}

function aplicarFiltros() {
    state.page = 1;
    carregarAuditLog();
}

function limparFiltros() {
    els.filtroTenant.value = "";
    els.filtroUsername.value = "";
    els.filtroAcao.value = "";
    els.filtroDetalhes.value = "";
    els.filtroPeriodo.value = "";
    els.filtroTsInicio.value = "";
    els.filtroTsFim.value = "";
    atualizarVisibilidadeDatasPersonalizadas();
    state.page = 1;
    carregarAuditLog();
}

async function fazerLogout() {
    const token = obterToken();
    if (token) {
        fetch("/logout", {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {});
    }
    localStorage.removeItem("cracha_jwt");
    localStorage.removeItem("tenant_id");
    localStorage.removeItem("tenant_nome");
    localStorage.removeItem("is_admin");
    localStorage.removeItem("role");
    localStorage.removeItem("login_timestamp");
    window.location.href = "/";
}

function configurarEventos() {
    document.getElementById("btnAplicar").addEventListener("click", aplicarFiltros);

    document.getElementById("btnLimpar").addEventListener("click", limparFiltros);

    els.filtroPeriodo.addEventListener("change", () => {
        atualizarVisibilidadeDatasPersonalizadas();
        if (els.filtroPeriodo.value !== "custom") {
            els.filtroTsInicio.value = "";
            els.filtroTsFim.value = "";
        }
    });

    [els.filtroUsername, els.filtroDetalhes].forEach((input) => {
        input.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") {
                ev.preventDefault();
                aplicarFiltros();
            }
        });
    });

    els.filtroTenant.addEventListener("change", () => {
        /* aplicacao imediata ao escolher cliente */
        aplicarFiltros();
    });

    els.filtroAcao.addEventListener("change", aplicarFiltros);

    document.getElementById("btnAnterior").addEventListener("click", () => {
        if (state.page > 1) {
            state.page -= 1;
            carregarAuditLog();
        }
    });

    document.getElementById("btnProximo").addEventListener("click", () => {
        const totalPaginas = Math.ceil(state.total / state.pageSize);
        if (state.page < totalPaginas) {
            state.page += 1;
            carregarAuditLog();
        }
    });

    document.getElementById("btnVoltarAdmin").addEventListener("click", () => {
        window.location.href = "/admin.html";
    });

    document.getElementById("btnLogout").addEventListener("click", fazerLogout);

    document.getElementById("btnExportarPdf").addEventListener("click", exportarAuditLogPDF);
}

document.addEventListener("DOMContentLoaded", async () => {
    cacheElements();
    if (!verificarAcessoSuperadmin()) return;
    atualizarVisibilidadeDatasPersonalizadas();
    configurarEventos();
    await carregarTenants();
    carregarAuditLog();
});

function _resumoFiltros() {
    const periodoLabels = { "24h": "Últimas 24 horas", "7d": "Últimos 7 dias", "30d": "Últimos 30 dias" };
    const { tsInicio, tsFim } = obterFiltrosTemporais();
    const periodo = els.filtroPeriodo.value;
    const tenant  = els.filtroTenant.value.trim();
    const username = els.filtroUsername.value.trim();
    const acao    = els.filtroAcao.value.trim();
    const detalhes = els.filtroDetalhes.value.trim();

    const linhas = [
        ["Cliente",    tenant   ? labelTenant(tenant)             : "Todos"],
        ["Utilizador", username ? username                        : "Todos"],
        ["Ação",       acao     ? (ACOES_LABEL[acao] || acao)     : "Todas"],
    ];
    if (detalhes) linhas.push(["Texto nos detalhes", detalhes]);
    if (periodo === "custom") {
        linhas.push(["De",  tsInicio ? new Date(tsInicio).toLocaleString("pt-PT") : "—"]);
        linhas.push(["Até", tsFim    ? new Date(tsFim).toLocaleString("pt-PT")    : "Agora"]);
    } else {
        linhas.push(["Período", periodoLabels[periodo] || "Todo o histórico"]);
    }
    return linhas;
}

async function exportarAuditLogPDF() {
    if (typeof window.jspdf === "undefined") {
        alert("Biblioteca jsPDF não carregada. Verifique a ligação à internet.");
        return;
    }

    const btn = document.getElementById("btnExportarPdf");
    btn.disabled = true;
    btn.textContent = "A gerar PDF…";

    try {
        await PDF_UTILS.carregarLogo();

        const params = construirQueryParams();
        params.set("page", "1");
        params.set("page_size", "2000");

        const token = obterToken();
        const resposta = await fetch(`/admin/audit-log?${params.toString()}`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (!resposta.ok) {
            const detalhe = await resposta.json().catch(() => ({}));
            alert(`Erro ao obter dados para exportação (HTTP ${resposta.status}): ${JSON.stringify(detalhe.detail ?? detalhe)}`);
            return;
        }

        const dados    = await resposta.json();
        const eventos  = dados.resultados || [];
        const total    = dados.total || 0;
        const exportados = Math.min(total, 1000);

        const { jsPDF } = window.jspdf;
        const W = 210, H = 297;
        const pdf = new jsPDF("p", "mm", "a4");

        pdf.setFillColor(26, 31, 54);
        pdf.rect(0, 0, W, H, "F");

        PDF_UTILS.inserirLogo(pdf, W / 2 - 35, 12, 70, 18);

        pdf.setFillColor(255, 255, 255);
        pdf.roundedRect(20, 40, W - 40, 62, 6, 6, "F");
        pdf.setTextColor(26, 31, 54);
        pdf.setFontSize(20);
        pdf.setFont("helvetica", "bold");
        pdf.text("LOG DE AÇÕES", W / 2, 60, { align: "center" });
        pdf.text("DE UTILIZADORES", W / 2, 72, { align: "center" });
        pdf.setFontSize(12);
        pdf.setFont("helvetica", "normal");
        pdf.text("Metric4 RTLS — Sistema de Auditoria", W / 2, 83, { align: "center" });
        pdf.setFontSize(10);
        const notaTotal = total > 1000
            ? `${exportados} registos exportados (de ${total} encontrados)`
            : `${exportados} registo(s) encontrado(s)`;
        pdf.text(notaTotal, W / 2, 94, { align: "center" });

        const resumo = _resumoFiltros();
        pdf.setTextColor(200, 210, 230);
        pdf.setFontSize(9);
        let yFilt = 124;
        pdf.setFont("helvetica", "bold");
        pdf.text("FILTROS APLICADOS", W / 2, yFilt, { align: "center" });
        yFilt += 8;
        pdf.setFont("helvetica", "normal");
        resumo.forEach(([label, valor]) => {
            const valorLines = pdf.splitTextToSize(String(valor), 95);
            pdf.setTextColor(180, 200, 240);
            pdf.text(`${label}:`, 50, yFilt);
            pdf.setTextColor(255, 255, 255);
            pdf.text(valorLines, 107, yFilt);
            yFilt += 7 * valorLines.length;
        });

        pdf.setTextColor(200, 210, 230);
        pdf.setFontSize(9);
        pdf.text(`Gerado em: ${new Date().toLocaleString("pt-PT")}`, W / 2, H - 28, { align: "center" });
        pdf.setTextColor(80, 100, 140);
        pdf.setFontSize(8);
        pdf.text("Metric4 RTLS — Documento de Auditoria Confidencial", W / 2, H - 10, { align: "center" });

        const cabecalhos = ["Timestamp", "Tenant", "Utilizador", "Ação", "Detalhes"];
        const larguras   = [38, 28, 28, 38, 58];
        const xTbl = 10;
        const alturaCab = 8;
        const margemFundo = 14;
        const passoLinha = 3.1;

        const desenharCabecalho = (yTop) => {
            pdf.setFillColor(26, 31, 54);
            pdf.rect(xTbl, yTop, W - 20, alturaCab, "F");
            pdf.setTextColor(255, 255, 255);
            pdf.setFontSize(8);
            pdf.setFont("helvetica", "bold");
            let xH = xTbl + 2;
            cabecalhos.forEach((h, i) => { pdf.text(h, xH, yTop + 5.5); xH += larguras[i]; });
            return yTop + alturaCab;
        };

        const novaPaginaConteudo = (titulo) => {
            pdf.addPage("a4", "p");
            pdf.setFillColor(244, 246, 251);
            pdf.rect(0, 0, W, H, "F");
            PDF_UTILS.inserirLogo(pdf, 10, 6, 42, 10);
            pdf.setTextColor(26, 31, 54);
            pdf.setFontSize(13);
            pdf.setFont("helvetica", "bold");
            pdf.text(titulo, W / 2, 18, { align: "center" });
            pdf.setFontSize(9);
            pdf.setFont("helvetica", "normal");
            pdf.setTextColor(100, 120, 150);
            pdf.text(`${exportados} registo(s) — exportado em ${new Date().toLocaleString("pt-PT")}`, W / 2, 25, { align: "center" });
            return desenharCabecalho(30);
        };

        let y = novaPaginaConteudo("Log de Ações de Utilizadores");

        if (eventos.length === 0) {
            pdf.setTextColor(100, 120, 150);
            pdf.setFontSize(11);
            pdf.setFont("helvetica", "normal");
            pdf.text("Nenhum registo encontrado para os filtros aplicados.", W / 2, y + 20, { align: "center" });
        } else {
            eventos.forEach((ev, idx) => {
                pdf.setFontSize(7);
                const detLines  = pdf.splitTextToSize(ev.detalhes  || "—",                   larguras[4] - 2);
                const acaoLines = pdf.splitTextToSize(ACOES_LABEL[ev.acao] || ev.acao || "—", larguras[3] - 2);
                const tenLines  = pdf.splitTextToSize(labelTenant(ev.tenant_id),              larguras[1] - 2);
                const maxLinhas = Math.max(detLines.length, acaoLines.length, tenLines.length);
                const rowH = Math.max(7, 4.2 + (maxLinhas - 1) * passoLinha);

                if (y + rowH > H - margemFundo) {
                    y = novaPaginaConteudo("Log de Ações (continuação)");
                }

                pdf.setFillColor(idx % 2 === 0 ? 255 : 248, idx % 2 === 0 ? 255 : 249, idx % 2 === 0 ? 255 : 255);
                pdf.rect(xTbl, y, W - 20, rowH, "F");

                let xL = xTbl + 2;
                pdf.setFont("helvetica", "normal");
                pdf.setTextColor(40, 50, 70);

                pdf.setFontSize(7.5);
                pdf.text(formatarTimestamp(ev.timestamp), xL, y + 4.5);
                xL += larguras[0];

                let yM = y + 3.6;
                pdf.setFontSize(7);
                tenLines.forEach((l) => { pdf.text(l, xL, yM); yM += passoLinha; });
                xL += larguras[1];

                pdf.setFontSize(7.5);
                pdf.text(ev.username || "—", xL, y + 4.5);
                xL += larguras[2];

                yM = y + 3.6;
                pdf.setFontSize(7);
                acaoLines.forEach((l) => { pdf.text(l, xL, yM); yM += passoLinha; });
                xL += larguras[3];

                yM = y + 3.6;
                pdf.setTextColor(55, 65, 90);
                detLines.forEach((l) => { pdf.text(l, xL, yM); yM += passoLinha; });

                y += rowH;
            });
        }

        PDF_UTILS.adicionarRodape(pdf, "Metric4 RTLS — Log de Ações", () => [W, H]);

        const dataStr = new Date().toISOString().slice(0, 10);
        pdf.save(`audit_log_metric4_${dataStr}.pdf`);

    } catch (err) {
        console.error(err);
        alert(`Erro ao gerar PDF: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = "⬇ Exportar PDF";
    }
}
