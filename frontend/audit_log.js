/**
 * audit_log.js — log global de ações (superadmin)
 */

const ACOES_LABEL = {
    login: "Início de sessão",
    logout: "Fim de sessão",
    credentials_updated: "Credenciais alteradas",
    tenant_created: "Cliente criado",
    tenant_updated: "Cliente atualizado",
    tenant_deleted: "Cliente eliminado",
    user_created: "Utilizador criado",
    user_updated: "Utilizador atualizado",
    user_deleted: "Utilizador eliminado",
    map_created: "Mapa criado",
    map_updated: "Mapa atualizado",
    map_deleted: "Mapa eliminado",
    tag_created: "Tag criada",
    tag_deleted: "Tag eliminada",
    tag_aliases_updated: "Nomes de tags atualizados",
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
        /* mantém opção «todos» */
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
        /* aplicação imediata ao escolher cliente — padrão comum em selects */
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
}

document.addEventListener("DOMContentLoaded", async () => {
    cacheElements();
    if (!verificarAcessoSuperadmin()) return;
    atualizarVisibilidadeDatasPersonalizadas();
    configurarEventos();
    await carregarTenants();
    carregarAuditLog();
});
