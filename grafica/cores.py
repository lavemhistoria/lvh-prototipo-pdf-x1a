"""
Conversão de cor para a gráfica.

Duas regras do manual da Meta guiam tudo aqui:
- cobertura máxima de tinta de 280% (soma C+M+Y+K);
- cinza e preto em preto puro (K), nunca em 4 cores.

Por isso cores neutras (texto, legendas, fios, QR code) viram só K, com a
mesma luminosidade (L*) da cor original. Cores com matiz passam pelo perfil
ICC de destino e depois pelo limite de tinta.
"""

import io
import math

import numpy as np
from PIL import Image, ImageCms

# Abaixo deste croma (C*ab) a cor é tratada como neutra e vira só K.
# O marrom da tinta do livro (#2a231c) tem croma por volta de 7, as legendas
# (#9a8f80) por volta de 8: os dois entram como neutros, que é o desejado.
LIMITE_NEUTRO = 12.0

# A cobertura máxima do manual é 280%. Miramos um pouco abaixo para absorver
# a variação da recompressão JPEG feita depois pelo Ghostscript.
TAC_MAXIMO = 280.0
TAC_ALVO = 272.0


class Cores:
    def __init__(self, caminho_icc_destino, tac_alvo=TAC_ALVO):
        self.tac_alvo = tac_alvo
        self.srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
        self.lab = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB', colorTemp=5000))
        self.destino = ImageCms.ImageCmsProfile(caminho_icc_destino)

        flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if hasattr(ImageCms, 'Flags') else 0x2000
        self._flags = flags

        # Cores chapadas: colorimétrico relativo, para o tom bater com a tela
        self._rgb_para_cmyk = ImageCms.buildTransform(
            self.srgb, self.destino, 'RGB', 'CMYK',
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, flags=flags)
        self._rgb_para_lab = ImageCms.buildTransform(
            self.srgb, self.lab, 'RGB', 'LAB',
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
        self._cmyk_para_lab = ImageCms.buildTransform(
            self.destino, self.lab, 'CMYK', 'LAB',
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)

        self._tabela_k = self._montar_tabela_k()

    # Para cada K de 0 a 100%, qual L* ele produz no papel do perfil.
    # Invertendo a tabela, achamos o K que reproduz a luminosidade de um cinza.
    def _montar_tabela_k(self):
        amostras = np.zeros((1, 256, 4), dtype=np.uint8)
        amostras[0, :, 3] = np.arange(256)
        lab = ImageCms.applyTransform(_cmyk_img(amostras), self._cmyk_para_lab)
        l_estrela = np.asarray(lab)[0, :, 0].astype(float) * 100 / 255
        # L* cai conforme K sobe; np.interp precisa de x crescente
        return l_estrela[::-1], np.arange(256)[::-1]

    def k_para_luminosidade(self, l_estrela):
        """Valor de K (0 a 255) que reproduz o L* pedido."""
        xs, ks = self._tabela_k
        return np.interp(l_estrela, xs, ks)

    def lab_de_rgb(self, rgb_array):
        img = Image.fromarray(rgb_array)
        lab = np.asarray(ImageCms.applyTransform(img, self._rgb_para_lab))
        l_estrela = lab[..., 0].astype(float) * 100 / 255
        # No modo LAB do Pillow, a e b vêm como inteiros com sinal (int8) guardados em uint8
        a = lab[..., 1].view(np.int8).astype(float)
        b = lab[..., 2].view(np.int8).astype(float)
        return l_estrela, a, b

    def limitar_tinta(self, cmyk):
        """Reduz C, M e Y onde a soma passa do alvo, preservando o K.

        cmyk: array uint8 (..., 4). Devolve uint8.
        """
        c = cmyk.astype(np.float32)
        total = c.sum(axis=-1)
        limite = self.tac_alvo * 255 / 100
        excesso = total > limite
        if not excesso.any():
            return cmyk
        k = c[..., 3]
        cmy = c[..., :3]
        soma_cmy = cmy.sum(axis=-1)
        disponivel = np.maximum(limite - k, 0)
        fator = np.where(excesso & (soma_cmy > 0), disponivel / np.maximum(soma_cmy, 1e-6), 1.0)
        cmy = cmy * fator[..., None]
        # Se o K sozinho já passa do limite (não acontece com perfis normais), corta o K
        k = np.minimum(k, limite)
        saida = np.concatenate([cmy, k[..., None]], axis=-1)
        return np.clip(np.round(saida), 0, 255).astype(np.uint8)

    # Cor chapada (texto, fios, fundos): devolve (c, m, y, k) entre 0 e 1
    def cor_vetorial(self, r, g, b):
        rgb = np.array([[[round(r * 255), round(g * 255), round(b * 255)]]], dtype=np.uint8)
        l_estrela, a, bb = self.lab_de_rgb(rgb)
        croma = math.hypot(float(a[0, 0]), float(bb[0, 0]))
        if croma < LIMITE_NEUTRO:
            k = float(self.k_para_luminosidade(l_estrela[0, 0]))
            # Branco de verdade continua sem tinta nenhuma
            if r > 0.995 and g > 0.995 and b > 0.995:
                k = 0
            return (0.0, 0.0, 0.0, round(k / 255, 4))
        cmyk = np.asarray(ImageCms.applyTransform(Image.fromarray(rgb), self._rgb_para_cmyk))
        cmyk = self.limitar_tinta(cmyk)[0, 0]
        return tuple(round(float(v) / 255, 4) for v in cmyk)

    def cores_para_cmyk(self, rgb_array):
        """Elementos gráficos (não fotos): colorimétrico relativo, como as cores chapadas."""
        return np.asarray(ImageCms.applyTransform(Image.fromarray(rgb_array), self._rgb_para_cmyk))

    def eh_neutra(self, rgb_array):
        """Foto em preto e branco (ou quase): croma médio muito baixo."""
        # Amostra reduzida, a decisão não precisa de todos os pixels
        img = Image.fromarray(rgb_array)
        img.thumbnail((400, 400))
        _, a, b = self.lab_de_rgb(np.asarray(img))
        croma = np.hypot(a, b)
        return float(np.percentile(croma, 95)) < 4.0

    def foto_para_k(self, rgb_array):
        """Foto P&B vira só K. Devolve array de cinza no sentido PDF DeviceGray (1 = branco)."""
        l_estrela, _, _ = self.lab_de_rgb(rgb_array)
        k = self.k_para_luminosidade(l_estrela)
        return np.clip(np.round(255 - k), 0, 255).astype(np.uint8)

    def foto_para_cmyk(self, img_rgb, perfil_origem=None):
        origem = perfil_origem or self.srgb
        transformacao = ImageCms.buildTransform(
            origem, self.destino, 'RGB', 'CMYK',
            renderingIntent=ImageCms.Intent.PERCEPTUAL, flags=self._flags)
        cmyk = np.asarray(ImageCms.applyTransform(img_rgb, transformacao))
        return self.limitar_tinta(cmyk)


def _cmyk_img(arr):
    return Image.frombytes('CMYK', (arr.shape[1], arr.shape[0]), np.ascontiguousarray(arr).tobytes())


def perfil_de_bytes(dados_icc):
    try:
        return ImageCms.ImageCmsProfile(io.BytesIO(dados_icc))
    except Exception:
        return None
