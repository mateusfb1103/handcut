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

## Sugestão automática de lances (Fase 2)

Com um vídeo aberto, o bloco "Sugestão automática" analisa o jogo e adiciona à lista os trechos de ataque ou de defesa do seu time (marcados como "sugerido"). Você revisa, remove o que estiver errado e exporta como de costume.

- Escolha se o seu time veste camisa **clara** ou **escura** e se quer **ataques** ou **defesas**.
- Para vídeos com mais de um jogo, clique em **Marcar períodos de análise**. Os botões/atalhos `I` e `O` passam a delimitar um período; repita para adicionar quantos períodos precisar. Só esses trechos seguem para o YOLO. Clique novamente no botão para voltar a marcar lances manualmente. Sem períodos delimitados, a análise continua cobrindo o vídeo inteiro.
- Um modelo YOLO (`models/yolo11n.onnx`) acha os jogadores, a cor da camisa separa os times e o time mais perto do gol é o que defende. O código está em `detector.py`.
- Roda só na CPU. Em testes, analisar leva cerca de 0,2x da duração selecionada em um núcleo (1 hora de vídeo ≈ 12 minutos).
- Para medir o quanto acerta em outro jogo, anote os lances reais e rode `python tools/avaliar_deteccao.py VIDEO.mp4 GABARITO.txt --camisa clara` (o formato do gabarito está no começo do script).

## Observações

- O servidor escuta apenas em `127.0.0.1`, portanto a interface é acessível somente neste computador.
- O download do YouTube depende do `yt-dlp`, dos componentes EJS e do Deno; pode exigir atualização quando a plataforma mudar.
- O download informa as mensagens recentes do `yt-dlp`, limita as tentativas de rede e é encerrado após 2 horas.
- Use apenas vídeos cujo download e uso você esteja autorizado a fazer.
