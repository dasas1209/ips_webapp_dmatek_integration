let dadosAuditoria = null;
let imagemMapaAuditoria = new Image();
let imagemLogoMetric4 = new Image();
let logoCarregado = false;
let presetAtivo = "4h";

const COR_TAGS = [
    "#e63946", "#457b9d", "#2a9d8f", "#e9c46a", "#f4a261",
    "#264653", "#8338ec", "#fb5607", "#3a86ff", "#06d6a0",
    "#ffbe0b", "#f72585", "#4cc9f0", "#7209b7", "#b5179e",
    "#480ca8", "#3f37c9", "#4361ee", "#4895ef", "#4cc9f0"
];
const mapaCorTags = {};

function corDaTag(tagId) {
    if (!mapaCorTags[tagId]) {
        const idx = Object.keys(mapaCorTags).length % COR_TAGS.length;
        mapaCorTags[tagId] = COR_TAGS[idx];
    }
    return mapaCorTags[tagId];
}

function formatarData(dt) {
    const d = new Date(dt);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function carregarLogo() {
    return new Promise((resolve) => {
        if (logoCarregado) {
            resolve(true);
            return;
        }
        imagemLogoMetric4.onload = () => {
            logoCarregado = true;
            resolve(true);
        };
        imagemLogoMetric4.onerror = () => resolve(false);
        imagemLogoMetric4.src = "/static/assets/metric-logo.svg";
    });
}

window.onload = function () {
    redirecionarSeNaoAutenticado();
    const tenant = obterTenantId();
    if (tenant) document.getElementById("badge-cliente").textContent = tenant;
    carregarLogo();
    aplicarPreset("4h");
};

function aplicarPreset(tipo) {
    presetAtivo = tipo;
    document.querySelectorAll(".btn-preset").forEach((b) => b.classList.remove("selected"));
    document.getElementById(`preset-${tipo}`).classList.add("selected");
    document.getElementById("row-custom").style.display = tipo === "custom" ? "flex" : "none";

    if (tipo !== "custom") {
        const agora = new Date();
        const horas = tipo === "4h" ? 4 : 8;
        const inicio = new Date(agora.getTime() - horas * 3600000);
        document.getElementById("dtFim").value = toLocalDatetimeInput(agora);
        document.getElementById("dtInicio").value = toLocalDatetimeInput(inicio);
    }
}

function toLocalDatetimeInput(dt) {
    const off = dt.getTimezoneOffset() * 60000;
    return new Date(dt - off).toISOString().slice(0, 16);
}

function obterIntervaloISO() {
    const inicioVal = document.getElementById("dtInicio").value;
    const fimVal = document.getElementById("dtFim").value;
    if (!inicioVal || !fimVal) return null;
    return { inicio: new Date(inicioVal).toISOString(), fim: new Date(fimVal).toISOString() };
}

function validarIntervalo() {
    const iv = obterIntervaloISO();
    if (!iv) return false;

    const diffDias = (new Date(iv.fim) - new Date(iv.inicio)) / 86400000;
    const aviso = document.getElementById("aviso-intervalo");

    if (diffDias > 30 || diffDias <= 0) {
        aviso.style.display = "block";
        return false;
    }
    aviso.style.display = "none";
    return true;
}

document.addEventListener("DOMContentLoaded", function () {
    ["dtInicio", "dtFim"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", validarIntervalo);
    });
});

async function gerarPreview() {
    if (!validarIntervalo()) {
        alert("Intervalo temporal inválido. Verifique as datas.");
        return;
    }

    const iv = obterIntervaloISO();
    const token = obterToken();
    if (!token) {
        window.location.href = "/";
        return;
    }

    setEstadoCarregando(true, "A consultar InfluxDB...");

    try {
        const url = `/relatorio/dados?inicio=${encodeURIComponent(iv.inicio)}&fim=${encodeURIComponent(iv.fim)}`;
        const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || resp.statusText);
        }

        dadosAuditoria = await resp.json();
        setEstadoCarregando(false);
        renderizarPreview(dadosAuditoria, iv);
    } catch (e) {
        setEstadoCarregando(false);
        alert(`Erro ao obter dados: ${e.message}`);
    }
}

function setEstadoCarregando(activo, texto) {
    const bar = document.getElementById("status-bar");
    const btnPreview = document.getElementById("btn-preview");
    const btnPng = document.getElementById("btn-png");
    const btnPdf = document.getElementById("btn-pdf");

    if (activo) {
        bar.classList.add("visivel");
        document.getElementById("status-texto").textContent = texto || "...";
        btnPreview.disabled = btnPng.disabled = btnPdf.disabled = true;
    } else {
        bar.classList.remove("visivel");
        btnPreview.disabled = false;
    }
}

function renderizarPreview(dados, iv) {
    document.getElementById("preview-section").style.display = "block";
    window.scrollTo({ top: document.getElementById("preview-section").offsetTop - 20, behavior: "smooth" });

    document.getElementById("badge-periodo-preview").textContent = `${formatarData(iv.inicio)} ? ${formatarData(iv.fim)}`;

    document.getElementById("res-distancia").textContent = `${dados.kpis_frota.distancia_total_m} m`;
    document.getElementById("res-bateria").textContent = `${dados.kpis_frota.bateria_media_perc}%`;
    document.getElementById("res-incidentes").textContent = dados.kpis_frota.total_incidentes;
    document.getElementById("res-tags").textContent = dados.kpis_frota.tags_ativas;

    const chkE = document.getElementById("chk-esparguete").checked;
    const chkK = document.getElementById("chk-kpis").checked;
    const chkI = document.getElementById("chk-incidentes").checked;

    document.getElementById("card-esparguete").style.display = chkE ? "" : "none";
    document.getElementById("card-kpis").style.display = chkK ? "" : "none";
    document.getElementById("card-incidentes").style.display = chkI ? "" : "none";

    if (chkE) renderizarEsparguetePreview(dados);
    if (chkK) renderizarTabelaKpis(dados.kpis_por_tag);
    if (chkI) renderizarIncidentes(dados.incidentes);

    document.getElementById("btn-png").disabled = false;
    document.getElementById("btn-pdf").disabled = false;
}

function renderizarEsparguetePreview(dados) {
    const canvas = document.getElementById("canvasEsparguetePreview");
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width || 800;
    canvas.height = rect.height || 320;
    const ctx = canvas.getContext("2d");

    const mapaPath = `/static/assets/mapa_${dados.cliente}.png`;
    if (!imagemMapaAuditoria.src.includes(mapaPath)) {
        imagemMapaAuditoria.src = mapaPath;
        imagemMapaAuditoria.onload = () => desenharEsparguete(ctx, canvas, dados);
        imagemMapaAuditoria.onerror = () => desenharEsparguete(ctx, canvas, dados);
    } else {
        desenharEsparguete(ctx, canvas, dados);
    }
}

function desenharEsparguete(ctx, canvas, dados) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (imagemMapaAuditoria.complete && imagemMapaAuditoria.naturalWidth > 0) {
        ctx.drawImage(imagemMapaAuditoria, 0, 0, canvas.width, canvas.height);
    } else {
        ctx.fillStyle = "#e8ecf4";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    const porTag = {};
    dados.esparguete_pontos.forEach((p) => {
        if (!porTag[p.tag_id]) porTag[p.tag_id] = [];
        porTag[p.tag_id].push(p);
    });

    Object.entries(porTag).forEach(([tagId, pontos]) => {
        if (pontos.length < 2) return;
        const cor = corDaTag(tagId);
        ctx.strokeStyle = cor;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.75;
        ctx.beginPath();
        pontos.forEach((p, i) => {
            const px = p.x * canvas.width;
            const py = p.y * canvas.height;
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        });
        ctx.stroke();

        ctx.globalAlpha = 1;
        ctx.fillStyle = cor;
        const ultimo = pontos[pontos.length - 1];
        ctx.beginPath();
        ctx.arc(ultimo.x * canvas.width, ultimo.y * canvas.height, 5, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#1a1f36";
        ctx.font = "bold 11px Segoe UI, Arial";
        ctx.fillText(tagId, ultimo.x * canvas.width + 7, ultimo.y * canvas.height + 4);
    });
    ctx.globalAlpha = 1;
}

function renderizarTabelaKpis(kpis) {
    const tbody = document.getElementById("tbody-kpis");
    tbody.innerHTML = "";

    if (kpis.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#a0aec0;">Sem dados no período.</td></tr>';
        return;
    }

    kpis.forEach((k) => {
        const cor = k.bateria_min_perc <= 5 ? "red" : k.bateria_min_perc <= 20 ? "#fd7e14" : "#28a745";
        const alertaBadge = k.num_alertas > 0
            ? `<span class="badge-alerta">${k.num_alertas} alerta(s)</span>`
            : '<span class="badge-ok">OK</span>';

        tbody.innerHTML += `
            <tr>
                <td><strong>${k.tag_id}</strong></td>
                <td>${k.distancia_m}</td>
                <td>${k.oee_perc}</td>
                <td style="color:${cor};font-weight:bold;">${k.bateria_min_perc}</td>
                <td>${k.tempo_ocioso_min}</td>
                <td>${alertaBadge}</td>
            </tr>`;
    });
}

function renderizarIncidentes(incidentes) {
    const lista = document.getElementById("lista-incidentes");
    lista.innerHTML = "";

    if (incidentes.length === 0) {
        lista.innerHTML = '<li class="incident-empty">Nenhum incidente registado neste período.</li>';
        return;
    }

    incidentes.forEach((inc) => {
        const ts = formatarData(inc.timestamp);
        const fonte = inc.fonte === "csv"
            ? '<span style="font-size:10px;color:#8892b0;margin-left:6px;">[CSV]</span>'
            : "";
        const desc = inc.descricao
            ? `<div class="incident-ts" style="font-style:italic;">${inc.descricao}</div>`
            : "";

        lista.innerHTML += `
            <li class="incident-item">
                <div class="incident-body">
                    <span class="incident-tag">${inc.tag_id}</span>${fonte}
                    <span class="incident-tipo">${inc.tipo}</span>
                    <div class="incident-ts">${ts}</div>
                    ${desc}
                </div>
            </li>`;
    });
}

async function exportarPNG() {
    if (!dadosAuditoria) return;

    await carregarLogo();

    const canvasSrc = document.getElementById("canvasEsparguetePreview");
    const exportCanvas = document.createElement("canvas");
    exportCanvas.width = canvasSrc.width;
    exportCanvas.height = canvasSrc.height;
    const ctx = exportCanvas.getContext("2d");

    ctx.drawImage(canvasSrc, 0, 0);

    if (logoCarregado) {
        ctx.globalAlpha = 0.96;
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.fillRect(10, 10, 180, 48);
        ctx.drawImage(imagemLogoMetric4, 16, 16, 150, 30);
        ctx.globalAlpha = 1;
    }

    const iv2 = obterIntervaloISO();
    if (iv2) {
        const periodoTxt = `Período: ${formatarData(iv2.inicio)} - ${formatarData(iv2.fim)}`;
        ctx.globalAlpha = 0.85;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, ctx.measureText(periodoTxt).width + 16, 22);
        ctx.globalAlpha = 1;
        ctx.fillStyle = "#1a1f36";
        ctx.font = "bold 12px Segoe UI, Arial";
        ctx.fillText(periodoTxt, 8, 15);
    }

    ctx.globalAlpha = 0.5;
    ctx.fillStyle = "#1a1f36";
    ctx.font = "bold 12px Segoe UI, Arial";
    ctx.fillText("Metric4 RTLS", 8, exportCanvas.height - 8);
    ctx.globalAlpha = 1;

    const link = document.createElement("a");
    const iv = obterIntervaloISO();
    const dataStr = iv ? iv.inicio.slice(0, 10) : new Date().toISOString().slice(0, 10);
    link.download = `auditoria_esparguete_${dadosAuditoria.cliente}_${dataStr}.png`;
    link.href = exportCanvas.toDataURL("image/png");
    link.click();
}

async function exportarPDF() {
    if (!dadosAuditoria) return;

    if (typeof window.jspdf === "undefined") {
        alert("Biblioteca jsPDF não carregada. Verifique a ligação à internet.");
        return;
    }

    await carregarLogo();
    setEstadoCarregando(true, "A gerar PDF...");

    const { jsPDF } = window.jspdf;
    const tenant = dadosAuditoria.cliente;
    const iv = obterIntervaloISO();

    try {
        const pdf = new jsPDF("p", "mm", "a4");
        const W = 210;
        const H = 297;

        pdf.setFillColor(26, 31, 54);
        pdf.rect(0, 0, W, H, "F");

        if (logoCarregado) {
            const cLogo = document.createElement("canvas");
            cLogo.width = 400;
            cLogo.height = 150;
            const cctx = cLogo.getContext("2d");
            cctx.fillStyle = "#ffffff";
            cctx.fillRect(0, 0, cLogo.width, cLogo.height);
            cctx.drawImage(imagemLogoMetric4, 40, 45, 320, 60);
            const logoData = cLogo.toDataURL("image/png");
            pdf.addImage(logoData, "PNG", W / 2 - 35, 12, 70, 18);
        }

        pdf.setFillColor(255, 255, 255);
        pdf.roundedRect(20, 40, W - 40, 60, 6, 6, "F");
        pdf.setTextColor(26, 31, 54);
        pdf.setFontSize(22);
        pdf.setFont("helvetica", "bold");
        pdf.text("RELATÓRIO DE AUDITORIA", W / 2, 63, { align: "center" });
        pdf.setFontSize(13);
        pdf.setFont("helvetica", "normal");
        pdf.text("RTLS Industrial - Metric4", W / 2, 74, { align: "center" });
        pdf.setFontSize(11);
        pdf.text(`Cliente: ${tenant}`, W / 2, 86, { align: "center" });

        pdf.setTextColor(200, 210, 230);
        pdf.setFontSize(10);
        pdf.text(`De:  ${formatarData(iv.inicio)}`, W / 2, 118, { align: "center" });
        pdf.text(`Até: ${formatarData(iv.fim)}`, W / 2, 127, { align: "center" });
        pdf.text(`Gerado em: ${formatarData(new Date().toISOString())}`, W / 2, 136, { align: "center" });

        const kf = dadosAuditoria.kpis_frota;
        const kpisTexto = [
            ["Distância Total", `${kf.distancia_total_m} m`],
            ["Bateria Média", `${kf.bateria_media_perc}%`],
            ["Total Incidentes", String(kf.total_incidentes)],
            ["Tags Ativas", String(kf.tags_ativas)],
        ];

        let yKpi = 155;
        pdf.setFontSize(10);
        pdf.setTextColor(150, 170, 220);
        pdf.text("SUMÁRIO EXECUTIVO", W / 2, yKpi, { align: "center" });
        yKpi += 8;
        kpisTexto.forEach(([label, valor]) => {
            pdf.setTextColor(180, 200, 240);
            pdf.text(`${label}:`, 60, yKpi);
            pdf.setTextColor(255, 255, 255);
            pdf.setFont("helvetica", "bold");
            pdf.text(valor, 130, yKpi);
            pdf.setFont("helvetica", "normal");
            yKpi += 9;
        });

        pdf.setTextColor(80, 100, 140);
        pdf.setFontSize(8);
        pdf.text("Metric4 RTLS - Documento de Auditoria Confidencial", W / 2, H - 10, { align: "center" });

        pdf.addPage("a4", "l");
        const Wl = 297;
        const Hl = 210;
        pdf.setFillColor(244, 246, 251);
        pdf.rect(0, 0, Wl, Hl, "F");

        if (logoCarregado) {
            const cLogo2 = document.createElement("canvas");
            cLogo2.width = 400;
            cLogo2.height = 150;
            const cctx2 = cLogo2.getContext("2d");
            cctx2.fillStyle = "#ffffff";
            cctx2.fillRect(0, 0, cLogo2.width, cLogo2.height);
            cctx2.drawImage(imagemLogoMetric4, 40, 45, 320, 60);
            pdf.addImage(cLogo2.toDataURL("image/png"), "PNG", 10, 6, 48, 12);
        }

        pdf.setTextColor(26, 31, 54);
        pdf.setFontSize(14);
        pdf.setFont("helvetica", "bold");
        pdf.text("Diagrama de Esparguete - Trajetórias", Wl / 2, 14, { align: "center" });
        pdf.setFontSize(9);
        pdf.setFont("helvetica", "normal");
        pdf.setTextColor(100, 120, 150);
        pdf.text(`De: ${formatarData(iv.inicio)}   Até: ${formatarData(iv.fim)}   Cliente: ${tenant}`, Wl / 2, 21, { align: "center" });

        const exportCanvas = document.createElement("canvas");
        exportCanvas.width = 1200;
        exportCanvas.height = 750;
        const ctxEx = exportCanvas.getContext("2d");
        if (imagemMapaAuditoria.complete && imagemMapaAuditoria.naturalWidth > 0) {
            ctxEx.drawImage(imagemMapaAuditoria, 0, 0, 1200, 750);
        } else {
            ctxEx.fillStyle = "#e8ecf4";
            ctxEx.fillRect(0, 0, 1200, 750);
        }
        desenharEsparguete(ctxEx, exportCanvas, dadosAuditoria);
        pdf.addImage(exportCanvas.toDataURL("image/png"), "PNG", 10, 26, Wl - 20, Hl - 36);

        const tagsUnicas = [...new Set(dadosAuditoria.esparguete_pontos.map((p) => p.tag_id))].sort();
        let xLeg = 12;
        let yLeg = Hl - 5;
        pdf.setFontSize(7);
        tagsUnicas.forEach((tagId) => {
            const hex = corDaTag(tagId);
            const r = parseInt(hex.slice(1, 3), 16);
            const g = parseInt(hex.slice(3, 5), 16);
            const b = parseInt(hex.slice(5, 7), 16);
            pdf.setFillColor(r, g, b);
            pdf.rect(xLeg, yLeg - 3, 6, 3, "F");
            pdf.setTextColor(50, 60, 80);
            pdf.text(tagId, xLeg + 8, yLeg);
            xLeg += 30;
            if (xLeg > Wl - 30) {
                xLeg = 12;
                yLeg -= 8;
            }
        });

        pdf.addPage("a4", "p");
        pdf.setFillColor(244, 246, 251);
        pdf.rect(0, 0, W, H, "F");

        if (logoCarregado) {
            const cLogo3 = document.createElement("canvas");
            cLogo3.width = 400;
            cLogo3.height = 150;
            const cctx3 = cLogo3.getContext("2d");
            cctx3.fillStyle = "#ffffff";
            cctx3.fillRect(0, 0, cLogo3.width, cLogo3.height);
            cctx3.drawImage(imagemLogoMetric4, 40, 45, 320, 60);
            pdf.addImage(cLogo3.toDataURL("image/png"), "PNG", 10, 6, 42, 10);
        }

        pdf.setTextColor(26, 31, 54);
        pdf.setFontSize(14);
        pdf.setFont("helvetica", "bold");
        pdf.text("KPIs por Tag", W / 2, 18, { align: "center" });
        pdf.setFontSize(9);
        pdf.setFont("helvetica", "normal");
        pdf.setTextColor(100, 120, 150);
        pdf.text(`Período: ${formatarData(iv.inicio)} - ${formatarData(iv.fim)}`, W / 2, 25, { align: "center" });

        const cabecalhos = ["Tag", "Dist. (m)", "OEE (%)", "Bat. Mín (%)", "Ocioso (min)", "Alertas"];
        const larguras = [30, 32, 28, 35, 38, 28];
        let xTbl = 15;
        let yTbl = 35;

        pdf.setFillColor(26, 31, 54);
        pdf.rect(xTbl, yTbl, W - 30, 8, "F");
        pdf.setTextColor(255, 255, 255);
        pdf.setFontSize(8);
        pdf.setFont("helvetica", "bold");
        let xH = xTbl + 2;
        cabecalhos.forEach((h, i) => {
            pdf.text(h, xH, yTbl + 5.5);
            xH += larguras[i];
        });

        yTbl += 8;
        pdf.setFont("helvetica", "normal");
        dadosAuditoria.kpis_por_tag.forEach((k, idx) => {
            pdf.setFillColor(idx % 2 === 0 ? 255 : 248, idx % 2 === 0 ? 255 : 249, idx % 2 === 0 ? 255 : 255);
            pdf.rect(xTbl, yTbl, W - 30, 7, "F");
            pdf.setTextColor(40, 50, 70);
            const linha = [
                k.tag_id,
                String(k.distancia_m),
                String(k.oee_perc),
                String(k.bateria_min_perc),
                String(k.tempo_ocioso_min),
                k.num_alertas > 0 ? `${k.num_alertas} alerta(s)` : "OK",
            ];
            let xL = xTbl + 2;
            linha.forEach((v, i) => {
                if (i === 5 && k.num_alertas > 0) pdf.setTextColor(180, 30, 30);
                pdf.text(v, xL, yTbl + 5);
                pdf.setTextColor(40, 50, 70);
                xL += larguras[i];
            });
            yTbl += 7;
        });

        pdf.addPage("a4", "p");
        pdf.setFillColor(244, 246, 251);
        pdf.rect(0, 0, W, H, "F");

        if (logoCarregado) {
            const cLogo4 = document.createElement("canvas");
            cLogo4.width = 400;
            cLogo4.height = 150;
            const cctx4 = cLogo4.getContext("2d");
            cctx4.fillStyle = "#ffffff";
            cctx4.fillRect(0, 0, cLogo4.width, cLogo4.height);
            cctx4.drawImage(imagemLogoMetric4, 40, 45, 320, 60);
            pdf.addImage(cLogo4.toDataURL("image/png"), "PNG", 10, 6, 42, 10);
        }

        pdf.setTextColor(26, 31, 54);
        pdf.setFontSize(14);
        pdf.setFont("helvetica", "bold");
        pdf.text("Log de Incidentes", W / 2, 18, { align: "center" });
        pdf.setFontSize(9);
        pdf.setFont("helvetica", "normal");
        pdf.setTextColor(100, 120, 150);
        pdf.text(`Total: ${dadosAuditoria.incidentes.length} incidente(s) registado(s)`, W / 2, 25, { align: "center" });

        const cabInc = ["Timestamp", "Tag", "Tipo", "Coord X (norm)", "Coord Y (norm)"];
        const largInc = [55, 30, 40, 35, 35];
        let xInc = 10;
        let yInc = 35;

        pdf.setFillColor(180, 30, 30);
        pdf.rect(xInc, yInc, W - 20, 8, "F");
        pdf.setTextColor(255, 255, 255);
        pdf.setFontSize(8);
        pdf.setFont("helvetica", "bold");
        let xHI = xInc + 2;
        cabInc.forEach((h, i) => {
            pdf.text(h, xHI, yInc + 5.5);
            xHI += largInc[i];
        });

        yInc += 8;
        pdf.setFont("helvetica", "normal");
        if (dadosAuditoria.incidentes.length === 0) {
            pdf.setTextColor(100, 150, 100);
            pdf.setFontSize(11);
            pdf.text("Nenhum incidente registado neste período.", W / 2, yInc + 20, { align: "center" });
        } else {
            dadosAuditoria.incidentes.forEach((inc, idx) => {
                if (yInc > H - 20) {
                    pdf.addPage("a4", "p");
                    yInc = 20;
                }
                pdf.setFillColor(idx % 2 === 0 ? 255 : 255, idx % 2 === 0 ? 245 : 248, idx % 2 === 0 ? 245 : 248);
                pdf.rect(xInc, yInc, W - 20, 7, "F");
                pdf.setTextColor(40, 50, 70);
                const xCoord = inc.x != null ? String(inc.x) : "n/a";
                const yCoord = inc.y != null ? String(inc.y) : "n/a";
                const linhaInc = [formatarData(inc.timestamp), inc.tag_id, inc.tipo, xCoord, yCoord];
                let xLI = xInc + 2;
                linhaInc.forEach((v, i) => {
                    if (i === 2) pdf.setTextColor(180, 30, 30);
                    pdf.text(v, xLI, yInc + 5);
                    pdf.setTextColor(40, 50, 70);
                    xLI += largInc[i];
                });
                yInc += 7;
            });
        }

        const totalPag = pdf.internal.getNumberOfPages();
        const dimPag = (p) => (p === 2 ? [297, 210] : [210, 297]);
        for (let p = 1; p <= totalPag; p += 1) {
            pdf.setPage(p);
            pdf.setFontSize(7);
            pdf.setTextColor(150, 160, 180);
            const [Wp, Hp] = dimPag(p);
            pdf.text(`Metric4 RTLS - Auditoria Industrial | Pág. ${p}/${totalPag}`, Wp / 2, Hp - 5, { align: "center" });
        }

        pdf.save(`auditoria_${tenant}_${iv.inicio.slice(0, 10)}.pdf`);
    } catch (e) {
        console.error(e);
        alert(`Erro ao gerar PDF: ${e.message}`);
    } finally {
        setEstadoCarregando(false);
    }
}

