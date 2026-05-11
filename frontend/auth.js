/**
 * auth.js
 * modulo partilhado de autenticacao metric4 rtls
 * incluir antes de qualquer outro script que precise de autenticacao:
 * <script src="/static/auth.js"></script>
 */

/**
 * le jwt do localstorage
 * @returns {string|null}
 */
function obterToken() {
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
