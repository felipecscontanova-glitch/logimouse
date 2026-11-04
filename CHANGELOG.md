# Histórico de versões

## 1.2.1 (2026-11-04)

- Corrige: às vezes o painel aplicava o DPI (ou outro ajuste) no mouse, mas não salvava. Um erro
  em qualquer parte do painel interrompia o processamento das respostas seguintes, e o ícone
  depois reaplicava o valor antigo ao reconectar.
- O painel agora salva o valor que você **escolheu**, não o que o mouse respondeu. Se o mouse
  ficar com outro valor, aparece um aviso (em mouses G, a dica é ligar o modo host).
- Se o mouse estiver dormindo ou desligado na hora, a escolha é salva e aplicada quando ele reconectar.
- Painel e ícone não podem mais sobrescrever o `config.json` um do outro (trava de arquivo).
- Testes do painel que reproduzem o problema (rodam no CI com tela virtual).

## 1.2.0 (2026-11-04)

- Atualização automática pelo GitHub (versão da branch main ou tags vX.Y.Z): o ícone na barra procura versão nova uma vez por dia,
  instala sozinho (sem pedir senha) e reabre já na versão nova.
- A versão nova é conferida antes de entrar no lugar (versão certa, tudo compila e abre) e a
  anterior fica guardada; `logimouse --rollback` volta para ela.
- Painel: versão atual, botão "Procurar atualização" e opção "Atualizar automaticamente".
- Menu do ícone: versão, "Procurar atualização agora" e "Atualizar automaticamente".
- Novos comandos: `--update`, `--check-update`, `--rollback`.

## 1.1.0 (2026-11-04)

- Ícone na barra com a % da bateria e aviso de bateria baixa.
- Ajustes salvos por mouse em `~/.config/logimouse/config.json`.
- Reaplica os ajustes ao iniciar e quando o mouse reconecta (desligar/ligar, receptor recolocado,
  Bluetooth reconectado).
- Opção de iniciar com o sistema, pelo painel, pelo ícone ou por `logimouse --autostart on`.
- Novo cartão "Aplicativo" no painel e botão "Esquecer ajustes".
- Novos comandos: `--tray`, `--reapply`, `--autostart`.
- Instalador instala as dependências sozinho (apt, dnf, pacman, zypper) e tem `--remover`.
- Código separado em módulos, com testes automáticos e CI.

## 1.0.0 (2026-11-04)

- Primeira versão: painel com bateria, DPI, velocidade do ponteiro, taxa de atualização,
  roda (catraca/livre, SmartShift, alta resolução, inverter) e modo host.
- Modo terminal (`--cli`, `--dpi`) e mouse simulado (`--demo`).
