# Editor de Lances de Handebol — MVP Fase 1

Aplicativo local para carregar um vídeo `.mp4` ou `.webm` (ou baixar um vídeo do YouTube), marcar os intervalos de interesse e exportá-los juntos em um único MP4.

## Requisitos

- Python 3.11 ou superior
- FFmpeg e FFprobe disponíveis no `PATH`
- Deno 2.3+ disponível no `PATH` para os desafios JavaScript atuais do YouTube
- `yt-dlp` com os componentes EJS (instalado pelo `requirements.txt`)

## Iniciar no Windows

1. Abra o PowerShell nesta pasta.
2. Crie e ative um ambiente virtual:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Instale as dependências:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Instale o Deno pelo [guia oficial](https://docs.deno.com/runtime/getting_started/installation/) e abra um novo terminal para que ele entre no `PATH`.

5. Confirme que `ffmpeg`, `ffprobe` e `deno` funcionam no terminal e inicie:

   ```powershell
   python app.py
   ```

6. Abra http://127.0.0.1:5000 no navegador.

## Marcação

- `Espaço`: reproduzir ou pausar
- `←` / `→`: voltar ou avançar 5 segundos
- `I`: marcar início do lance
- `O`: marcar fim e adicionar o intervalo à lista

Os intervalos são exportados na ordem do jogo. A margem padrão adiciona 3 segundos antes e depois de cada intervalo, limitada ao começo e ao fim do vídeo. A exportação reencoda em H.264 para permitir cortes precisos. Arquivos carregados ficam em `media/`; resultados ficam em `exports/`.

### Edição de lance específico (`03 / EDIÇÃO DE LANCE`)

- Na lista **Lances**, cada item exibe o botão **▶** (reproduzir a partir do início), o ícone de **lápis** (verde, para editar o lance) e o ícone de **`X`** (vermelho, para remover o lance).
- Ao clicar no ícone de **lápis**, a seção **02 / MARCAÇÃO** é recolhida automaticamente e abre a seção **03 / EDIÇÃO DE LANCE** com um player exclusivo limitado aos **30 segundos anteriores e posteriores** ao lance (reduzido automaticamente para `fim_anterior + 1 s` ou `início_posterior - 1 s` quando houver outro lance dentro dessa janela).
- Na barra exclusiva do player (branca com o intervalo do lance destacado em verde), arraste as **extremidades verdes** para estender ou encurtar início e fim com pré-visualização imediata do quadro, e clique em **CONFIRMAR** (salva o novo intervalo) ou **CANCELAR** (descarta). Em ambos os casos, o editor de lance fecha e a seção **02 / MARCAÇÃO** volta ao normal — evitando precisar aumentar a margem de corte global para todos os lances.
- Atalhos durante a edição de lance: `Espaço` (reproduzir ou pausar dentro da janela), `←` / `→` (voltar ou avançar 5 s na janela, ou ±1 s / ±0,5 s com `Shift` quando uma extremidade verde estiver focada) e `Esc` (cancelar).

## Sugestão automática de lances (Fase 2)

> **Estado atual:** modelo `YOLOX-s` (`Apache-2.0`) congelado e histórico Git higienizado (`3A/3B/3B.5` concluídas). A detecção está aprovada nos jogos de quadra padrão (`Londrina-X-Cascavel`, `Final4` e `Pato x Cascavel`) e segue em ajuste fino apenas para quadras bicolores com rede na frente da câmera (`Londrina x Pato`, Plano B `1A-v2`).

Com um vídeo aberto, o bloco "Sugestão automática" analisa o jogo e adiciona à lista os trechos de ataque ou de defesa do seu time (marcados como "sugerido"). Você revisa, ajusta início e fim de lances pontuais no ícone de lápis ou remove o que estiver errado no `X`, e exporta como de costume.

- Escolha a cor da camisa do seu time (clara, escura, cor específica ou clicando diretamente na camisa no vídeo) e se quer **ataques** ou **defesas**.
- Para vídeos com mais de um jogo, clique em **Marcar períodos de análise**. Os botões/atalhos `I` e `O` passam a delimitar um período; repita para adicionar quantos períodos precisar. **Recomendação:** deixe cerca de **5 segundos de folga** antes e depois de cada trecho relevante para que a suavização nas bordas não descarte lances próximos ao início ou ao fim do período. Só esses trechos seguem para o YOLO. Clique novamente no botão para voltar a marcar lances manualmente. Sem períodos delimitados, a análise continua cobrindo o vídeo inteiro.
- Um modelo YOLOX-s (`models/yolox_s.onnx`, licença `Apache-2.0`, ver `models/LICENSE-YOLOX.txt` e `models/NOTICE`) acha os jogadores, a cor da camisa separa os times e o time mais perto do gol é o que defende. O código está em `detector.py`.
- Roda só na CPU (usando todos os núcleos disponíveis menos um, para não travar a interface). Em testes na máquina de referência (i5-8250U), analisar levou cerca de `0,43x` da duração selecionada em 480p; o desempenho varia conforme o computador.
- Para medir o quanto acerta em outro jogo, anote os lances reais e rode `python tools/avaliar_deteccao.py VIDEO.mp4 GABARITO.txt --camisa clara` (o formato do gabarito está no começo do script e em `.md/Protocolo de Testes Fase 2.md`).

## Observações

- O servidor escuta apenas em `127.0.0.1`, portanto a interface é acessível somente neste computador.
- O download do YouTube depende do `yt-dlp`, dos componentes EJS e do Deno; pode exigir atualização quando a plataforma mudar.
- O download informa as mensagens recentes do `yt-dlp`, limita as tentativas de rede e é encerrado após 2 horas.
- Use apenas vídeos cujo download e uso você esteja autorizado a fazer.
