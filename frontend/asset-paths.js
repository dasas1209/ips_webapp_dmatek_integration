/**
 * asset-paths.js — caminhos canónicos de imagens estáticas do frontend
 */
(function () {
    const IMGS_DIR = "/static/assets/imgs/";
    const LOGO = IMGS_DIR + "metric-logo.svg";
    const MAPS_DIR = IMGS_DIR + "maps/";
    const AVATARS_DIR = IMGS_DIR + "avatars/";

    function normalizarCaminhoImagem(caminho) {
        if (!caminho) return "";
        let c = String(caminho).trim().replace(/\\/g, "/");

        if (c.includes("metric-logo")) {
            return LOGO;
        }

        const nomeFicheiro = c.split("/").pop() || "";
        const eImagem = /\.(png|jpe?g|svg|webp|gif)$/i.test(nomeFicheiro);

        if (c.includes("/avatars/") || c.startsWith("/static/assets/avatars/")) {
            return AVATARS_DIR + nomeFicheiro;
        }

        if (c.startsWith("/static/assets/imgs/")) {
            return c;
        }

        if (c.startsWith("frontend/assets/imgs/")) {
            return c.replace("frontend/", "/static/");
        }

        if (c.startsWith("frontend/assets/avatars/")) {
            return AVATARS_DIR + nomeFicheiro;
        }

        if (eImagem && (c.startsWith("frontend/assets/") || c.startsWith("/static/assets/"))) {
            return MAPS_DIR + nomeFicheiro;
        }

        if (c.startsWith("frontend/")) {
            return c.replace("frontend/", "/static/");
        }

        if (!c.startsWith("/") && eImagem) {
            return MAPS_DIR + nomeFicheiro;
        }

        if (!c.startsWith("/")) {
            return "/" + c;
        }

        return c;
    }

    function mapaFallbackTenant(tenantId) {
        return `${MAPS_DIR}mapa_${tenantId}.png`;
    }

    function iniciaisCliente(nome) {
        return (nome || "")
            .replace(/_/g, " ")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((p) => p[0]?.toUpperCase() || "")
            .join("") || "M4";
    }

    function _criarImgAvatar(src, alt, onError) {
        const img = document.createElement("img");
        img.alt = alt || "Avatar";
        img.decoding = "async";
        img.loading = "eager";
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.maxWidth = "100%";
        img.style.maxHeight = "100%";
        img.style.objectFit = "cover";
        img.style.display = "block";
        img.onerror = onError;
        if (src.startsWith("blob:")) {
            img.src = src;
        } else {
            const separador = src.includes("?") ? "&" : "?";
            img.src = `${src}${separador}v=${Date.now()}`;
        }
        return img;
    }

    function aplicarAvatarElemento(el, nome, logoUrl) {
        if (!el) return;
        const iniciais = iniciaisCliente(nome);
        el.innerHTML = "";
        el.classList.remove("tenant-avatar--img");
        if (logoUrl) {
            const src =
                String(logoUrl).startsWith("blob:") || String(logoUrl).startsWith("data:")
                    ? logoUrl
                    : normalizarCaminhoImagem(logoUrl);
            const img = _criarImgAvatar(src, nome, () => aplicarAvatarElemento(el, nome, null));
            el.classList.add("tenant-avatar--img");
            el.appendChild(img);
        } else {
            el.textContent = iniciais;
        }
    }

    window.ASSET_PATHS = {
        IMGS_DIR,
        LOGO,
        MAPS_DIR,
        AVATARS_DIR,
        normalizarCaminhoImagem,
        mapaFallbackTenant,
        iniciaisCliente,
        aplicarAvatarElemento,
    };
})();
