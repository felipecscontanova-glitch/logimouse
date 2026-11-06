# Histórico de versões

## 1.3.1 (2026-11-06)

- Reconhece o receptor do **MCHOSE V9 Pro**, que usa o fabricante USB `291d` (produto `385d`), e não
  o `3837` do X9. O diagnóstico de um V9 Pro de verdade mostrou o mesmo canal de bateria do X9
  (report 0x55 de 63 bytes na página 0xff90).
- Receptores com "MCHOSE" no nome também são examinados, qualquer que seja o fabricante USB.
- Nome do modelo sem o prefixo do chip ("C-Media Electronics Inc MCHOSE V9 PRO" vira "MCHOSE V9 PRO").
- Regra udev inclui o fabricante `291d`: rode o `instalar.sh` de novo uma vez.
- Testes com o report descriptor real do receptor do V9 Pro.

## 1.3.0 (2026-11-06)

- Bateria de headsets **MCHOSE** (V9 Pro, V9, X9) pelo receptor 2.4 GHz, sem o M HUB: no painel
  (o headset aparece na lista junto com o mouse), na barra (`73%  🎧 58%`), no menu do ícone, no
  `--cli` e com aviso de bateria baixa.
- O receptor só recebe a pergunta da bateria se tiver o canal do fabricante (report 0x55 na
  página 0xff90); avisos espontâneos de bateria também são lidos.
- Headsets Bluetooth que informam bateria ao sistema (UPower) também aparecem.
- `logimouse --diagnostico`: relatório (USB, HID, conversa com o receptor, UPower) salvo em
  `~/logimouse-diagnostico.txt` para adaptar modelos novos.
- Regra udev inclui o fabricante USB 3837 (MCHOSE): rode o `instalar.sh` de novo uma vez.
- Corrige: o menu do ícone não se redesenhava quando só um dispositivo que não é o mouse mudava.

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
