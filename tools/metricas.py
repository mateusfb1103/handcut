"""Regras oficiais de medição da Fase 2 (sugestão automática de lances).

Este módulo não usa o YOLO nem o vídeo: só compara intervalos. Fica separado para poder ser
testado automaticamente (tests/test_metricas.py) e reaproveitado pelos scripts de avaliação.

Regras combinadas (ver .md/Protocolo de Testes Fase 2.md):

- Recall: um lance do gabarito do tipo pedido conta como ENCONTRADO quando a SOMA dos pedaços
  de sugestões do mesmo tipo cobre pelo menos metade dele.
- Lance PARTIDO: lance encontrado que recebeu 2 ou mais sugestões (cada uma cobrindo pelo menos
  1 s dele). É registrado à parte, porque pesa no tempo de revisão.
- Sugestão CORRETA: cobre algum lance do tipo pedido (parcial também vale, porque um lance pode
  ter vários ataques). O piso mínimo de sobreposição AINDA ESTÁ EM ABERTO; por padrão vale
  qualquer sobreposição maior que zero (regra literal combinada).
- Sugestão ERRADA: tipo trocado (cobre só lances do tipo oposto) ou fora de qualquer lance.
- Lances "opcionais" (ambíguos no gabarito) não contam no recall, e uma sugestão que cai só
  neles é "neutra" (nem certa nem errada).
- Trechos "ignorar" (encerramento, replay, etc.) e ±5 s ao redor de cada "emenda" são
  retirados tanto do gabarito quanto das sugestões antes de contar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ATAQUE, DEFESA = "ataque", "defesa"
OPOSTO = {ATAQUE: DEFESA, DEFESA: ATAQUE}

RECALL_MIN_COVERAGE = 0.50     # metade do lance precisa estar coberta
SPLIT_MIN_OVERLAP = 1.0        # um pedaço precisa cobrir ao menos 1 s para contar como "partido"
SPLICE_MARGIN = 5.0            # segundos excluídos antes e depois de cada emenda
# Estimativa de revisão (só até existir a tela de revisão da Fase 5; não é medição real).
REVIEW_SECONDS_PER_SUGGESTION = 12.0
REVIEW_SECONDS_PER_SPLIT = 10.0

META_RECALL = 0.90
META_ERRADAS_POR_CORRETA = 0.50
META_REVISAO_SEGUNDOS = 15 * 60
META_TEMPO_ANALISE = 1.0       # tempo de análise / duração analisada


# =====================================================================================
# Gabarito
# =====================================================================================
@dataclass
class Lance:
    kind: str          # "ataque" ou "defesa", do ponto de vista do time de referência
    start: float
    end: float
    optional: bool = False


@dataclass
class Gabarito:
    lances: list[Lance] = field(default_factory=list)
    ignorar: list[tuple[float, float]] = field(default_factory=list)
    emendas: list[float] = field(default_factory=list)

    def invertido(self) -> "Gabarito":
        """O mesmo gabarito visto pelo time adversário (ataque vira defesa e vice-versa)."""
        return Gabarito([Lance(OPOSTO[l.kind], l.start, l.end, l.optional) for l in self.lances],
                        list(self.ignorar), list(self.emendas))

    def zonas_excluidas(self, margem: float = SPLICE_MARGIN) -> list[tuple[float, float]]:
        zonas = list(self.ignorar) + [(max(0.0, t - margem), t + margem) for t in self.emendas]
        return unir(zonas)


def parse_time(text: str) -> float:
    """'1:05', '01:05', '1:02:03' ou '65.5' -> segundos."""
    seconds = 0.0
    for part in text.strip().split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def ler_gabarito(path: Path) -> Gabarito:
    return parse_gabarito(path.read_text(encoding="utf-8"), path.name)


def parse_gabarito(text: str, nome: str = "gabarito") -> Gabarito:
    """Formato (uma instrução por linha; '#' começa um comentário):

        ataque  0:20 0:44
        defesa  0:45 0:52 opcional     # lance ambíguo: não conta no recall nem como erro
        ignorar 2:46 2:50              # encerramento, replay, tela parada...
        emenda  0:57                   # corte entre dois trechos: exclui ±5 s ao redor
    """
    gabarito = Gabarito()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        word = parts[0].lower()
        try:
            if word in (ATAQUE, DEFESA) and len(parts) in (3, 4):
                optional = len(parts) == 4
                if optional and parts[3].lower() != "opcional":
                    raise ValueError
                start, end = parse_time(parts[1]), parse_time(parts[2])
                if end <= start:
                    raise ValueError
                gabarito.lances.append(Lance(word, start, end, optional))
            elif word == "ignorar" and len(parts) == 3:
                start, end = parse_time(parts[1]), parse_time(parts[2])
                if end <= start:
                    raise ValueError
                gabarito.ignorar.append((start, end))
            elif word == "emenda" and len(parts) == 2:
                gabarito.emendas.append(parse_time(parts[1]))
            else:
                raise ValueError
        except ValueError:
            raise ValueError(
                f"{nome}, linha {number}: não entendi '{raw.strip()}'. Use 'ataque|defesa INÍCIO FIM "
                f"[opcional]', 'ignorar INÍCIO FIM' ou 'emenda TEMPO'.") from None
    gabarito.lances.sort(key=lambda l: (l.start, l.end))
    return gabarito


# =====================================================================================
# Intervalos
# =====================================================================================
def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def unir(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def subtrair(start: float, end: float, zonas: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pedaços de [start, end] que ficam fora das zonas excluídas."""
    pieces = [(start, end)]
    for z_start, z_end in zonas:
        next_pieces = []
        for a, b in pieces:
            if z_end <= a or z_start >= b:
                next_pieces.append((a, b))
                continue
            if z_start > a:
                next_pieces.append((a, z_start))
            if z_end < b:
                next_pieces.append((z_end, b))
        pieces = next_pieces
    return [(a, b) for a, b in pieces if b - a > 1e-6]


# =====================================================================================
# Métricas
# =====================================================================================
def piso_sobreposicao(duracao_lance: float, piso_segundos: float = 0.0, piso_fracao: float = 0.0) -> float:
    """Sobreposição mínima para uma sugestão parcial contar como correta.

    0 e 0 (padrão) = qualquer sobreposição maior que zero. Com os dois valores, vale o menor
    entre `piso_segundos` e `piso_fracao` x duração do lance (decisão ainda em aberto).
    """
    candidatos = []
    if piso_segundos > 0:
        candidatos.append(piso_segundos)
    if piso_fracao > 0:
        candidatos.append(piso_fracao * duracao_lance)
    return min(candidatos) if candidatos else 0.0


def _cobre(sobreposicao: float, piso: float) -> bool:
    return sobreposicao > 1e-6 and sobreposicao >= piso


def avaliar(gabarito: Gabarito, sugestoes: list[dict], kind: str, *, piso_segundos: float = 0.0,
            piso_fracao: float = 0.0, margem_emenda: float = SPLICE_MARGIN) -> dict:
    """Compara as sugestões de um tipo (`kind`) com o gabarito, já do ponto de vista do time pedido.

    `sugestoes` é a lista [{start, end}, ...] devolvida pelo detector para esse tipo.
    """
    zonas = gabarito.zonas_excluidas(margem_emenda)

    # Gabarito e sugestões sem as zonas excluídas (um lance pode virar dois pedaços).
    lances = []  # (lance original, pedaços válidos)
    for lance in gabarito.lances:
        pieces = subtrair(lance.start, lance.end, zonas)
        if pieces:
            lances.append((lance, pieces))
    sug_pieces = []
    for item in sugestoes:
        pieces = subtrair(float(item["start"]), float(item["end"]), zonas)
        if pieces:
            sug_pieces.append(((float(item["start"]), float(item["end"])), pieces))

    def sobreposicao(pieces_a, pieces_b) -> float:
        return sum(overlap(a, b, c, d) for a, b in pieces_a for c, d in pieces_b)

    # ---- Recall e lances partidos ----
    alvo = [(l, p) for l, p in lances if l.kind == kind and not l.optional]
    por_lance = []
    for lance, pieces in alvo:
        length = sum(b - a for a, b in pieces)
        cobertura = sum(sobreposicao(pieces, sp) for _, sp in sug_pieces)
        pedacos = sum(1 for _, sp in sug_pieces if sobreposicao(pieces, sp) >= SPLIT_MIN_OVERLAP)
        fracao = cobertura / length if length > 0 else 0.0
        found = fracao >= RECALL_MIN_COVERAGE
        por_lance.append({"start": lance.start, "end": lance.end, "cobertura": round(fracao, 3),
                          "encontrado": found, "pedacos": pedacos, "partido": found and pedacos >= 2})
    encontrados = sum(1 for item in por_lance if item["encontrado"])
    partidos = sum(1 for item in por_lance if item["partido"])

    # ---- Classificação de cada sugestão ----
    por_sugestao = []
    for (start, end), pieces in sug_pieces:
        melhor_mesmo = 0.0
        correta = neutra = trocada = False
        for lance, lp in lances:
            s = sobreposicao(pieces, lp)
            if s <= 1e-6:
                continue
            piso = piso_sobreposicao(sum(b - a for a, b in lp), piso_segundos, piso_fracao)
            if lance.optional:
                neutra = neutra or _cobre(s, piso)
            elif lance.kind == kind:
                melhor_mesmo = max(melhor_mesmo, s)
                correta = correta or _cobre(s, piso)
            else:
                trocada = trocada or _cobre(s, piso)
        if correta:
            classe = "correta"
        elif neutra:
            classe = "neutra"
        elif trocada:
            classe = "errada_tipo_trocado"
        else:
            classe = "errada_fora_de_lance"
        por_sugestao.append({"start": start, "end": end, "classe": classe,
                             "sobreposicao_mesmo_tipo": round(melhor_mesmo, 2)})
    corretas = sum(1 for s in por_sugestao if s["classe"] == "correta")
    trocadas = sum(1 for s in por_sugestao if s["classe"] == "errada_tipo_trocado")
    fora = sum(1 for s in por_sugestao if s["classe"] == "errada_fora_de_lance")
    neutras = sum(1 for s in por_sugestao if s["classe"] == "neutra")
    erradas = trocadas + fora
    corretas_curtas = sum(1 for s in por_sugestao
                          if s["classe"] == "correta" and s["sobreposicao_mesmo_tipo"] < 2.0)

    recall = encontrados / len(alvo) if alvo else None
    razao = erradas / corretas if corretas else (None if erradas == 0 else float("inf"))
    return {
        "tipo": kind,
        "lances": len(alvo),
        "encontrados": encontrados,
        "recall": recall,
        "partidos": partidos,
        "sugestoes": len(por_sugestao),
        "corretas": corretas,
        "corretas_com_menos_de_2s": corretas_curtas,
        "neutras": neutras,
        "erradas": erradas,
        "erradas_tipo_trocado": trocadas,
        "erradas_fora_de_lance": fora,
        "erradas_por_correta": razao,
        "por_lance": por_lance,
        "por_sugestao": por_sugestao,
    }


def estimativa_revisao(sugestoes: int, partidos: int, duracao_analisada: float,
                       duracao_jogo: float = 60 * 60) -> dict:
    """ESTIMATIVA (não medição) do tempo de revisão, extrapolada para `duracao_jogo` de vídeo.

    Usa 12 s por sugestão e 10 s extras por lance partido. A cronometragem real fica para a Fase 5,
    quando existir a tela de revisão.
    """
    trecho = sugestoes * REVIEW_SECONDS_PER_SUGGESTION + partidos * REVIEW_SECONDS_PER_SPLIT
    fator = duracao_jogo / duracao_analisada if duracao_analisada > 0 else 0.0
    return {"segundos_no_trecho": round(trecho, 1), "segundos_por_jogo": round(trecho * fator, 1),
            "sugestoes_por_jogo": round(sugestoes * fator, 1), "duracao_jogo_suposta": duracao_jogo}


def veredito(resultado: dict, tempo_relativo: float | None, revisao_por_jogo: float | None) -> dict:
    """Compara com as metas. None = não dá para dizer (sem lances, sem medição, etc.)."""
    recall, razao = resultado["recall"], resultado["erradas_por_correta"]
    return {
        "recall": None if recall is None else recall >= META_RECALL,
        "erradas_por_correta": None if razao is None and resultado["sugestoes"] == 0 and resultado["lances"] == 0
        else (razao is not None and razao <= META_ERRADAS_POR_CORRETA) if razao is not None else True,
        "revisao_estimada": None if revisao_por_jogo is None else revisao_por_jogo < META_REVISAO_SEGUNDOS,
        "tempo_analise": None if tempo_relativo is None else tempo_relativo <= META_TEMPO_ANALISE,
    }


def somar(resultados: list[dict]) -> dict:
    """Junta os números de vários trechos/perspectivas (sem fazer média de porcentagens)."""
    keys = ["lances", "encontrados", "partidos", "sugestoes", "corretas", "corretas_com_menos_de_2s",
            "neutras", "erradas", "erradas_tipo_trocado", "erradas_fora_de_lance"]
    total = {key: sum(r[key] for r in resultados) for key in keys}
    total["recall"] = total["encontrados"] / total["lances"] if total["lances"] else None
    total["erradas_por_correta"] = (total["erradas"] / total["corretas"] if total["corretas"]
                                    else (None if total["erradas"] == 0 else float("inf")))
    return total
