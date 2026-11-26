# Roadmap: distribuição local

O app da Fase 1 será distribuído como programa local para Windows, sem servidor, em cinco etapas, e cada uma só termina quando o seu critério é cumprido.

## Decisões que sustentam o roadmap

Quatro decisões estão fechadas, quatro são provisórias e uma depende de teste.

| Decisão | Escolha | Status |
| --- | --- | --- |
| Hospedagem | App local no computador de cada usuário, sem servidor, para evitar custo de servidor e de armazenamento | Decidida |
| Sistema inicial | Windows primeiro; Mac depois, por ter poucos usuários | Decidida |
| Empacotamento | PyInstaller em modo pasta, com ffmpeg, ffprobe e Deno incluídos, e janela própria com pywebview | Decidida |
| Entrega | ZIP na fase de teste; instalador com Inno Setup depois | Decidida |
| Arquivo local | Lido onde está, pelo seletor de arquivos da janela, sem copiar | Decidida |
| Resolução do link do YouTube | Baixa até 480p para marcar; a exportação baixa só os trechos marcados em até 1080p. | Decidida |
| Resolução da saída | O usuário escolhe: 480p, 720p, 1080p ou original | Decidida |
| Velocidade da exportação | Manter o reencode atual (veryfast, CRF 23) | Decidida |
| Intervalos sobrepostos | Não juntar; lances seguidos do mesmo tipo são marcados como um corte só | Decidida |

## Roadmap

&#91;embedded content: roadmap · 5 etapas, 4 critérios de avanço\]

A etapa A, em destaque, é o foco agora. As setas mostram a ordem e o critério ao lado de cada etapa precisa ser cumprido antes de começar a seguinte; a etapa E não tem prazo.

## Checklist por etapa

Marque cada ação ao concluir; a etapa seguinte começa quando o critério da anterior é cumprido.

### A · Fechar a Fase 1 local

- [x] Trocar o `app.py` pela versão com registro de velocidade, exportar de novo o corte de 1h26 e guardar as linhas `[export ...]` do terminal.
- [x] Decidir o que fazer com a velocidade a partir do resultado: energia ou temperatura, conteúdo, ou ajuste de preset e CRF.
- [x] Decidir se juntamos intervalos sobrepostos e tiramos o `+faststart` das partes intermediárias.
- [x] Adicionar a escolha de resolução da saída (480p, 720p ou original).
- [x] Testar o download por trechos em 720p com o yt-dlp, com poucos e com muitos lances, e comparar com baixar o vídeo inteiro.
- [x] Fechar a decisão sobre o link: baixar até 480p para marcar e 720p só nos trechos.

### B · Empacotar para Windows

- [X] Criar o launcher que escolhe uma porta livre, sobe o servidor e abre a janela.
- [X] Abrir a janela com pywebview e usar o seletor de arquivos para ler o vídeo no lugar, sem copiar.
- [X] Mover vídeos, exportações e temporários para a pasta do usuário, por exemplo Vídeos.
- [X] Incluir ffmpeg, ffprobe e Deno no pacote e apontar o app para eles.
- [X] Adicionar o botão de atualizar o yt-dlp.
- [X] Adicionar o botão para limpar arquivos temporários e exportações antigas.
- [X] Escrever o script de build com PyInstaller em modo pasta e gerar o ZIP.
- [X] Testar em um PC limpo, sem Python, abrindo com duplo clique e exportando um jogo inteiro.

### C · Teste com usuários

- [X] Escrever um guia curto de instalação e uso, com o aviso do SmartScreen ("Mais informações → Executar assim mesmo").
- [X] Avisar os testadores de que a velocidade depende do computador de cada um.
- [X] Escolher testadores com computadores diferentes.
- [ ] Registrar, por teste, o tempo de exportação, os erros e as dúvidas.
- [ ] Atualizar riscos e decisões do documento com o que os testes mostrarem.

### D · Instalador e estabilidade

- [ ] Ler as condições de redistribuição do FFmpeg (GPL) e do Deno e registrar as atribuições no pacote.
- [ ] Criar o instalador com o Inno Setup.
- [ ] Gerar o instalador automaticamente com o GitHub Actions.
- [ ] Avaliar a assinatura digital do instalador (custo) para evitar o aviso do SmartScreen.
- [ ] Definir como o app avisa que há uma versão nova.
- [ ] Revisar os termos de uso do download de vídeos e fechar a decisão "Uso dos vídeos baixados".

### E · Depois, sem prazo (Fase 2 — sugestão automática com `YOLOX-s` `Apache-2.0`)

> **Status de licença (resolvido em 26/11/2026):** `models/yolo11n.onnx` (`AGPL-3.0`) foi substituído por `models/yolox_s.onnx` (`Apache-2.0`, acompanhado de `models/LICENSE-YOLOX.txt` e `models/NOTICE`) e removido completamente do histórico Git (`3B.5`). `build.py` já empacota o modelo permissivo e os arquivos de atribuição obrigatórios.

- [ ] Concluir o protocolo da Fase 2 em [Protocolo de Testes Fase 2.md](./Protocolo%20de%20Testes%20Fase%202.md) (pendente apenas o Plano B `1A-v2` para quadras bicolores com rede, como `Londrina x Pato.mp4`).
- [x] Decidir licença e modelo (`YOLOX-s` `Apache-2.0` congelado no Passo 3A/3B e histórico Git higienizado no Passo 3B.5).
- [ ] Implementar salvamento de marcações (Fase 1) e concluir a Etapa C para fechar o ciclo de testes com usuários.
- [ ] Fazer a versão para Mac (empacotamento, assinatura e notarização da Apple).
