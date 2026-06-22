// pixels mínimos sugeridos calculados a partir do checklist documentado
// (base 300dpi, considerando o maior slot razoável de cada proporção)
const RESOLUCAO_MINIMA = { largura: 1181, altura: 1181 }; // referência mínima conservadora (quadrado)

const formulario = document.getElementById('formulario');
const botaoGerar = document.getElementById('botao-gerar');
const statusEl = document.getElementById('status');
const slots = document.querySelectorAll('.slot-foto');

const arquivosSelecionados = [null, null, null];

slots.forEach((slot) => {
  const input = slot.querySelector('input[type="file"]');

  input.addEventListener('change', async (evento) => {
    const arquivo = evento.target.files[0];
    if (!arquivo) return;

    const indice = Number(input.dataset.index);
    arquivosSelecionados[indice] = arquivo;

    // remove alerta anterior, se houver
    const alertaAntigo = slot.querySelector('.alerta-qualidade');
    if (alertaAntigo) alertaAntigo.remove();

    const urlPreview = URL.createObjectURL(arquivo);

    // checa resolução real da imagem antes de mostrar o preview
    const dimensoes = await obterDimensoes(urlPreview);
    const resolucaoBaixa =
      dimensoes.largura < RESOLUCAO_MINIMA.largura ||
      dimensoes.altura < RESOLUCAO_MINIMA.altura;

    slot.innerHTML = '';
    const img = document.createElement('img');
    img.src = urlPreview;
    slot.appendChild(img);
    slot.appendChild(input);
    slot.classList.add('preenchido');

    if (resolucaoBaixa) {
      const alerta = document.createElement('div');
      alerta.className = 'alerta-qualidade';
      alerta.textContent = 'Resolução baixa para impressão';
      slot.appendChild(alerta);
    }
  });
});

function obterDimensoes(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ largura: img.naturalWidth, altura: img.naturalHeight });
    img.src = url;
  });
}

formulario.addEventListener('submit', async (evento) => {
  evento.preventDefault();

  const resposta = document.getElementById('resposta').value.trim();
  const pergunta = document.getElementById('pergunta-texto').textContent.trim();
  const fotos = arquivosSelecionados.filter(Boolean);

  if (!resposta) {
    mostrarStatus('Escreva sua resposta antes de gerar o PDF.', 'erro');
    return;
  }
  if (fotos.length === 0) {
    mostrarStatus('Envie ao menos uma foto.', 'erro');
    return;
  }

  const dadosFormulario = new FormData();
  dadosFormulario.append('pergunta', pergunta);
  dadosFormulario.append('resposta', resposta);
  fotos.forEach((foto) => dadosFormulario.append('fotos', foto));

  botaoGerar.disabled = true;
  botaoGerar.textContent = 'Gerando PDF...';
  mostrarStatus('Convertendo cores e gerando conformidade PDF/X-1a. Isso pode levar alguns segundos...', '');

  try {
    const resposta = await fetch('/gerar-pdf', {
      method: 'POST',
      body: dadosFormulario,
    });

    if (!resposta.ok) {
      const erro = await resposta.json().catch(() => ({}));
      throw new Error(erro.erro || 'Falha ao gerar o PDF.');
    }

    const blob = await resposta.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'lavemhistoria_x1a.pdf';
    document.body.appendChild(link);
    link.click();
    link.remove();

    mostrarStatus('PDF gerado com sucesso. O download deve começar automaticamente.', 'sucesso');
  } catch (erro) {
    mostrarStatus(erro.message, 'erro');
  } finally {
    botaoGerar.disabled = false;
    botaoGerar.textContent = 'Gerar PDF/X-1a';
  }
});

function mostrarStatus(mensagem, tipo) {
  statusEl.textContent = mensagem;
  statusEl.className = 'status' + (tipo ? ' ' + tipo : '');
}
