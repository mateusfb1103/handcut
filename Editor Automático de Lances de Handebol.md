# Projeto: Editor Automático de Lances de Handebol

Oct 29, 2026 · @Mateus

## Visão geral

O projeto é um programa que recebe um jogo de handebol e devolve um único vídeo só com os lances de ataque ou de defesa do seu time. Hoje o processo manual (baixar, achar os lances, cortar e juntar) leva de horas a dias para um vídeo de 10 a 15 minutos.

A meta é trocar esse trabalho por alguns minutos de revisão. O caminho é construir em fases: primeiro um editor semiautomático que já economiza a maior parte do tempo, depois a identificação automática dos lances com visão computacional.

## Objetivos e não objetivos

O sucesso do projeto é medido por tempo economizado e por lances que não ficam de fora do vídeo final.

**Objetivos**

- Reduzir o tempo de produção de um vídeo de 10 a 15 minutos de dias para menos de 1 hora no MVP, e para menos de 15 minutos de revisão depois da automação.
- Gerar um vídeo final com apenas lances de ataque ou apenas de defesa, à escolha do usuário.
- Aceitar tanto link de vídeo quanto arquivo local.
- Priorizar não perder lances (recall) em vez de não errar nenhum (precisão), com margem de alguns segundos antes e depois de cada corte.

**Não objetivos (por enquanto)**

- Estatísticas automáticas do jogo (gols, assistências, mapa de calor).
- Classificar o tipo de jogada (6x0, 5x1, contra-ataque, 7m).
- Aplicativo de celular ou serviço online para outras equipes.
- Edição avançada (efeitos, narração, música).

## Fluxo do usuário

O usuário passa por sete etapas em linha reta, e só as duas últimas mudam entre o MVP e a versão automática.

1. **Entrada:** cola o link do vídeo ou envia o arquivo.
2. **Escolha:** seleciona se quer lances de ataque ou de defesa e informa a cor da camisa do seu time.
3. **Lado de ataque:** indica para qual lado da quadra, direita ou esquerda, o time ataca no 1º tempo. O programa inverte esse lado no 2º tempo. Como a transmissão continua durante o intervalo de cerca de 10 minutos, o usuário também marca em que ponto do vídeo o 2º tempo começa.
4. **Download:** o programa baixa o vídeo (ou usa o arquivo enviado) e guarda uma cópia local.
5. **Identificação dos lances:** no MVP, o usuário marca início e fim de cada lance por atalhos de teclado. Na Fase 2, o programa sugere os lances e o usuário revisa.
6. **Corte e junção:** o programa recorta cada lance, com margem de segurança, e junta tudo na ordem do jogo.
7. **Saída:** entrega um único arquivo de vídeo, pronto para assistir em grupo.

## Premissas sobre os vídeos

Os vídeos vêm de uma câmera em ponto fixo, operada por uma pessoa que só gira de um lado ao outro da quadra, sem zoom. Isso é um cenário favorável, mas com uma complicação: a câmera nunca mostra a quadra inteira ao mesmo tempo.

- **A favor:** o enquadramento é sempre largo, então os jogadores têm tamanho parecido em todo o vídeo, o que ajuda os detectores a acharem as pessoas. Zoom é muito raro e os replays aparecem poucas vezes, então há poucas trocas de câmera para atrapalhar; um replay que passar pode ser descartado na revisão.
- **Contra:** como a câmera gira, a posição do jogador na imagem não diz onde ele está na quadra. O programa precisa inferir o lado do jogo pela direção da câmera e pela posição dos times na imagem.
- **Consequência para o projeto:** em vez de mapear cada jogador em coordenadas exatas da quadra, a Fase 2 usa sinais mais simples: para que lado a câmera aponta e qual time (por cor da camisa) está mais avançado em direção ao gol que aparece na imagem.

Essas premissas precisam ser validadas com 2 ou 3 vídeos reais antes de começar a Fase 2.

## Fases do projeto

O projeto avança em três fases, e cada uma só começa depois que o critério da anterior é cumprido.

&#91;embedded content: fases do projeto · 3 fases, 2 critérios de avanço\]

A Fase 1 já entrega valor sozinha. A Fase 2 só começa se os testes com vídeos reais mostrarem que a câmera que gira não impede a detecção.

## Arquitetura técnica

No MVP, o programa tem três módulos comandados por uma interface local, e tudo roda em Python no computador do usuário.

&#91;embedded content: arquitetura · interface, 3 módulos e vídeo final\]

O módulo de identificação é o único que muda entre as fases: na Fase 1 é a marcação manual e, na Fase 2, passa a sugerir os lances para o usuário revisar na interface.

### Armazenamento e caminho para implantação

**MVP local:** o arquivo enviado ou baixado pelo `yt-dlp` fica na pasta `media/` do projeto, na máquina que está executando `python app.py`. O vídeo final é salvo em `exports/`. Portanto, os arquivos não ficam no computador que apenas abre a interface no navegador; ficam no computador que hospeda o processo Python.

**Conteinerização:** colocar o app em um container facilita empacotar Python, FFmpeg e bibliotecas, mas não transfere o processamento para uma infraestrutura mais potente por si só. O container executa no hardware do host. Arquivos gravados somente na camada interna do container podem desaparecer quando ele for removido; em desenvolvimento, usar um volume ou bind mount para persistir `media/` e `exports/`.

**Serviço futuro:** para não depender do hardware do usuário, a aplicação pode ser hospedada em um servidor e o processamento pode rodar em workers separados da interface. Uma arquitetura possível é:

1. A interface web recebe um link ou inicia o envio do arquivo.
2. O vídeo é armazenado em armazenamento de objetos, fora do container da aplicação.
3. A aplicação cria um trabalho em uma fila e informa seu andamento ao usuário.
4. Um worker baixa o vídeo do YouTube ou lê o arquivo armazenado, executa FFmpeg e, na Fase 2, a análise de visão computacional.
5. O vídeo final é guardado no armazenamento de objetos e disponibilizado ao usuário para baixar.
6. Uma política de retenção apaga vídeos de origem, arquivos temporários e resultados após um prazo definido, salvo se o usuário optar por mantê-los.

Os workers podem começar em máquinas com CPU e, se a automação da Fase 2 exigir, usar máquinas com GPU sem exigir GPU no computador do usuário. Separar os workers permite dimensionar a interface e o processamento de vídeo de forma independente. Isso transfere os requisitos de hardware para a infraestrutura do projeto e traz custos de processamento, armazenamento e tráfego de rede; vídeos grandes também podem levar tempo para serem enviados ao servidor.

Esta evolução é uma direção futura, não uma decisão de trocar o MVP local agora. Antes de disponibilizar o serviço, definir autenticação, limites de tamanho e duração, concorrência de trabalhos, prazo de retenção, exclusão dos arquivos e orçamento de infraestrutura. Para upload de arquivos grandes, avaliar envio direto do navegador ao armazenamento de objetos, reduzindo a passagem do arquivo pelo servidor da interface.

## Como identificar ataque e defesa

O MVP não precisa de IA: o usuário marca os lances e o programa só corta e junta. A IA entra na Fase 2, para sugerir os lances automaticamente, e funciona melhor como sugestão a ser revisada do que como decisão final.

**Abordagem da Fase 2 (câmera em ponto fixo que gira)**

1. Amostrar uns 5 quadros por segundo e detectar as pessoas com um modelo pronto (por exemplo YOLO), sem treinar nada do zero.
2. Rastrear cada jogador entre quadros para manter a identidade ao longo do lance.
3. Separar os times pela cor da camisa. Goleiros e árbitros, que têm cores diferentes, ficam de fora da contagem.
4. Estimar para que lado a câmera aponta medindo o movimento horizontal da imagem entre quadros (fluxo óptico, no OpenCV). Isso diz em qual metade da quadra o jogo está.
5. Combinar os dois sinais. Se a câmera mostra o lado do gol que o time ataca e a maior parte dos jogadores desse time está avançada, é ataque. Se mostra o gol que o time defende e ele está recuado, é defesa.
6. Suavizar o resultado, ignorar trechos menores que cerca de 3 segundos e acrescentar a margem de corte antes de mostrar as sugestões ao usuário.

**Informação que o usuário precisa dar:** a cor da camisa do seu time e para qual lado ele ataca no 1º tempo (direita ou esquerda). O programa inverte esse lado no 2º tempo e, como a transmissão não para no intervalo de cerca de 10 minutos, o usuário também marca onde o 2º tempo começa no vídeo.

**Limitações conhecidas:** a virada de posse em contra-ataques rápidos pode ser detectada com atraso, e a câmera às vezes demora para acompanhar a bola. Por isso a revisão humana continua no plano.

**Placar e tempo na tela:** como os vídeos mostram o cronômetro e o placar, uma melhoria futura é ler o relógio para achar sozinho o início do 2º tempo e o intervalo, e ler o placar para marcar os gols.

## Registro de decisões

Das doze decisões abaixo, três estão decididas, sete são provisórias e duas seguem em aberto.

| Decisão | Opções consideradas | Escolha atual | Motivo | Status |
| --- | --- | --- | --- | --- |
| Definição de lance | Posse completa; só finalizações | Posse completa | Dá contexto para ver padrões e erros, não só o fim da jogada | Provisória |
| Identificação do time | Cor da camisa; clicar em um jogador | Cor da camisa | Simples e vale para todos os lances do jogo | Provisória |
| Lado de ataque em cada tempo | Informado pelo usuário; detectado pelo programa | Usuário indica o lado do 1º tempo; o programa inverte no 2º | Os lados se invertem no 2º tempo; com o lado inicial informado, o programa inverte sozinho e erra menos | Provisória |
| Plataforma | App local; web | App local | Vídeos grandes e nenhum custo de servidor | Provisória |
| Linguagem e bibliotecas | Python com yt-dlp, FFmpeg, OpenCV e YOLO; outras stacks | Python com essas bibliotecas | Gratuitas e maduras para vídeo e detecção de pessoas | Provisória |
| Interface do MVP | Streamlit ou Gradio; player HTML próprio; arquivo de tempos marcados | A testar | Atalhos de teclado no player podem exigir HTML próprio | Em aberto |
| Processamento no MVP | Computador do usuário; servidor/nuvem | Computador do usuário | Mantém o MVP simples e sem custo recorrente de infraestrutura; numa versão disponibilizada como serviço, os workers podem processar os vídeos em hardware controlado pelo projeto | Provisória |
| Margem em cada corte | De 2 a 5 segundos | 3 s antes e 3 s depois, configurável | Evita cortar a jogada pela metade | Provisória |
| Revisão humana na Fase 2 | Obrigatória; opcional | Obrigatória | A detecção vai errar alguns lances, e perder lance é pior que sobrar um | Decidida |
| Uso dos vídeos baixados | Uso pessoal sem redistribuir; outros usos | Uso pessoal, sem redistribuir | Baixar de plataformas pode violar os termos de uso, e os vídeos costumam estar no YouTube | Em aberto |
| Formato do vídeo baixado | mp4; webm | mp4 (H.264 e AAC), em 720p para análise e até 1080p | Funciona com FFmpeg e OpenCV e abre em qualquer aparelho; 720p deixa a análise mais leve; o download pede H.264 de forma explícita, pois alguns mp4 do YouTube usam AV1 ou VP9, que o reprodutor do Windows pode não abrir | Decidida |
| Formato do vídeo final | mp4; webm; cópia sem reencodar | mp4 (H.264 e AAC), com os cortes reencodados | Abre em celular, TV e WhatsApp; reencodar garante o início exato de cada lance | Decidida |

## Riscos e mitigações

Os maiores riscos são a câmera que gira, que dificulta saber onde o jogo está, e o uso de vídeos baixados de plataformas.

| Risco | O que pode acontecer | Mitigação |
| --- | --- | --- |
| Câmera gira e não mostra a quadra inteira | O programa confunde ataque com defesa em alguns lances | Validar a abordagem com 2 ou 3 vídeos reais antes da Fase 2 e manter a revisão humana |
| Camisas de cor parecida entre os times, ou com o fundo | Jogadores atribuídos ao time errado | Usuário informa a cor no início; teste com vídeos de ginásios diferentes; correção manual como plano B |
| Vídeo com baixa resolução ou pouca luz | Menos jogadores detectados | Definir uma resolução mínima aceitável (por exemplo 720p) depois dos primeiros testes |
| Download de plataformas | Baixar vídeos do YouTube e similares pode ir contra os termos de uso do serviço | Tratar arquivo local como caminho principal e usar o download só para uso pessoal, sem redistribuir |
| Ferramenta de download quebra | A plataforma muda e o yt-dlp deixa de funcionar até sair atualização | Manter a opção de arquivo local sempre disponível e atualizar a biblioteca |
| Processamento lento sem GPU | Um jogo inteiro demora demais para analisar | Analisar 5 quadros por segundo em vez de todos, mostrar progresso e permitir analisar só um trecho e usar um modelo de detecção leve |
| Serviço hospedado e vídeos grandes | Upload, armazenamento e processamento aumentam custo e tempo de espera; dados podem ocupar o container ou permanecer mais tempo que o necessário | Separar armazenamento persistente e workers, impor limites, mostrar progresso e definir retenção e exclusão automática |
| Escopo crescer | Estatísticas e tipos de jogada atrasam o que importa | Respeitar a lista de não objetivos até a Fase 2 estar em uso |

A parte legal não é aconselhamento jurídico: vale confirmar com o clube ou a federação o que pode ser feito com as gravações dos jogos.

## Perguntas em aberto e próximos passos

O próximo passo concreto é construir o MVP e testá-lo em um jogo real; algumas respostas suas ajustam o plano antes disso.

**Perguntas em aberto**

- De onde vêm os vídeos: costumam estar em plataformas como o YouTube ou chegam como arquivos? Resposta: costumam estar no YouTube.
- Qual é o computador que vai rodar o programa, e ele tem placa de vídeo dedicada? Resposta: computadores pessoais, em geral sem placa dedicada.
- Qual é o seu nível de Python? Isso muda quanto do código posso entregar pronto e quanto você vai querer ajustar. Resposta: pouco Python, mas aprende rápido.
- Os vídeos mostram o placar na tela? Isso pode ajudar em refinamentos futuros. Resposta: sim, placar e tempo aparecem na tela.

**Próximos passos**

- [ ] Reunir 2 ou 3 vídeos reais de jogos, de preferência de ginásios diferentes, para validar as premissas.
- [ ] Montar o MVP: download, marcação de lances por atalhos e corte e junção com FFmpeg.
- [ ] Usar o MVP em um jogo real e medir quanto tempo levou.
- [ ] Fechar as decisões em aberto do registro, em especial a interface.
- [ ] Testar a detecção de jogadores e da direção da câmera nos vídeos de teste, para decidir se a Fase 2 é viável.
