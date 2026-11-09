"""Gera o vídeo de encerramento (outro) do Handcut.

A bola rola da direita para a esquerda e o letreiro aparece (da direita para
a esquerda) conforme a bola passa, até ela parar na posição do logo.

Uso (na pasta do projeto):
    python tools/make_outro.py
    python tools/make_outro.py --bola assets/bola.png --letreiro assets/letreiro.png --saida outro.mp4

Precisa de: Pillow (pip install pillow) e FFmpeg instalado.
"""
import argparse
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance

# ---------- Ajustes (pode mexer nestes valores) ----------
LARGURA, ALTURA, FPS = 1280, 720, 30   # mesmo formato das exportações (720p, 30 fps)
DIAMETRO_BOLA = 500                    # tamanho da bola em pixels
LARGURA_LETREIRO = 560                 # largura do letreiro em pixels
FOLGA = 40                             # espaço entre a bola e o letreiro, no final
T_ROLAGEM = 2.0                        # segundos que a bola leva para rolar
T_PARADO = 1.0                         # segundos com o logo parado no final
T_FADE = 0.4                           # segundos do escurecimento final
# ---------------------------------------------------------


def preparar_bola(caminho):
    """Abre a bola, acha onde ela está na imagem e recorta em círculo limpo."""
    img = Image.open(caminho).convert("RGBA")
    alfa = img.getchannel("A")

    if alfa.getextrema()[0] < 250:
        # A imagem tem transparência de verdade: a bola é onde alfa > 0.
        caixa = alfa.point(lambda v: 255 if v > 10 else 0).getbbox()
    else:
        # Fundo branco: a bola é tudo que não é (quase) branco.
        r, g, b = img.convert("RGB").split()
        minimo = ImageChops.darker(ImageChops.darker(r, g), b)
        caixa = minimo.point(lambda v: 255 if v < 235 else 0).getbbox()

    if caixa is None:
        sys.exit("Não encontrei a bola na imagem. Confira o arquivo.")
    print(f"Bola encontrada na área {caixa} (esquerda, topo, direita, base)")

    # Recorta um quadrado centrado na bola.
    cx = (caixa[0] + caixa[2]) / 2
    cy = (caixa[1] + caixa[3]) / 2
    lado = min(caixa[2] - caixa[0], caixa[3] - caixa[1])
    esq, topo = round(cx - lado / 2), round(cy - lado / 2)
    img = img.crop((esq, topo, esq + lado, topo + lado))

    # Máscara circular (desenhada em tamanho 4x e reduzida, para a borda ficar suave).
    mascara = Image.new("L", (lado * 4, lado * 4), 0)
    ImageDraw.Draw(mascara).ellipse((0, 0, lado * 4 - 1, lado * 4 - 1), fill=255)
    mascara = mascara.resize((lado, lado), Image.LANCZOS)
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mascara))

    return img.resize((DIAMETRO_BOLA, DIAMETRO_BOLA), Image.LANCZOS)


def preparar_letreiro(caminho):
    """Abre o letreiro (fundo preto), tira a sobra de preto e ajusta o tamanho."""
    img = Image.open(caminho)
    if "A" in img.getbands():
        fundo = Image.new("RGB", img.size, (0, 0, 0))
        fundo.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
        img = fundo
    img = img.convert("RGB")
    caixa = img.convert("L").point(lambda v: 255 if v > 40 else 0).getbbox()
    if caixa is None:
        sys.exit("Não encontrei o letreiro na imagem. Confira o arquivo.")
    img = img.crop(caixa)
    altura = round(img.height * LARGURA_LETREIRO / img.width)
    return img.resize((LARGURA_LETREIRO, altura), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser(description="Gera o outro animado do Handcut")
    ap.add_argument("--bola", default="assets/bola.png")
    ap.add_argument("--letreiro", default="assets/letreiro.png")
    ap.add_argument("--saida", default="outro.mp4")
    args = ap.parse_args()

    bola = preparar_bola(args.bola)
    letreiro = preparar_letreiro(args.letreiro)
    raio = DIAMETRO_BOLA / 2

    # Posição final do logo: bola + folga + letreiro, centralizados na tela.
    largura_total = DIAMETRO_BOLA + FOLGA + letreiro.width
    x_inicio = (LARGURA - largura_total) / 2
    cx_final = x_inicio + raio                       # centro da bola no final
    cx_inicial = LARGURA + raio                      # bola começa fora da tela, à direita
    texto_x = round(x_inicio + DIAMETRO_BOLA + FOLGA)
    texto_y = round((ALTURA - letreiro.height) / 2)
    cy = ALTURA / 2

    duracao = T_ROLAGEM + T_PARADO
    n_quadros = round(duracao * FPS)

    ffmpeg = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{LARGURA}x{ALTURA}",
        "-r", str(FPS), "-i", "-",
        # trilha de áudio em silêncio, para o vídeo poder ser emendado nas exportações
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", f"{duracao}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart",
        args.saida,
    ]
    proc = subprocess.Popen(ffmpeg, stdin=subprocess.PIPE)

    for i in range(n_quadros):
        t = i / FPS

        # Posição da bola: começa rápida e desacelera até parar (ease-out).
        p = min(t / T_ROLAGEM, 1.0)
        suave = 1 - (1 - p) ** 3
        cx = cx_inicial + (cx_final - cx_inicial) * suave

        # Rolar sem escorregar: ângulo = distância percorrida / raio.
        # Indo para a esquerda, a bola gira no sentido anti-horário.
        percorrido = cx_inicial - cx
        angulo = math.degrees(percorrido / raio)

        quadro = Image.new("RGB", (LARGURA, ALTURA), (0, 0, 0))
        quadro.paste(letreiro, (texto_x, texto_y))

        # Esconde o letreiro à esquerda do centro da bola: só aparece o que a bola já passou.
        ImageDraw.Draw(quadro).rectangle((0, 0, round(cx), ALTURA), fill=(0, 0, 0))

        girada = bola.rotate(angulo, resample=Image.BICUBIC)
        quadro.paste(girada, (round(cx - raio), round(cy - raio)), girada)

        # Escurece no final.
        resta = duracao - t
        if resta < T_FADE:
            quadro = ImageEnhance.Brightness(quadro).enhance(max(resta / T_FADE, 0))

        proc.stdin.write(quadro.tobytes())

    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        sys.exit("O FFmpeg deu erro. Confira se ele está instalado.")
    print(f"Pronto: {args.saida} ({duracao:.1f} s, {LARGURA}x{ALTURA}, {FPS} fps)")


if __name__ == "__main__":
    main()