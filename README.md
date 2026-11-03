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

Os intervalos são exportados na ordem do jogo. A margem padrão adiciona 3 segundos antes e depois de cada intervalo, limitada ao começo e ao fim do vídeo. A exportação reencoda em H.264/AAC para permitir cortes precisos. Arquivos carregados ficam em `media/`; resultados ficam em `exports/`.

## Observações

- O servidor escuta apenas em `127.0.0.1`, portanto a interface é acessível somente neste computador.
- O download do YouTube depende do `yt-dlp`, dos componentes EJS e do Deno; pode exigir atualização quando a plataforma mudar.
- O download informa as mensagens recentes do `yt-dlp`, limita as tentativas de rede e é encerrado após 2 horas.
- Use apenas vídeos cujo download e uso você esteja autorizado a fazer.
