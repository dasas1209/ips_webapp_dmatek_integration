/**
 * auth.js
 * modulo partilhado de autenticacao metric4 rtls
 * incluir antes de qualquer outro script que precise de autenticacao:
 * <script src="/static/auth.js"></script>
 */

/**
 * verifica se o jwt guardado em localstorage esta expirado
 * @returns {boolean}
 */
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

/**
 * le jwt do localstorage — devolve null se ausente ou expirado
 * @returns {string|null}
 */
function obterToken() {
    if (tokenExpirado()) {
        localStorage.removeItem("cracha_jwt");
        localStorage.removeItem("tenant_id");
        return null;
    }
    return localStorage.getItem("cracha_jwt");
}

/**
 * devolve tenant id do utilizador autenticado
 * @returns {string|null}
 */
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

/**
 * redireciona para login se nao houver sessao activa
 */
function redirecionarSeNaoAutenticado() {
    if (!obterToken()) {
        window.location.href = "/";
    }
}
