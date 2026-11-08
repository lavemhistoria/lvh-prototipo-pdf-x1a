"""
Motor da gráfica: transforma o PDF do livro (RGB, gerado pelo navegador a partir
das mesmas páginas da pré-visualização) no PDF/X-1a do manual da Meta.

Etapas:
1. preparar: cores para CMYK, preto e cinza em K, fotos com limite de 280%
2. acabamento: formato exato, sangria de 3 mm, marcas de corte e informações de página
3. Ghostscript: fecha o PDF/X-1a:2001 (PDF 1.3, OutputIntent, fontes embutidas, 300 dpi)
4. validar: nada segue para a gráfica com erro

Uso: python pipeline.py entrada.pdf saida.pdf [--largura 148 --altura 210] [--icc perfil.icc]
Imprime um relatório JSON; código de saída 0 só quando o PDF passou na validação.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pikepdf

import acabamento
import fundo as camada_fundo
from cores import Cores
from preparar import Preparador
from validar import bordas_sem_sangria, validar

AQUI = os.path.dirname(os.path.abspath(__file__))

# Perfil genérico de mercado até a Bianca (UmLivro) mandar o real.
# Ao trocar, ajuste também os textos de OutputCondition abaixo.
ICC_PADRAO = os.path.join(AQUI, '..', 'perfis-icc', 'FOGRA39L_coated.icc')
CONDICAO = {
    'identificador': 'FOGRA39',
    'descricao': 'FOGRA39 generico - aguardando perfil real da UmLivro',
}


def _definicao_pdfx(caminho_icc, titulo):
    # Mesmo arquivo de definição que o server.js gerava, agora aqui.
    # O caminho do ICC precisa ser ASCII: por isso tudo roda numa pasta temporária.
    return f"""%!
systemdict /ColorConversionStrategy known {{
  systemdict /ColorConversionStrategy get cvn dup /Gray ne exch /CMYK ne and
}} {{
  (\\nERROR: ColorConversionStrategy not set.)=
  true
}} ifelse
{{ (ERROR: ColorConversionStrategy must be /DeviceGray or /DeviceCMYK.)=
  /ColorConversionStrategy cvx /rangecheck signalerror
}} if

[ /GTS_PDFXVersion (PDF/X-1a:2001)
  /Title ({titulo})
  /Trapped /False
/DOCINFO pdfmark

/ICCProfile ({caminho_icc}) def

[/_objdef {{icc_PDFX}} /type /stream /OBJ pdfmark
[{{icc_PDFX}} << /N 4 >> /PUT pdfmark
[{{icc_PDFX}} ICCProfile (r) file /PUT pdfmark

[/_objdef {{OutputIntent_PDFX}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFX}} <<
  /Type /OutputIntent
  /S /GTS_PDFX
  /OutputCondition ({CONDICAO['descricao']})
  /Info ({CONDICAO['descricao']})
  /OutputConditionIdentifier ({CONDICAO['identificador']})
  /RegistryName (http://www.color.org)
  /DestOutputProfile {{icc_PDFX}}
>> /PUT pdfmark
[{{Catalog}} <</OutputIntents [ {{OutputIntent_PDFX}} ]>> /PUT pdfmark
"""


DICIONARIO_JPEG = (
    '<< /ColorImageDict << /QFactor 0.15 /Blend 1 /HSamples [1 1 1 1] /VSamples [1 1 1 1] >> '
    '/GrayImageDict << /QFactor 0.15 /Blend 1 /HSamples [1 1 1 1] /VSamples [1 1 1 1] >> '
    '>> setdistillerparams'
)


def _ghostscript(entrada, saida, definicao):
    # Ordem importa: opções, -sOutputFile, arquivo de definição, PDF de entrada
    args = [
        'gs', '-dPDFX', '-dBATCH', '-dNOPAUSE', '-dNOSAFER', '-dQUIET',
        '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.3',
        '-sColorConversionStrategy=CMYK', '-sProcessColorModel=DeviceCMYK',
        '-dEmbedAllFonts=true', '-dSubsetFonts=true',
        # Fotos a 300 dpi (só reduz o que passar de 450 dpi), JPEG de alta qualidade
        '-dDownsampleColorImages=true', '-dColorImageResolution=300',
        '-dColorImageDownsampleThreshold=1.5', '-dColorImageDownsampleType=/Bicubic',
        '-dDownsampleGrayImages=true', '-dGrayImageResolution=300',
        '-dGrayImageDownsampleThreshold=1.5', '-dGrayImageDownsampleType=/Bicubic',
        '-dDownsampleMonoImages=true', '-dMonoImageResolution=1200',
        '-dAutoFilterColorImages=false', '-sColorImageFilter=DCTEncode',
        '-dAutoFilterGrayImages=false', '-sGrayImageFilter=DCTEncode',
        f'-sOutputFile={saida}',
        # Qualidade JPEG "máxima" do Distiller, sem subamostragem de cor: a subamostragem
        # padrão cria halos que passam do limite de 280% nas bordas das fotos
        '-c', DICIONARIO_JPEG, '-f',
        definicao,
        entrada,
    ]
    resultado = subprocess.run(args, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f'Ghostscript falhou: {resultado.stderr or resultado.stdout}')
    return resultado.stdout.strip()


def gerar(entrada, saida, largura_mm=148.0, altura_mm=210.0, caminho_icc=ICC_PADRAO,
          nome='La vem historia', manter_intermediarios=False, fundo=None):
    """entrada: PDF do livro (ou a camada de frente, quando há fundo).
    fundo: camada de fundo do modo gráfica do site, achatada em imagem por baixo da frente."""
    relatorio = {'etapas': {}}
    pasta = tempfile.mkdtemp(prefix='lvh_grafica_')
    try:
        icc = os.path.join(pasta, 'destino.icc')
        shutil.copyfile(caminho_icc, icc)
        cmyk = os.path.join(pasta, '1_cmyk.pdf')
        x1a = os.path.join(pasta, '2_x1a.pdf')
        definicao = os.path.join(pasta, 'pdfx_def.ps')

        # 1. Cores
        cores = Cores(icc)
        with pikepdf.open(entrada) as pdf:
            rel = Preparador(pdf, cores).executar()
            if fundo:
                camada_fundo.aplicar(pdf, fundo, cores, rel)
            relatorio['etapas']['cores'] = {
                'fotos_cmyk': rel.fotos_cmyk,
                'fotos_preto_e_branco_em_k': rel.fotos_k,
                'cores_convertidas': rel.cores_convertidas,
                'opacidades_achatadas': rel.opacidades_achatadas,
                'paginas_com_fundo': rel.fundos,
            }
            avisos = list(rel.avisos)

            # 2. Sangria e marcas
            avisos += acabamento.aplicar(pdf, largura_mm, altura_mm, nome)
            caixas = acabamento.caixas(pdf)
            pdf.save(cmyk)

        # 3. PDF/X-1a
        with open(definicao, 'w', encoding='latin-1') as arq:
            arq.write(_definicao_pdfx(icc, nome.encode('ascii', 'replace').decode()))
        saida_gs = _ghostscript(cmyk, x1a, definicao)
        if saida_gs:
            avisos.append(f'Ghostscript: {saida_gs[:300]}')

        # O Ghostscript pode refazer as caixas da página; garantimos as nossas
        with pikepdf.open(x1a) as pdf:
            acabamento.reaplicar_caixas(pdf, caixas)
            pdf.save(saida, force_version='1.3', fix_metadata_version=False)

        # 4. Validação
        resultado = validar(saida, largura_mm, altura_mm)
        encostam = bordas_sem_sangria(saida)
        if encostam:
            avisos.append(
                f'{"Páginas" if len(encostam) > 1 else "Página"} {", ".join(map(str, encostam))}: conteúdo encosta na linha de corte sem '
                'sangria. Pode sair um filete branco na borda (capa no miolo? papel creme?).')
        resultado['avisos'] = avisos + resultado['avisos']
        if rel.erros:
            resultado['erros'] = rel.erros + resultado['erros']
            resultado['ok'] = False
        resultado['etapas'] = relatorio['etapas']
        if manter_intermediarios:
            resultado['intermediarios'] = pasta
        return resultado
    finally:
        if not manter_intermediarios:
            shutil.rmtree(pasta, ignore_errors=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('entrada')
    p.add_argument('saida')
    p.add_argument('--largura', type=float, default=148.0, help='formato final em mm')
    p.add_argument('--altura', type=float, default=210.0, help='formato final em mm')
    p.add_argument('--icc', default=ICC_PADRAO)
    p.add_argument('--nome', default='La vem historia')
    p.add_argument('--fundo', help='camada de fundo do modo gráfica (?grafica=fundo); a entrada é a frente')
    p.add_argument('--manter-intermediarios', action='store_true')
    a = p.parse_args()
    try:
        r = gerar(a.entrada, a.saida, a.largura, a.altura, a.icc, a.nome, a.manter_intermediarios, a.fundo)
    except Exception as erro:
        r = {'ok': False, 'erros': [str(erro)], 'avisos': [], 'info': {}}
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r['ok'] else 1)
