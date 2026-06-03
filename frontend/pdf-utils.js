// utilitarios partilhados de geracao pdf metric4
(function () {
    let _logo = null;
    let _logoOk = false;

    // carrega o logo uma unica vez — chamadas subsequentes resolvem imediatamente
    function carregarLogo() {
        return new Promise((resolve) => {
            if (_logoOk) { resolve(true); return; }
            _logo = new Image();
            _logo.onload  = () => { _logoOk = true; resolve(true); };
            _logo.onerror = () => resolve(false);
            _logo.src = (window.ASSET_PATHS && window.ASSET_PATHS.LOGO) || "/static/assets/imgs/metric-logo.svg";
        });
    }

    function logoDisponivel() {
        return _logoOk;
    }

    // insere o logo numa pagina pdf via canvas intermediario com fundo branco
    function inserirLogo(pdf, x, y, w, h) {
        if (!_logoOk || !_logo) return;
        const c = document.createElement("canvas");
        c.width = 400;
        c.height = 150;
        const ctx = c.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(_logo, 40, 45, 320, 60);
        pdf.addImage(c.toDataURL("image/png"), "PNG", x, y, w, h);
    }

    // desenha o logo directamente num canvas 2d (para exportacao png)
    function desenharLogoNoCanvas(ctx, x, y, w, h) {
        if (!_logoOk || !_logo) return;
        ctx.drawImage(_logo, x, y, w, h);
    }

    // escreve rodape numerado em todas as paginas — getDims(p) => [largura, altura]
    function adicionarRodape(pdf, texto, getDims) {
        const totalPag = pdf.internal.getNumberOfPages();
        for (let p = 1; p <= totalPag; p++) {
            pdf.setPage(p);
            const [Wp, Hp] = getDims(p);
            pdf.setFontSize(7);
            pdf.setTextColor(150, 160, 180);
            pdf.text(`${texto} | Pág. ${p}/${totalPag}`, Wp / 2, Hp - 5, { align: "center" });
        }
    }

    window.PDF_UTILS = { carregarLogo, logoDisponivel, inserirLogo, desenharLogoNoCanvas, adicionarRodape };
})();
