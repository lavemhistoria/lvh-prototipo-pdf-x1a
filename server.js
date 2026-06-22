/**
 * PROTÓTIPO LÁ VEM HISTÓRIA! - Gerador de PDF/X-1a
 *
 * Pipeline:
 * 1. Recebe pergunta (fixa), resposta em texto e 3 imagens via upload
 * 2. Converte as 3 imagens para CMYK (ou grayscale puro, se detectado como P&B)
 * 3. Monta um PDF simples com a pergunta, resposta e as 3 fotos
 * 4. Roda Ghostscript sobre o PDF para conformidade PDF/X-1a:2001 real
 * 5. Devolve o PDF final para download
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

// detecta se a imagem é visualmente grayscale comparando médias dos canais RGB
async function ehGrayscale(buffer) {
  const stats = await sharp(buffer).stats();
  const canais = stats.channels;
  if (canais.length < 3) return true;

  const [r, g, b] = canais;
  const diferencaMaxima = Math.max(
    Math.abs(r.mean - g.mean),
    Math.abs(g.mean - b.mean),
    Math.abs(r.mean - b.mean)
  );
  return diferencaMaxima < 6;
}

// converte uma imagem para CMYK (ou grayscale puro) e devolve como JPEG buffer
// pdfkit não lê TIFF/CMYK nativamente de forma simples, então mantemos JPEG
// mas já com o espaço de cor correto definido via sharp antes de embutir no PDF
async function prepararImagem(buffer) {
  const grayscale = await ehGrayscale(buffer);

  const imagem = sharp(buffer).rotate(); // corrige orientação EXIF

  if (grayscale) {
    return {
      buffer: await imagem.toColorspace('b-w').jpeg({ quality: 95 }).toBuffer(),
      grayscale: true,
    };
  }

  return {
    buffer: await imagem.jpeg({ quality: 95 }).toBuffer(),
    grayscale: false,
  };
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

// CAMINHO DO PERFIL ICC usado na declaração de OutputIntent do PDF/X-1a.
//
// ATENÇÃO: este é um perfil GENÉRICO de mercado (Coated FOGRA39), usado
// apenas para o PDF sair estruturalmente completo neste protótipo.
// NÃO é o perfil real da UmLivro/Meta. Quando a Bianca fornecer o perfil
// real, troque o arquivo dentro de /perfis-icc e ajuste o nome abaixo.
const NOME_ARQUIVO_PERFIL_ICC = 'FOGRA39L_coated.icc';
const CAMINHO_PERFIL_ICC = path.join(__dirname, 'perfis-icc', NOME_ARQUIVO_PERFIL_ICC);
const CAMINHO_DEFINICAO_PDFX = path.join(__dirname, 'PDFX_def_lvh.ps');

// Gera o arquivo de definição PDFX (.ps) usando o caminho absoluto do
// AMBIENTE ATUAL em que o servidor está rodando. Isso é feito em tempo de
// execução (não commitado no Git) justamente para nunca depender de um
// caminho fixo gravado em outra máquina (ex: ambiente de teste local vs.
// container de produção no Render, que têm estruturas de pasta diferentes).
function gerarArquivoDefinicaoPdfx() {
  const template = `%!
% Arquivo de definicao PDFX gerado automaticamente na inicializacao do servidor.
% Nao edite manualmente nem comite este arquivo: ele e regenerado a cada start.

systemdict /ColorConversionStrategy known {
  systemdict /ColorConversionStrategy get cvn dup /Gray ne exch /CMYK ne and
} {
  (\\nERROR: ColorConversionStrategy not set.)=
  true
} ifelse
{ (ERROR: ColorConversionStrategy must be /DeviceGray or /DeviceCMYK.)=
  /ColorConversionStrategy cvx /rangecheck signalerror
} if

[ /GTS_PDFXVersion (PDF/X-1a:2001)
  /Title (La vem historia - PDF X-1a)
  /Trapped /False
/DOCINFO pdfmark

/ICCProfile (${CAMINHO_PERFIL_ICC}) def

currentdict /ICCProfile known {
  [/_objdef {icc_PDFX} /type /stream /OBJ pdfmark
  [{icc_PDFX} <<
  systemdict /ColorConversionStrategy known {
    systemdict /ColorConversionStrategy get cvn dup /Gray eq {
      pop /N 1 false
    }{
      dup /RGB eq {
        (RGB is not a valid ColorConversionStrategy for PDF/X output)=
        /ColorConversionStrategycvx /rangecheck signalerror
      }{
        /CMYK eq {
          /N 4 false
        }{
          (ColorConversionStrategy not a device space, falling back to ProcessColorModel, output may not be valid PDF/X.)=
          true
        } ifelse
      } ifelse
    } ifelse
  } {
    (ColorConversionStrategy not set, falling back to ProcessColorModel, output may not be valid PDF/X.)=
    true
  } ifelse
  {
    currentpagedevice /ProcessColorModel get
    dup /DeviceGray eq {
      pop /N 1
    }{
      dup /DeviceRGB eq {
        (RGB is not a valid ProcessColorModel for PDF/X output)=
        /ColorConversionStrategycvx /rangecheck signalerror
      }{
        dup /DeviceCMYK eq {
          pop /N 4
        } {
          (ProcessColorModel not a device space.)=
          /ProcessColorModel cvx /rangecheck signalerror
        } ifelse
      } ifelse
    } ifelse
  } if
  >> /PUT pdfmark
  [{icc_PDFX} ICCProfile (r) file /PUT pdfmark
} if

[/_objdef {OutputIntent_PDFX} /type /dict /OBJ pdfmark
[{OutputIntent_PDFX} <<
  /Type /OutputIntent
  /S /GTS_PDFX
  /OutputCondition (FOGRA39 generico - aguardando perfil real da UmLivro)
  /Info (FOGRA39 generico - aguardando perfil real da UmLivro)
  /OutputConditionIdentifier (FOGRA39)
  /RegistryName (http://www.color.org)
  currentdict /ICCProfile known {
    /DestOutputProfile {icc_PDFX}
  } if
>> /PUT pdfmark
[{Catalog} <</OutputIntents [ {OutputIntent_PDFX} ]>> /PUT pdfmark
`;

  fs.writeFileSync(CAMINHO_DEFINICAO_PDFX, template, 'latin1');
  console.log(`Arquivo de definição PDFX gerado em: ${CAMINHO_DEFINICAO_PDFX}`);
  console.log(`Usando perfil ICC: ${CAMINHO_PERFIL_ICC}`);
}

gerarArquivoDefinicaoPdfx();

// roda Ghostscript para converter o PDF base em PDF/X-1a:2001 de verdade,
// incluindo a declaração de OutputIntent (exigida pela especificação X-1a).
// A ordem dos argumentos importa: o arquivo de definição PDFX precisa vir
// ANTES do PDF de entrada, pois ele injeta os pdfmarks no fluxo de processamento.
function converterParaX1a(caminhoEntrada, caminhoSaida) {
  return new Promise((resolve, reject) => {
    const args = [
      '-dPDFX',
      '-dBATCH',
      '-dNOPAUSE',
      '-dNOSAFER', // necessário para o Ghostscript ler o perfil ICC referenciado no .ps
      '-sColorConversionStrategy=CMYK',
      '-sProcessColorModel=DeviceCMYK',
      '-sDEVICE=pdfwrite',
      '-dCompatibilityLevel=1.3',
      `-sOutputFile=${caminhoSaida}`,
      CAMINHO_DEFINICAO_PDFX,
      caminhoEntrada,
    ];

    execFile('gs', args, (erro, stdout, stderr) => {
      if (erro) {
        console.error('Erro no Ghostscript:', stderr);
        return reject(erro);
      }
      resolve();
    });
  });
}

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
    await converterParaX1a(caminhoPdfBase, caminhoPdfFinal);

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
