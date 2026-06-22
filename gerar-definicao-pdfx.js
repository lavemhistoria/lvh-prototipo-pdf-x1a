/**
 * GERADOR DO ARQUIVO DE DEFINIÇÃO PDFX (PDFX_def_lvh.ps)
 *
 * Este script gera o arquivo PostScript que o Ghostscript usa para declarar
 * o OutputIntent (perfil ICC de saída) no PDF/X-1a final.
 *
 * QUANDO RODAR ESTE SCRIPT:
 * Toda vez que você precisar trocar o perfil ICC (por exemplo, quando a
 * Bianca, da UmLivro, fornecer o perfil ICC real da gráfica).
 *
 * COMO USAR:
 * node gerar-definicao-pdfx.js caminho/para/perfil.icc "Nome do perfil"
 *
 * Exemplo com o perfil genérico de teste:
 * node gerar-definicao-pdfx.js perfis-icc/FOGRA39L_coated.icc "FOGRA39"
 *
 * Exemplo de uso futuro, com perfil real da gráfica:
 * node gerar-definicao-pdfx.js perfis-icc/perfil-umlivro.icc "Perfil UmLivro"
 */

const fs = require('fs');
const path = require('path');

const caminhoPerfilIcc = process.argv[2];
const nomePerfil = process.argv[3] || 'Perfil personalizado';

if (!caminhoPerfilIcc) {
  console.error('Uso: node gerar-definicao-pdfx.js caminho/para/perfil.icc "Nome do perfil"');
  process.exit(1);
}

const caminhoAbsolutoPerfil = path.resolve(caminhoPerfilIcc);

if (!fs.existsSync(caminhoAbsolutoPerfil)) {
  console.error(`Arquivo de perfil ICC não encontrado: ${caminhoAbsolutoPerfil}`);
  process.exit(1);
}

// template baseado no arquivo PDFX_def.ps que acompanha o Ghostscript,
// adaptado para PDF/X-1a:2001 (em vez do X-3:2002 original) e com os
// campos de identificação do produto já preenchidos.
const template = `%!
% Arquivo de definição PDFX gerado automaticamente.
% Gerado por gerar-definicao-pdfx.js. Não edite manualmente, regenere o
% arquivo executando o script novamente com o perfil ICC desejado.

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

/ICCProfile (${caminhoAbsolutoPerfil}) def

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
  /OutputCondition (${nomePerfil})
  /Info (${nomePerfil})
  /OutputConditionIdentifier (${nomePerfil})
  /RegistryName (http://www.color.org)
  currentdict /ICCProfile known {
    /DestOutputProfile {icc_PDFX}
  } if
>> /PUT pdfmark
[{Catalog} <</OutputIntents [ {OutputIntent_PDFX} ]>> /PUT pdfmark
`;

const caminhoSaida = path.join(__dirname, 'PDFX_def_lvh.ps');
fs.writeFileSync(caminhoSaida, template, 'latin1');

console.log(`Arquivo gerado: ${caminhoSaida}`);
console.log(`Perfil ICC usado: ${caminhoAbsolutoPerfil}`);
console.log(`Nome do perfil: ${nomePerfil}`);
console.log(`\nReinicie o servidor (server.js) para usar a nova definição.`);
