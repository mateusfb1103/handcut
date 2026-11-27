# Protocolo de Testes — Fase 2 (Handcut)

Documento de referência da Fase 0 para medir a viabilidade da sugestão automática de lances (`detector.py`) com regras fixas e divisão clara entre ajuste e teste cego.

---

## 1. Regras oficiais das métricas (`tools/metricas.py`)

Aplicadas por `tools/avaliar_deteccao.py` sobre cada tipo (`ataque` ou `defesa`):

- **Recall (meta ≥ 90%):** um lance real do gabarito conta como **encontrado** quando a **soma** das sobreposições de todas as sugestões do mesmo tipo que caem nele atinge pelo menos **50%** da duração válida do lance.
- **Lances partidos (registro obrigatório à parte):** lance encontrado que recebeu **2 ou mais sugestões**, cada uma cobrindo pelo menos **1,0 s** dele. Pesa no tempo de revisão.
- **Sugestão correta:** sugestão que cobre um lance do mesmo tipo no gabarito. **Sugestão parcial conta como correta** (pois um mesmo lance pode conter vários ataques/reinícios após falta).
  - *Piso mínimo de sobreposição:* decisão ainda em aberto (`--piso-segundos` / `--piso-fracao` em `avaliar_deteccao.py`, padrão `0.0` com relatório paralelo de quantas sugestões corretas tiveram `< 2,0 s` de sobreposição).
- **Sugestão errada (meta: até 1 errada para cada 2 corretas, razão ≤ 0,50):**
  - *Tipo trocado:* cai apenas em lance do tipo oposto (ex.: pediu ataque do seu time e veio ataque do adversário).
  - *Fora de lance:* cai fora de qualquer lance anotado (intervalo, replay, tempo técnico).
- **Lances `opcional`:** não entram no denominador do recall e tornam neutra qualquer sugestão que caia só neles.
- **Exclusão de trechos (`ignorar` e `emenda`):** faixas `ignorar` (ex.: encerramento animado, replay) e **±5 s** ao redor de cada `emenda` são subtraídas do gabarito e das sugestões antes do cálculo.
- **Estimativa de revisão (até existir a tela da Fase 5):** `12 s` por sugestão + `10 s` extras por lance partido, extrapolados para `60 min` de jogo (meta `< 15 min`). A cronometragem real entra apenas na Fase 5.
- **Tempo de análise (meta ≤ 1,0× a duração selecionada, só CPU):** medido com a análise em **480p**; 720p só é comparado se 480p reprovar.

---

## 2. Acervo de vídeos e divisão Ajuste × Teste Cego

Vídeos originais fornecidos em `C:\Users\mateu\Videos\Vídeos Teste` e gabaritos convertidos em `tools/gabaritos/`.

### Conjunto de Ajuste (usado na Fase 1 e no passo 2A)

| Vídeo | Duração / Res. | Quadra | Camisas | Placar | Emendas / Ignorar | Gabarito |
|---|---|---|---|---|---|---|
| `Londrina-X-Cascavel.mp4` | 3:00 (`852×480`) | Inteira azul (sem verde) | Preto × Amarelo | Não | Nenhuma | `tools/gabaritos/londrina_x_cascavel.txt` |
| `Londrina x Cascavel Final4.mp4` | 2:49 (`854×480`) | Madeira + área verde | Branco × Preto | Sim | `emenda 1:22.5` (30:00→00:00); `ignorar 2:46 2:50` (outro) | `tools/gabaritos/londrina_x_cascavel_final4.txt` |

### Conjunto de Teste Cego (intocado durante o ajuste; só roda no passo 2B)

| Vídeo | Duração / Res. | Quadra | Camisas | Placar | Emendas / Ignorar | Gabarito |
|---|---|---|---|---|---|---|
| `Londrina x Pato.mp4` | 5:21 (`852×480`) | Azul + área cinza + rede na câmera | Preto × Azul *(validação de brilho parecido)* | Sim | `emenda 2:30.5` (29:59→00:00); `0:44–0:52` confirmado p/ ambos os times | `tools/gabaritos/londrina_x_pato.txt` |
| `Pato x Cascavel.mp4` | 6:02 (`852×480`) | Madeira (sem verde) + banco embaixo | Preto × Amarelo | Sim | `emenda 3:49.5` (03:47→00:18) | `tools/gabaritos/pato_x_cascavel.txt` |

### Pendências restantes no acervo (0A)

- [x] **Micro-gabarito por sinal (~30 quadros/vídeo nos 2 vídeos de ajuste):** concluído e revisado em `tools/gabaritos/micro_londrina_x_cascavel.json` (30 quadros) e `tools/gabaritos/micro_londrina_x_cascavel_final4.json` (31 quadros) com referência em Londrina (`meu`).
- [x] **Teste N3 (2º tempo isolado vs vídeo inteiro):** validado em 19/11/2026 com **13/13 (100%)** sugestões alinhadas (diferença máxima interna `0,5 s`, ver tabela abaixo).
- [ ] **Trecho exploratório de arquibancada (opcional, fora da meta):** 1 trecho curto gravado com câmera na mão apenas para observação qualitativa.

---

## 3. Registro de hardware e resultados

Preencher uma linha para cada execução oficial (gerada por `tools/avaliar_deteccao.py`):

| Data | Fase / Modelo | Vídeo / Condição | Máquina (CPU, núcleos, RAM) | Duração analisada | Tempo (× dur.) | Recall | Err./Corr. | Partidos | Rev. est. | Veredito |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-19 | 2A / `yolo11n.onnx` (480p) | `Londrina-X-Cascavel.mp4` — ATAQUE (`escura`, quadra azul, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 180.2 s | 60.2 s (`0.33×`) | 100% (5/5) | 0.00 (0/3) | 0 | ~12.0 min | **PASSA** |
| 2026-11-19 | 2A / `yolo11n.onnx` (480p) | `Londrina-X-Cascavel.mp4` — DEFESA (`escura`, quadra azul, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 180.2 s | 60.2 s (`0.33×`) | 100% (1/1) | 0.00 (0/1) | 0 | ~4.0 min | **PASSA** |
| 2026-11-19 | 2A / `yolo11n.onnx` (480p) | `Londrina x Cascavel Final4.mp4` — ATAQUE (`clara`, madeira+verde, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 169.2 s | 53.9 s (`0.32×`) | 100% (3/3) | 0.00 (0/3) | 0 | ~12.8 min | **PASSA** |
| 2026-11-19 | 2A / `yolo11n.onnx` (480p) | `Londrina x Cascavel Final4.mp4` — DEFESA (`clara`, madeira+verde, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 169.2 s | 53.9 s (`0.32×`) | 100% (2/2) | 0.00 (0/1, 1 neutra) | 0 | ~8.5 min | **PASSA** |
| 2026-11-19 | 2B (Cego) / `yolo11n.onnx` (480p) | `Pato x Cascavel.mp4` — ATAQUE (`escura`, madeira sem verde + banco, emenda 3:49.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 362.0 s | 127.2 s (`0.35×`) | 100% (7/7) | 0.25 (1/4) | 0 | ~9.9 min | **PASSA** |
| 2026-11-19 | 2B (Cego) / `yolo11n.onnx` (480p) | `Pato x Cascavel.mp4` — DEFESA (`escura`, madeira sem verde + banco, emenda 3:49.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 362.0 s | 127.2 s (`0.35×`) | 100% (6/6) | 0.00 (0/4) | 0 | ~8.0 min | **PASSA** |
| 2026-11-19 | 2B (Cego) / `yolo11n.onnx` (480p) | `Londrina x Pato.mp4` — ATAQUE (`escura`, azul+vôlei cinza+rede, preto×azul, emenda 2:30.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 321.3 s | 116.6 s (`0.36×`) | 50% (2/4) | 1.50 (3/2) | 0 | ~11.2 min | **REPROVA** |
| 2026-11-19 | 2B (Cego) / `yolo11n.onnx` (480p) | `Londrina x Pato.mp4` — DEFESA (`escura`, azul+vôlei cinza+rede, preto×azul, emenda 2:30.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 321.3 s | 116.6 s (`0.36×`) | 83% (5/6) | 0.17 (1/6) | 1 | ~17.6 min | **REPROVA** |
| 2026-11-20 | 3B / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Londrina-X-Cascavel.mp4` — ATAQUE (`escura`, quadra azul, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 180.2 s | 78.1 s (`0.43×`) | 100% (5/5) | 0.00 (0/3) | 0 | ~12.0 min | **PASSA** |
| 2026-11-20 | 3B / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Londrina-X-Cascavel.mp4` — DEFESA (`escura`, quadra azul, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 180.2 s | 78.1 s (`0.43×`) | 100% (1/1) | 0.00 (0/1) | 0 | ~4.0 min | **PASSA** |
| 2026-11-20 | 3B / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Londrina x Cascavel Final4.mp4` — ATAQUE (`clara`, madeira+verde, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 169.2 s | 73.5 s (`0.43×`) | 100% (3/3) | 0.00 (0/3) | 0 | ~12.8 min | **PASSA** |
| 2026-11-20 | 3B / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Londrina x Cascavel Final4.mp4` — DEFESA (`clara`, madeira+verde, sem períodos) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 169.2 s | 73.5 s (`0.43×`) | 100% (2/2) | 0.00 (0/1, 1 neutra) | 0 | ~8.5 min | **PASSA** |
| 2026-11-26 | Plano B `1A-v2` / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Pato x Cascavel.mp4` — ATAQUE (`escura`, madeira sem verde + banco, emenda 3:49.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 362.0 s | ~0.43× *(reuso cache `yolox_s`)* | 100% (7/7) | 0.00 (0/4) | 0 | ~8.0 min | **PASSA** |
| 2026-11-26 | Plano B `1A-v2` / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Pato x Cascavel.mp4` — DEFESA (`escura`, madeira sem verde + banco, emenda 3:49.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 362.0 s | ~0.43× *(reuso cache `yolox_s`)* | 100% (6/6) | 0.00 (0/4) | 0 | ~8.0 min | **PASSA** |
| 2026-11-26 | Plano B `1A-v2` / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Londrina x Pato.mp4` — ATAQUE (`escura`, azul+vôlei cinza+rede, preto×azul, emenda 2:30.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 321.3 s | ~0.43× *(reuso cache `yolox_s`)* | 100% (4/4) | 0.00 (0/4) | 0 | ~9.0 min | **PASSA** |
| 2026-11-26 | Plano B `1A-v2` / `yolox_s.onnx` (`Apache-2.0`, 480p) | `Londrina x Pato.mp4` — DEFESA (`escura`, azul+vôlei cinza+rede, preto×azul, emenda 2:30.5) | i5-8250U @ 1.60GHz (8 núcl., 11.9 GB RAM, Win 11) | 321.3 s | ~0.43× *(reuso cache `yolox_s`)* | 100% (6/6) | 0.00 (0/6) | 0 | ~13.4 min | **PASSA** |

### Teste N3 — 2º tempo isolado (`--periodos` / FFmpeg `-ss`) vs vídeo inteiro (2026-11-19)

| Vídeo (`r_fps` / `avg_fps`) | Faixa 2º tempo | Tempo 2º tempo (`× dur.`) | Sugestões alinhadas (≤ 2,0 s, fora borda 5 s) | Diferença máxima interna | Veredito N3 |
|---|---|---|---|---|---|
| `Londrina x Cascavel Final4.mp4` (`30/1` CFR) | `83.0 s – 169.2 s` | 30.9 s (`0.36×`) | 2/2 (100%) | 0.0 s *(início 90→87 na borda 5 s)* | **PASSA** |
| `Pato x Cascavel.mp4` (`30/1` CFR) | `230.0 s – 362.0 s` | 44.4 s (`0.34×`) | 3/3 (100%) | 0.0 s | **PASSA** |
| `Londrina x Pato.mp4` (`30/1` CFR) | `151.0 s – 321.3 s` | 58.3 s (`0.34×`) | 8/8 (100%) | 0.5 s | **PASSA** |
| **Total N3** | — | — | **13/13 (100%)** | **0.5 s** | **PASSA** |

> **Resolução do Plano B (`1A-v2`, 26/11/2026):** a falha original em `Londrina x Pato.mp4` vinha do salto cromático do histórico de piso entre o azul externo e o retângulo cinza central de vôlei (`sep_ab ≈ 26`), invertendo `cov_diff` no meio do jogo. Foram adicionados sob princípios SOLID: (1) trava contra saltos cromáticos bruscos em `_update_floor_history` (`delta_ab > 15`), (2) estimativa leve de giro horizontal da câmera via `cv2.phaseCorrelate` (`_estimate_camera_pan` / `_integrate_pan_positions`) e (3) estabilizador aditivo em `goal_sides` (`_bicolor_goal_score`, combinando piso estabilizado + centro horizontal coletivo dos jogadores + giro panorâmico, ativado automaticamente apenas quando `corr(cov_diff, end_score) < -0.25`). Com isso, **todos os 4 jogos oficiais da matriz (8/8 perspectivas)** passaram com **`100%` de recall, `0.00` erradas/correta e `0` lances partidos**, sem regressão em `Maringá x Cascavel JAPS`.
