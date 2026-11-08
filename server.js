/**
 * PROTÓTIPO LÁ VEM HISTÓRIA! - Gerador de PDF/X-1a
 *
 * Pipeline:
 * 1. Recebe pergunta (fixa), resposta em texto e 3 imagens via upload
 * 2. Monta um PDF simples com a pergunta, resposta e as 3 fotos
 * 3. Passa o PDF pelo motor da gráfica (grafica/pipeline.py): CMYK, preto em K,
 *    limite de 280%, sangria, marcas de corte, PDF/X-1a e validação
 * 4. Devolve o PDF final para download
 *
 * POST /grafica recebe o PDF que o site já gera (RGB) e devolve o PDF/X-1a.
 */

const express = require('express');
const multer = require('multer');
const sharp = require('sharp');
const PDFDocument = require('pdfkit');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');
const { randomUUID } = require('crypto');

const app = express();
const PORT = process.env.PORT || 3000;

const PASTA_TEMP = path.join(__dirname, 'temp');
const PASTA_PUBLIC = path.join(__dirname, 'public');

if (!fs.existsSync(PASTA_TEMP)) fs.mkdirSync(PASTA_TEMP, { recursive: true });

app.use(express.static(PASTA_PUBLIC));
app.use(express.json());

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 15 * 1024 * 1024 }, // 15mb por imagem
});

// A conversão de cor (CMYK, P&B em K, limite de tinta) acontece no pipeline da gráfica,
// depois de montar o PDF. Aqui só corrigimos a orientação EXIF da foto.
async function prepararImagem(buffer) {
  return { buffer: await sharp(buffer).rotate().jpeg({ quality: 95 }).toBuffer() };
}

async function gerarPdfBase(pergunta, resposta, imagensPreparadas, caminhoSaida) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({
      size: [396.85, 566.93], // 140mm x 200mm aprox, em pontos (140/25.4*72)
      margins: { top: 50, bottom: 50, left: 40, right: 40 },
    });

    const stream = fs.createWriteStream(caminhoSaida);
    doc.pipe(stream);

    doc.fontSize(18).fillColor('#2b2b2b').text(pergunta, { align: 'left' });
    doc.moveDown(1);
    doc.fontSize(12).fillColor('#3a3a3a').text(resposta, { align: 'left', lineGap: 4 });
    doc.moveDown(2);

    const larguraDisponivel = doc.page.width - doc.page.margins.left - doc.page.margins.right;
    const alturaFoto = 130;
    let yAtual = doc.y;

    for (const img of imagensPreparadas) {
      if (yAtual + alturaFoto > doc.page.height - doc.page.margins.bottom) {
        doc.addPage();
        yAtual = doc.page.margins.top;
      }
      doc.image(img.buffer, doc.page.margins.left, yAtual, {
        fit: [larguraDisponivel, alturaFoto],
      });
      yAtual += alturaFoto + 15;
    }

    doc.end();
    stream.on('finish', resolve);
    stream.on('error', reject);
  });
}

// MOTOR DA GRÁFICA
//
// Toda a conversão para o padrão da Meta (cor CMYK, preto em K, limite de 280%,
// sangria, marcas de corte, PDF/X-1a e validação) mora em grafica/pipeline.py.
// O perfil ICC e os textos de OutputCondition também ficam lá.
const PYTHON = process.env.PYTHON_GRAFICA || 'python3';
const PIPELINE = path.join(__dirname, 'grafica', 'pipeline.py');

// Devolve o relatório do pipeline. Rejeita se o PDF não passou na validação:
// um arquivo reprovado nunca deve seguir para a gráfica.
function converterParaGrafica(caminhoEntrada, caminhoSaida, { largura = 148, altura = 210, nome, fundo } = {}) {
  return new Promise((resolve, reject) => {
    const args = [PIPELINE, caminhoEntrada, caminhoSaida, '--largura', String(largura), '--altura', String(altura)];
    if (nome) args.push('--nome', nome);
    if (fundo) args.push('--fundo', fundo);

    execFile(PYTHON, args, { maxBuffer: 10 * 1024 * 1024 }, (erro, stdout, stderr) => {
      let relatorio;
      try {
        relatorio = JSON.parse(stdout);
      } catch {
        console.error('Pipeline da gráfica sem relatório:', stderr || erro);
        return reject(new Error('Falha no pipeline da gráfica.'));
      }
      if (!relatorio.ok) {
        const falha = new Error('PDF reprovado na validação da gráfica.');
        falha.relatorio = relatorio;
        return reject(falha);
      }
      resolve(relatorio);
    });
  });
}

// Recebe o livro impresso pelo site no modo gráfica e devolve o PDF/X-1a.
// Campos: "livro" (camada de frente, ?grafica=frente, impressa sem fundos) e "fundo"
// (camada de fundo, ?grafica=fundo, com fundos). Sem o fundo, "livro" é tratado como o PDF
// comum do site; se ele tiver transparência, a validação reprova.
// O relatório da validação vai no cabeçalho X-Relatorio-Grafica (JSON em base64).
const uploadPdf = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 200 * 1024 * 1024 },
});

app.post('/grafica', uploadPdf.fields([{ name: 'livro', maxCount: 1 }, { name: 'fundo', maxCount: 1 }]), async (req, res) => {
  const idSessao = randomUUID();
  const caminhoEntrada = path.join(PASTA_TEMP, `${idSessao}_rgb.pdf`);
  const caminhoFundo = path.join(PASTA_TEMP, `${idSessao}_fundo.pdf`);
  const caminhoSaida = path.join(PASTA_TEMP, `${idSessao}_x1a.pdf`);
  const limpar = () => {
    fs.unlink(caminhoEntrada, () => {});
    fs.unlink(caminhoFundo, () => {});
    fs.unlink(caminhoSaida, () => {});
  };

  try {
    const livro = req.files?.livro?.[0];
    const fundo = req.files?.fundo?.[0];
    if (!livro) return res.status(400).json({ erro: 'Envie o PDF do livro no campo "livro".' });
    fs.writeFileSync(caminhoEntrada, livro.buffer);
    if (fundo) fs.writeFileSync(caminhoFundo, fundo.buffer);

    const relatorio = await converterParaGrafica(caminhoEntrada, caminhoSaida, {
      largura: Number(req.body.largura) || 148,
      altura: Number(req.body.altura) || 210,
      nome: req.body.nome,
      fundo: fundo ? caminhoFundo : undefined,
    });

    res.set('X-Relatorio-Grafica', Buffer.from(JSON.stringify(relatorio)).toString('base64'));
    res.download(caminhoSaida, 'livro_grafica_x1a.pdf', (erro) => {
      limpar();
      if (erro) console.error('Erro ao enviar PDF:', erro);
    });
  } catch (erro) {
    limpar();
    console.error('Erro no pipeline da gráfica:', erro.relatorio || erro);
    res.status(erro.relatorio ? 422 : 500).json({
      erro: erro.message,
      relatorio: erro.relatorio,
    });
  }
});

app.post('/gerar-pdf', upload.array('fotos', 3), async (req, res) => {
  const idSessao = randomUUID();
  const caminhoPdfBase = path.join(PASTA_TEMP, `${idSessao}_base.pdf`);
  const caminhoPdfFinal = path.join(PASTA_TEMP, `${idSessao}_x1a.pdf`);

  try {
    const { pergunta, resposta } = req.body;
    const arquivos = req.files;

    if (!pergunta || !resposta) {
      return res.status(400).json({ erro: 'Pergunta e resposta são obrigatórias.' });
    }
    if (!arquivos || arquivos.length === 0) {
      return res.status(400).json({ erro: 'Envie ao menos uma foto.' });
    }

    const imagensPreparadas = [];
    for (const arquivo of arquivos) {
      const resultado = await prepararImagem(arquivo.buffer);
      imagensPreparadas.push(resultado);
    }

    await gerarPdfBase(pergunta, resposta, imagensPreparadas, caminhoPdfBase);
    await converterParaGrafica(caminhoPdfBase, caminhoPdfFinal, { largura: 140, altura: 200 });

    res.download(caminhoPdfFinal, 'lavemhistoria_x1a.pdf', (erro) => {
      // limpeza dos arquivos temporários após o download
      fs.unlink(caminhoPdfBase, () => {});
      fs.unlink(caminhoPdfFinal, () => {});
      if (erro) console.error('Erro ao enviar PDF:', erro);
    });
  } catch (erro) {
    console.error('Erro no pipeline:', erro);
    fs.unlink(caminhoPdfBase, () => {});
    fs.unlink(caminhoPdfFinal, () => {});
    res.status(500).json({ erro: 'Falha ao gerar o PDF. Tente novamente.' });
  }
});

app.listen(PORT, () => {
  console.log(`Protótipo rodando em http://localhost:${PORT}`);
});
