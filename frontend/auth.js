// auth.js modulo partilhado de autenticacao metric4 rtls

// verifica se o jwt guardado em localstorage esta expirado
function tokenExpirado() {
    const token = localStorage.getItem("cracha_jwt");
    if (!token) return true;
    try {
        const payloadB64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
        const payload    = JSON.parse(atob(payloadB64));
        // exp esta em segundos unix — compara com Date.now() em ms
        return Date.now() >= payload.exp * 1000;
    } catch {
        return true;
    }
}

// le jwt do localstorage — devolve null se ausente ou expirado
function obterToken() {
    if (tokenExpirado()) {
        localStorage.removeItem("cracha_jwt");
        localStorage.removeItem("tenant_id");
        localStorage.removeItem("is_admin");
        localStorage.removeItem("role");
        return null;
    }
    return localStorage.getItem("cracha_jwt");
}

// le o role sempre do token para evitar inconsistencias com cache stale
function obterRole() {
    const token = obterToken();
    if (!token) return null;
    try {
        const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
        return payload.role || null;
    } catch {
        return null;
    }
}

// devolve tenant id do utilizador autenticado
function obterTenantId() {
    const cached = localStorage.getItem("tenant_id");
    if (cached) return cached;

    const token = obterToken();
    if (!token) return null;

    try {
        const payloadB64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
        const payload    = JSON.parse(atob(payloadB64));
        const tenant     = payload.tenant_id || null;
        if (tenant) localStorage.setItem("tenant_id", tenant);
        return tenant;
    } catch {
        return null;
    }
}

// devolve o username do utilizador autenticado a partir do jwt
function obterNomeUtilizador() {
    const token = obterToken();
    if (!token) return "-";
    try {
        const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
        return payload.sub || payload.username || payload.user || "-";
    } catch {
        return "-";
    }
}

// verifica se o utilizador autenticado e o administrador do sistema
function isPainelAdmin() {
    return localStorage.getItem("is_admin") === "true";
}

// redireciona para login se nao houver sessao activa
function redirecionarSeNaoAutenticado() {
    if (!obterToken()) {
        window.location.href = "/";
    }
}
