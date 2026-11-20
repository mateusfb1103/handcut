# Handcut — Revisão antes da Fase 2

Nov 11, 2026 · @Mateus (atualizado em Nov 18, 2026 com a entrada na Fase 0)

> **Nota (Nov 18, 2026):** Os registros preliminares no `handcut.log` (ex.: velocidade ~0,23x e 0 sugestões em quadra azul) serviram como diagnóstico inicial. A validação oficial das metas da Fase 2 segue o protocolo descrito em [Protocolo de Testes Fase 2.md](./Protocolo%20de%20Testes%20Fase%202.md).

Revisei o documento do projeto, o roadmap de distribuição, o guia de instalação e o estado do código. A tabela lista 33 pontos; o status de cada um é um dropdown, e as contagens mudam conforme você os ajusta.

## Revisão por ponto

Os pontos seguem a ordem Resolvido, Resolvido mas não documentado e Não resolvido; o status de cada um é um dropdown que você pode mudar.

| Ponto | Status | Detalhe e ação |
| --- | --- | --- |
| Hospedagem: app local, sem servidor | Resolvido | Projeto e Roadmap registram a decisão e o motivo (custo de servidor e de armazenamento). |
| Sistema inicial: Windows primeiro | Resolvido | Roadmap: Mac depois, por ter poucos usuários. |
| Revisão humana obrigatória na Fase 2 | Resolvido | Projeto: Decidida, porque perder lance é pior que sobrar um. |
| Velocidade da exportação | Resolvido | Roadmap: manter o reencode (veryfast, CRF 23); medido em 5,2× o tempo real em 720p. |
| Intervalos sobrepostos | Resolvido | Roadmap: não juntar; lances seguidos do mesmo tipo viram um corte só. |
| Etapas A e B do roadmap, guia de instalação e aviso aos testadores | Resolvido | Marcadas como concluídas; guia escrito; testadores serão avisados de que a velocidade depende do computador. |
| Perguntas em aberto do projeto | Resolvido | Origem dos vídeos (YouTube), computador (sem placa dedicada), nível de Python e placar na tela já têm resposta registrada. |
| Cookies do Firefox para o YouTube | Resolvido mas não documentado | Decisão A implementada (seletor "Cookies do navegador"). Chrome, Edge e Brave falham no Windows (DPAPI); importar cookies.txt e login dentro do app ficaram para depois. Falta o teste real no app e registrar no guia, na página, no roadmap e nos riscos. Quem não tem Firefox logado baixa o vídeo por outro meio e abre o arquivo. |
| Bloqueio de IP do YouTube ("Sign in to confirm you're not a bot") | Resolvido mas não documentado | Na rede de casa o download falha e nos dados móveis funciona; a extensão de VPN do Chrome não vale como teste. O guia só manda atualizar o yt-dlp. Acrescentar o erro, a causa e o que fazer ao guia e à tabela de riscos. |
| Formato do vídeo baixado | Resolvido | O registro diz mp4 H.264 e AAC em 720p. O app baixa só vídeo, sem áudio, em até 480p. Atualizar o registro. |
| Resolução do link e da saída | Resolvido | Decidido: o arquivo local mantém a qualidade original e ela não pode ser alterada; o link do YouTube é baixado em 480p para editar e a exportação oferece até 1080p (baixando de novo só os trechos marcados). O roadmap e o diagrama da etapa A ainda dizem 480p, 720p ou original e trechos em 720p. |
| Interface do MVP | Resolvido | Registro: Em aberto. Na prática: Flask local, player HTML próprio, atalhos I, O, Espaço e setas (5 s) e janela pywebview. Fechar a decisão. |
| Pilha técnica | Resolvido | O registro cita Python, yt-dlp, FFmpeg, OpenCV e YOLO. O app também usa Flask, Deno, pywebview e PyInstaller; OpenCV e YOLO ainda não entraram. |
| Status "Provisória" de decisões já testadas | Resolvido | Roadmap: Empacotamento, Entrega, Arquivo local e Resolução da saída. Projeto: Plataforma, Linguagem, Processamento e Margem (3 s). Revisar com você quais passam a Decidida. |
| Fase 1 sem escolha de ataque ou defesa, cor da camisa e lado | Resolvido | O fluxo do usuário descreve 7 etapas como se valessem no MVP. No app o usuário só marca início e fim; essas etapas são da Fase 2. |
| Nome e logo | Resolvido | O programa se chama Handcut e o logo já está no app; os documentos ainda usam "Editor Automático de Lances de Handebol". |
| Entrega de teste | Resolvido | O roadmap diz "ZIP". Na prática: ZIP no Google Drive, página do Handcut e guia de instalação. Registrar. |
| Avaliação da versão Mac | Resolvido | O roadmap só diz "Mac depois". Registrar: build em Mac na nuvem (GitHub Actions), alguém com Mac para testar e, para evitar o aviso do macOS, conta Apple (cerca de US$ 99 por ano). |
| Riscos de distribuição sem assinatura | Resolvido mas não documentado | SmartScreen, ZIP bloqueado pelo Windows e antivírus só aparecem no guia, não na tabela de riscos. |
| Áudio no vídeo final do YouTube | Resolvido | Decidido por você: o vídeo final do YouTube não terá áudio. Falta corrigir os textos que prometem AAC: a frase do app ("MP4 com H.264 e AAC"), o registro de decisões e a decisão "Formato do vídeo final". |
| Build nova e desbloqueio automático | Não resolvido | Confirmar em outro PC que o ZIP abre sem o Unblock-File. O ZIP do Drive pode ser anterior ao desbloqueio automático, à correção de foco, ao logo e aos cookies do Firefox: gerar com python build.py e reenviar. |
| Qualidade do vídeo do YouTube: edição em 480p e exportação até 1080p | Resolvido | Decidido por você: o programa baixa em 480p para editar e oferece exportar até 1080p. Falta fechar a decisão "Resolução do link" (Em aberto) no roadmap e confirmar se a exportação em 1080p já foi testada com um vídeo real do YouTube. |
| Termos de uso do download | Não resolvido | Registro: Em aberto; etapa D. Cookies da sua conta somam o risco de a conta ser sinalizada. |
| Teste de detecção da Fase 2 | Não resolvido | Trecho de 2 a 3 min da transmissão da liga. É o critério para avançar à Fase 2 e para validar a câmera que gira. |
| Qual vídeo a Fase 2 atende | Não resolvido | O registro supõe câmera fixa. A transmissão da liga tem placar e tempo; o jogo gravado da arquibancada com câmera na mão não. Decidir se o segundo tipo entra. |
| Resolução de análise × cópia local de 480p | Não resolvido | Só para a detecção: a qualidade de edição e de exportação já está decidida, mas o registro fala em 720p para análise e o app baixa 480p. Comparar a detecção a 480p e 720p (etapa E) antes de decidir se a cópia local deve subir. |
| Critério numérico da Fase 2 | Não resolvido | Só existe "priorizar recall". Definir uma meta, por exemplo a porcentagem de lances marcados que a sugestão encontra, para dizer se o teste passou. |
| Tempo total em jogo real | Não resolvido | O critério para a Fase 2 é produzir um vídeo de 10 a 15 min em menos de 1 hora. Nos documentos só há a medida da exportação; registrar marcação mais exportação. |
| Guardar as marcações | Não resolvido | Pelo código atual, as marcações ficam só na tela e se perdem ao fechar. Salvá-las evitaria a perda e daria o gabarito para medir a Fase 2. |
| Licença e peso do YOLO | Não resolvido | Os modelos da Ultralytics costumam ser AGPL-3.0 (confirmar) e o PyTorch soma centenas de MB ao ZIP de cerca de 150 MB. Avaliar alternativas (outro modelo, ONNX) antes de integrar. |
| Ordem das etapas C e D × Fase 2 | Não resolvido | C: registrar resultados dos testadores e atualizar riscos. D: licença do FFmpeg, instalador, GitHub Actions, assinatura e aviso de versão. O roadmap deixa o teste de detecção na etapa E; decidir se ele pode andar em paralelo. |
| Compartilhar a página e o link | Não resolvido | A página do Handcut está privada e é preciso conferir se o link do Drive abre para qualquer pessoa. Resolver antes de enviar aos testadores. |
