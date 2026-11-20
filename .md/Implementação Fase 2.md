# Implementação Fase 2

## Contexto

> **Estado desta branch (`fase2-yolo`):** a integração no app é um **protótipo local** para testes e validação. Não vai para a `main`, não se deve rodar `build.py` nem enviar ZIP a testadores enquanto o modelo `AGPL-3.0` estiver no pacote e os pré-requisitos (prova de viabilidade, licença, salvamento de marcações e Etapa C) não estiverem concluídos.

O Handcut possui uma sugestão automática de lances baseada em YOLO. O modelo `yolo11n.onnx` (entrada fixa `544×960`, licença `AGPL-3.0` nos metadados) roda localmente, apenas na CPU (usando `cpu_count - 1` threads no `onnxruntime`), para localizar pessoas nos quadros do vídeo em `2.0` quadros por segundo (`SAMPLE_FPS = 2.0`). A versão inicial usa a luminosidade `L` (espaço LAB) da região da camisa para separar os times e o piso verde (`green_x`) para localizar o lado do gol, estimando ataque ou defesa pela distância até o gol.

## Regras oficiais de medição (Fase 0)

- **Recall (meta ≥ 90%):** soma-se a cobertura de todos os pedaços de sugestões do tipo pedido sobre um lance do gabarito; o lance conta como encontrado se a soma atingir ≥ 50%.
- **Lances partidos:** registrados à parte (lance encontrado coberto por ≥ 2 sugestões com ≥ 1 s cada).
- **Sugestão correta vs errada (meta: até 1 errada para cada 2 corretas):** sugestão parcial conta como correta; sugestão em tipo oposto ou fora de qualquer lance conta como errada; lances `opcional` são neutros; trechos `ignorar` e `±5 s` ao redor de cada `emenda` são removidos antes da contagem.
- **Revisão (< 15 min/jogo) e análise (≤ 1× duração em CPU):** detalhes e protocolo em [Protocolo de Testes Fase 2.md](./Protocolo%20de%20Testes%20Fase%202.md).

## Comportamento antes das alterações

Antes desta implementação, ao clicar em **Sugerir lances**, o programa fazia a seguinte análise:

1. Lia o vídeo inteiro em aproximadamente dois quadros por segundo, em 480p.
2. Executava o YOLO em cada quadro amostrado.
3. Agrupava os quadros classificados como ataque ou defesa em sugestões de lances.
4. Adicionava as sugestões escolhidas à lista de lances para revisão e exportação.

O comportamento era o mesmo independentemente de haver um, dois ou mais jogos na mesma transmissão. Assim, uma transmissão longa com vários jogos fazia o computador analisar também todos os trechos que não interessavam. Como a inferência roda na CPU, isso podia tornar a espera muito longa.

As teclas e botões `I` e `O` já serviam exclusivamente para marcar, respectivamente, o início e o fim de um lance manual que seria exportado.

## Alterações realizadas

### Interface

- Foi adicionado o bloco **Períodos para analisar** dentro de **Sugestão automática**.
- O botão **Marcar períodos de análise** alterna o destino das marcações `I` e `O`:
  - no modo normal, elas continuam criando lances manuais para exportação;
  - no modo de análise, elas criam um período de início e fim que será enviado ao YOLO.
- É possível registrar vários períodos de análise no mesmo vídeo.
- Cada período aparece em uma lista com horário de início, fim, duração, botão para reproduzir a partir dele e opção de remoção.
- A lista de períodos e a lista de lances manuais são independentes. Marcar um período não cria automaticamente um lance para exportação.
- Quando não há período delimitado, a interface e a API preservam o comportamento anterior: o vídeo inteiro é analisado.
- O resultado da análise em cache considera, além do vídeo e da cor da camisa, os períodos selecionados. Portanto, mudar um período exige uma nova análise, evitando reutilizar sugestões de outra seleção.

### API e processamento

- O endpoint `POST /api/suggest` passou a aceitar `periods`, uma lista de intervalos `{ start, end }`.
- Os períodos são validados no servidor: precisam ter início e fim numéricos válidos, estar dentro da duração do vídeo e ter fim posterior ao início.
- Períodos sobrepostos são ordenados e unidos para evitar executar o mesmo trecho mais de uma vez.
- Uma lista vazia, ou a ausência de `periods`, é convertida em um único intervalo que cobre todo o vídeo, mantendo compatibilidade com chamadas antigas.
- A leitura de quadros em `detector.py` agora aceita `start` e `end`. O FFmpeg busca e decodifica somente a faixa solicitada, em vez de percorrer a transmissão completa.
- O modelo YOLO é carregado uma vez por pedido de sugestão e reutilizado em todos os períodos daquele pedido.
- A barra de progresso considera a soma das durações selecionadas e informa qual período está sendo processado.

### Separação entre períodos

- A separação entre camisa clara e escura ainda usa os quadros de todos os períodos selecionados, produzindo um único limiar de luminosidade para a análise (com fallback silencioso fixo em `100.0` quando há menos de 50 observações de pessoas).
- Tanto a suavização do lado do gol (`goal_sides`, janela de mediana `±2,5 s`, chamada dentro de `label_samples`) quanto a suavização dos rótulos (`±1,0 s`) e a conversão de quadros em lances (`labels_to_segments`) acontecem separadamente em cada período.
- Essa separação impede que o fim de um período contamine o cálculo do lado do gol do próximo e impede que dois períodos próximos sejam fundidos em uma única sugestão através de um intervalo que o usuário não escolheu analisar.
- Toda sugestão fica limitada ao fim do período de análise correspondente.
- **Folga recomendada nas bordas:** como a suavização exige vizinhos e lances menores que `4,0 s` são descartados, recomenda-se deixar cerca de **5 segundos de folga** antes e depois de cada período relevante.

### Documentação e testes

- O README foi atualizado com as instruções para marcar períodos de análise e com a observação de que o tempo estimado é proporcional à duração selecionada.
- Foram incluídos testes automatizados para:
  - manter a análise do vídeo inteiro quando não há períodos;
  - ordenar, unir e limitar períodos ao tamanho do vídeo;
  - rejeitar períodos inválidos;
  - garantir que períodos próximos não sejam unidos através de uma lacuna não selecionada.
- Também foram executadas verificações de sintaxe de Python e JavaScript e verificação de espaços/erros no diff.

## Problemas encontrados e corrigidos

### Análise desnecessária de transmissões longas

**Problema:** a detecção percorria toda a transmissão, incluindo jogos que não seriam utilizados.

**Correção:** os intervalos escolhidos agora são enviados à API e usados para limitar a leitura de frames e a inferência do YOLO.

### Sugestões poderiam atravessar uma lacuna não analisada

**Problema:** se os quadros de vários períodos fossem tratados como uma sequência única, a regra que junta segmentos próximos poderia transformar dois períodos selecionados em um lance contínuo, incluindo uma lacuna que não foi analisada.

**Correção:** cada período é rotulado e transformado em segmentos de forma independente. O limiar de cor é compartilhado, mas nenhum segmento é unido entre períodos.

### Reutilização indevida do resultado automático

**Problema:** o cache da interface considerava somente o vídeo e a cor da camisa. Após mudar os períodos, seria possível reaproveitar sugestões calculadas para outra área do vídeo.

**Correção:** o cache agora também inclui uma assinatura dos períodos selecionados. Alterações na lista invalidam o resultado anterior.

## Possíveis problemas e limitações restantes

- A busca do FFmpeg para o começo de cada período depende da estrutura de quadros-chave do arquivo. Em alguns vídeos, o primeiro quadro efetivamente processado pode ficar muito próximo, mas não exatamente, do instante marcado. As sugestões ainda são limitadas ao período solicitado.
- Períodos muito curtos podem não conter quadros suficientes para que as regras de suavização e a duração mínima de um lance (`4,0 s`) produzam uma sugestão, ou cair abaixo de 50 observações de pessoas (ativando o fallback fixo `100.0` em `light_threshold`). Sem folga de ~5 s nas bordas, lances iniciados/encerrados junto ao corte do período podem ser descartados.
- Quadras sem piso verde (ex.: quadras inteiramente azuis ou de madeira sem área verde) zeram `green_x`, deixando todos os quadros como `indef` (0 sugestões); além disso, pares de camisas com brilho próximo (ex.: amarelo × vermelho ou preto × azul) não se separam apenas por luminosidade `L`, e árbitros/goleiros ainda entram na contagem de distância. Esses pontos fazem parte do plano da Fase 1.
- O limiar entre camisa clara e escura é calculado somente a partir dos períodos selecionados. Se um período tiver iluminação muito diferente dos demais, a separação dos times pode ficar menos confiável.
- A detecção continua dependente de câmera aberta, jogadores visíveis, camisas distinguíveis e identificação visual consistente da área do gol. Close-ups, replays, arquibancada e mudanças fortes de iluminação ainda podem gerar classificações indefinidas ou incorretas.
- O processamento é local e usa CPU. Delimitar períodos reduz proporcionalmente o trabalho, mas períodos longos ou muitos períodos ainda podem levar tempo, conforme o hardware.
- Não foi adicionada, nesta alteração, persistência dos períodos ao recarregar a página ou trocar de vídeo. Eles existem durante a sessão do vídeo aberto.

Nenhuma dessas limitações foi alterada neste momento; estão registradas para avaliação futura.
