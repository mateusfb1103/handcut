# Handcut — Decisão de licença do modelo (Passo 3A/3B)

Nov 20, 2026 · @Mateus

## Decisão registrada (Passo 3A)

- **Escolha:** **Opção B — migrar para modelo ONNX de licença permissiva (`Apache-2.0` / `MIT`)**, acionando o **Passo 3B** imediatamente.
- **Paralelo:** solicitar cotação da licença Enterprise da Ultralytics (Opção A) apenas como referência real de custo.
- **Descartada:** Opção C (abrir o Handcut sob `AGPL-3.0`), por contradizer o objetivo de software fechado e vendável.
- **Aviso:** este registro não substitui aconselhamento jurídico; a conferência jurídica final dos termos `Apache-2.0` (incluindo origem oficial dos pesos) continua necessária antes da distribuição comercial.

---

## Opções avaliadas

**A. Licença Enterprise da Ultralytics.** Exigida para qualquer produto comercial ou uso sem abrir o código do projeto inteiro ([Ultralytics](https://www.ultralytics.com/request-license)). Assinatura anual sob medida em nome da pessoa jurídica que desenvolve o produto, com retorno em 24 a 72 horas.
- Custo recorrente pesa na margem de um produto que ainda não vendeu.
- Titularidade: confirmar exigência de CNPJ e regras ao encerrar a assinatura no contrato oficial.

**B. Migrar para um modelo permissivo (`Apache-2.0` / `MIT`).** Remove custo recorrente e favorece PCs fracos sem GPU. Obrigações leves do `Apache-2.0`: incluir o texto da licença (`LICENSE`) e o arquivo `NOTICE` no instalador/pacote. Aciona o **Passo 3B**.

**C. Abrir o Handcut sob `AGPL-3.0`.** Exige liberar o código do projeto inteiro sob `AGPL-3.0`. Descartada.

---

## Candidatos permissivos (Passo 3B)

A licença dos pesos deve ser conferida diretamente na origem oficial, nunca em reexportações de terceiros.

| Modelo | Licença | Observações |
| --- | --- | --- |
| **YOLOX** (`Megvii-BaseDetection/YOLOX`: nano, tiny, s, m) | `Apache-2.0` (código e pesos COCO oficiais) | Nano 25,8 mAP, Tiny 32,8, S 39,6. Exportação ONNX oficial. Candidato prioritário no 3B. |
| **RF-DETR** (Roboflow) | `Apache-2.0` apenas em Nano, Small, Medium e Large | Demais tamanhos usam licença própria da Roboflow (evitar). Contingência caso `YOLOX-s` e `YOLOX-tiny` não atinjam a meta. |
| **RT-DETR** (Baidu) | `Apache-2.0` no código | Licença separada dos pesos precisa ser confirmada; mais pesado (20M–76M params, risco em CPU antiga). |

**Modelos a evitar:** `YOLO-NAS` (restrição comercial nos pesos), `YOLOv7` / `YOLOv9`, e toda a família **Ultralytics** (`v5, v8, 10, 11, 12, 26` — `AGPL-3.0`).

---

## Auditoria do repositório (concluída em 20/11/2026)

- `models/yolo11n.onnx` (`10,7 MB`) **foi commitado** no commit `27448798` da branch `fase2-yolo` e existe no remoto `handcut/fase2-yolo` (`https://github.com/mateusfb1103/handcut`).
- **Não existe** na branch `master` nem em `feature/windows-desktop-packaging`.
- Não há código nem dependência da Ultralytics em `requirements.txt` ou `detector.py` (apenas `onnxruntime`, `opencv-python-headless` e `numpy`).
- **Ação obrigatória antes de distribuir/mesclar:** após congelar o modelo permissivo no Passo 3B, criar branch limpa a partir da `master` sem o binário `yolo11n.onnx` no histórico (ou higienizar a branch `fase2-yolo` e remover o binário do remoto).

---

## Resultado do Passo 3B (congelado em 20/11/2026)

- **Modelo congelado:** `models/yolox_s.onnx` (`34,2 MB`, entrada `640×640`, `CONF_MIN = 0.25`), baixado da release oficial `0.1.1rc0` de `Megvii-BaseDetection/YOLOX` sob licença **`Apache-2.0`**, acompanhado de `models/LICENSE-YOLOX.txt` e `models/NOTICE`.
- **Critérios do Passo 3B atingidos:**
  - Recuperação de jogadores vs `yolo11n.onnx` nos 61 quadros de referência: **93,6% (496/530)** (meta ≥ `90%`);
  - Velocidade real em CPU (i5-8250U, 480p, sem cache): **`0,43×`** nos 2 vídeos de ajuste (meta ≤ `0,50×`);
  - Conjunto de Ajuste (`2A`): **100% PASSA** (`Recall 100%`, `Err./Corr. 0,00`, `0 partidos`, `Rev. est. ≤ 12,8 min`).
- **`models/yolo11n.onnx` removido** do working tree (pendente apenas a etapa `3B.5` de higienização do histórico Git antes de distribuição/merge).

## Próximos passos

1. Enviar o formulário de licença da Ultralytics em paralelo (opcional, apenas referência de preço).
2. *(3B.5, antes de distribuir/mesclar)* Criar branch limpa a partir da `master` sem o binário `yolo11n.onnx` no histórico e remover a branch antiga `fase2-yolo` do remoto.
3. Avançar sobre o modelo congelado `yolox_s.onnx` para o **Plano B `1A-v2`** (quadras bicolores com rede) e re-validação final `2B` + `3C`.
