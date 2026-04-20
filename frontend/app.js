// 1. Login
async function fazerLogin() {
    const user = document.getElementById("username").value;
    const pass = document.getElementById("password").value;
    const erroTexto = document.getElementById("mensagem_erro");

    // O Swagger UI e o FastAPI OAuth2 exigem dados em formato "Form Data" e não JSON!
    const formData = new URLSearchParams();
    formData.append("username", user);
    formData.append("password", pass);

    try {
        const resposta = await fetch("/login", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded"
            },
            body: formData.toString()
        });

        if (resposta.ok) {
            const dados = await resposta.json();
            // Sucesso! token guardado
            localStorage.setItem("cracha_jwt", dados.access_token);
            erroTexto.innerText = "";
            mudarParaDashboard();
        } else {
            erroTexto.innerText = "Credenciais inválidas. Acesso Negado.";
        }
    } catch (erro) {
        erroTexto.innerText = "Erro ao contactar o servidor.";
    }
}

// 2. Transições Visuais - Single Page Application
function mudarParaDashboard() {
    document.getElementById("seccao_login").classList.add("escondido");
    document.getElementById("seccao_dashboard").classList.remove("escondido");
}

function fazerLogout() {
    localStorage.removeItem("cracha_jwt"); // Destrói o cracha
    document.getElementById("seccao_dashboard").classList.add("escondido");
    document.getElementById("seccao_login").classList.remove("escondido");
    document.getElementById("consola_dados").innerText = "A aguardar dados da fábrica...";
}

// 3. Verificação de Segurança ao dar refresh
// user verificado faz refresh nao precisa de login de novo
window.onload = function() {
    if (localStorage.getItem("cracha_jwt")) {
        mudarParaDashboard();
    }
}

// 4. busca os dados
async function obterPosicoes() {
    const token = localStorage.getItem("cracha_jwt");
    const consola = document.getElementById("consola_dados");
    
    if (!token) {
        fazerLogout();
        return;
    }

    try {
        // pedido GET com crachá no Header de Autorização
        const resposta = await fetch("/posicoes", {
            method: "GET",
            headers: {
                "Authorization": "Bearer " + token
            }
        });

        if (resposta.ok) {
            const pacoteDados = await resposta.json();
            document.getElementById("nome_cliente").innerText = pacoteDados.cliente;
            
            // dados em bruto - proof of concept
            consola.innerText = JSON.stringify(pacoteDados, null, 2);
        } else {
            // token expirou ou inválido
            consola.innerText = "Erro de Autenticação. Por favor, saia e entre novamente.";
            fazerLogout();
        }
    } catch (erro) {
        consola.innerText = "Erro ao comunicar com a Base de Dados (InfluxDB).";
    }
}